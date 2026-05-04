# dashboard/app.py
# Streamlit web dashboard for the Smart Weather + Focus Monitor.
# Displays real-time and historical data fetched from Flask middleware.
# Assigned to: Amir

import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime
import data_loader as dl

# ============================================================
# PAGE CONFIGURATION
# ============================================================

st.set_page_config(
    page_title="Smart Monitor Dashboard",
    page_icon="🌤️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ============================================================
# CUSTOM STYLING
# ============================================================

st.markdown("""
    <style>
        /* Dark background for metric cards */
        [data-testid="metric-container"] {
            background-color: #1a1a2e;
            border: 1px solid #444;
            border-radius: 8px;
            padding: 12px;
        }
        /* Section headers */
        h2 { color: #4fc3f7; }
        h3 { color: #aaaaaa; }
        /* Sidebar */
        [data-testid="stSidebar"] { background-color: #0f0f1a; }
    </style>
""", unsafe_allow_html=True)

# ============================================================
# SIDEBAR
# ============================================================

with st.sidebar:
    st.title("⚙️ Settings")
    st.markdown("---")

    # Days selector — used by all historical charts
    days = st.slider("History (days)", min_value=1, max_value=30, value=7)

    # Manual refresh button — Streamlit auto-refreshes on interaction
    if st.button("🔄 Refresh Data"):
        st.cache_data.clear()

    st.markdown("---")
    st.caption("Smart Weather + Focus Monitor")
    st.caption("Cloud & Advanced Analytics — 2026")

# ============================================================
# HEADER
# ============================================================

st.title("🌤️ Smart Monitor Dashboard")
st.markdown("Real-time indoor/outdoor conditions and work session analytics.")
st.markdown("---")

# ============================================================
# SECTION 1 — REAL-TIME METRICS
# ============================================================

st.header("📡 Current Conditions")

latest  = dl.get_latest()
weather = dl.get_current_weather()
session = dl.get_current_session()

# Indoor metrics row
col1, col2, col3, col4 = st.columns(4)

with col1:
    temp = latest.get("temperature")
    st.metric(
        label="🌡️ Indoor Temp",
        value="{}°C".format(round(temp, 1)) if temp is not None else "N/A",
    )

with col2:
    hum = latest.get("humidity")
    delta_color = "inverse" if hum is not None and hum < 40 else "normal"
    st.metric(
        label="💧 Humidity",
        value="{}%".format(round(hum, 1)) if hum is not None else "N/A",
        delta="Low — use humidifier" if hum is not None and hum < 40 else None,
        delta_color=delta_color,
    )

with col3:
    co2 = latest.get("co2_ppm")
    aq  = latest.get("air_quality_label", "N/A")
    st.metric(
        label="🌬️ Air Quality",
        value=aq,
        delta="CO2: {} ppm".format(co2) if co2 else None,
        delta_color="inverse" if aq == "Poor" else "normal",
    )

with col4:
    current = weather.get("current", {})
    out_temp = current.get("temperature")
    st.metric(
        label="🌍 Outdoor Temp",
        value="{}°C".format(round(out_temp, 1)) if out_temp is not None else "N/A",
        delta=current.get("condition", ""),
    )

st.markdown("---")

# ============================================================
# SECTION 2 — WEATHER FORECAST
# ============================================================

st.header("📅 Weather Forecast")

forecast = weather.get("forecast", [])
if forecast:
    cols = st.columns(len(forecast))
    for i, day in enumerate(forecast):
        with cols[i]:
            st.markdown("**{}**".format(day.get("date", "---")))
            st.markdown("{}".format(day.get("condition", "N/A")))
            st.markdown("🌡️ {}/{} °C".format(
                round(day.get("temp_min", 0), 1),
                round(day.get("temp_max", 0), 1)
            ))
else:
    st.info("Weather forecast unavailable.")

st.markdown("---")

# ============================================================
# SECTION 3 — WORK SESSION STATUS
# ============================================================

st.header("⏱️ Work Session")

col1, col2, col3 = st.columns(3)

with col1:
    active = session.get("active", False)
    status = "🟢 Active" if active and not session.get("paused") \
        else "🟡 Paused" if session.get("paused") \
        else "⚪ No Session"
    st.metric(label="Status", value=status)

with col2:
    work_sec = session.get("work_seconds", 0)
    if work_sec:
        h = int(work_sec // 3600)
        m = int((work_sec % 3600) // 60)
        work_str = "{}h {}m".format(h, m) if h > 0 else "{}m".format(m)
    else:
        work_str = "—"
    st.metric(label="Work Time", value=work_str)

with col3:
    stats = dl.get_session_stats()
    avg   = stats.get("avg_work_minutes")
    st.metric(
        label="Avg Session",
        value="{}min".format(round(avg, 0)) if avg else "—"
    )

st.markdown("---")

# ============================================================
# SECTION 4 — INDOOR HISTORY CHARTS
# ============================================================

st.header("📊 Indoor History")

df_indoor = dl.get_indoor_history(days=days)

if not df_indoor.empty:
    # Temperature chart
    fig_temp = px.line(
        df_indoor,
        x="timestamp",
        y="temperature",
        title="Indoor Temperature (°C)",
        color_discrete_sequence=["#4fc3f7"],
        template="plotly_dark",
    )
    fig_temp.update_layout(
        plot_bgcolor="#1a1a2e",
        paper_bgcolor="#1a1a2e",
        xaxis_title="",
        yaxis_title="°C",
    )
    st.plotly_chart(fig_temp, use_container_width=True)

    # Humidity + CO2 side by side
    col1, col2 = st.columns(2)

    with col1:
        fig_hum = px.line(
            df_indoor,
            x="timestamp",
            y="humidity",
            title="Humidity (%)",
            color_discrete_sequence=["#81d4fa"],
            template="plotly_dark",
        )
        # Add threshold line at 40%
        fig_hum.add_hline(
            y=40,
            line_dash="dash",
            line_color="orange",
            annotation_text="Min threshold (40%)",
        )
        fig_hum.update_layout(
            plot_bgcolor="#1a1a2e",
            paper_bgcolor="#1a1a2e",
        )
        st.plotly_chart(fig_hum, use_container_width=True)

    with col2:
        if "co2_ppm" in df_indoor.columns:
            fig_co2 = px.line(
                df_indoor,
                x="timestamp",
                y="co2_ppm",
                title="CO2 (ppm)",
                color_discrete_sequence=["#a5d6a7"],
                template="plotly_dark",
            )
            # Add threshold line at 1000ppm
            fig_co2.add_hline(
                y=1000,
                line_dash="dash",
                line_color="red",
                annotation_text="Poor air threshold",
            )
            fig_co2.update_layout(
                plot_bgcolor="#1a1a2e",
                paper_bgcolor="#1a1a2e",
            )
            st.plotly_chart(fig_co2, use_container_width=True)
else:
    st.info("No indoor history available for the selected period.")

st.markdown("---")

# ============================================================
# SECTION 5 — OUTDOOR WEATHER HISTORY
# ============================================================

st.header("🌍 Outdoor Weather History")

df_outdoor = dl.get_outdoor_history(days=days)

if not df_outdoor.empty:
    fig_out = px.line(
        df_outdoor,
        x="timestamp",
        y="temperature",
        title="Outdoor Temperature (°C)",
        color_discrete_sequence=["#ffcc80"],
        template="plotly_dark",
    )
    fig_out.update_layout(
        plot_bgcolor="#1a1a2e",
        paper_bgcolor="#1a1a2e",
    )
    st.plotly_chart(fig_out, use_container_width=True)
else:
    st.info("No outdoor history available for the selected period.")

st.markdown("---")

# ============================================================
# SECTION 6 — SESSION ANALYTICS
# ============================================================

st.header("🎯 Session Analytics")

df_sessions = dl.get_session_history(limit=20)
stats       = dl.get_session_stats()

# Stats row
col1, col2, col3, col4 = st.columns(4)

with col1:
    st.metric(
        label="Total Sessions",
        value=stats.get("total_sessions", "—")
    )
with col2:
    avg = stats.get("avg_work_minutes")
    st.metric(
        label="Avg Work Time",
        value="{}min".format(round(avg, 1)) if avg else "—"
    )
with col3:
    total = stats.get("total_work_minutes")
    st.metric(
        label="Total Work Time",
        value="{}min".format(round(total, 0)) if total else "—"
    )
with col4:
    longest = stats.get("longest_session_minutes")
    st.metric(
        label="Longest Session",
        value="{}min".format(round(longest, 0)) if longest else "—"
    )

# Sessions bar chart
if not df_sessions.empty and "total_work_minutes" in df_sessions.columns:
    df_sessions["label"] = df_sessions["start_time"].dt.strftime("%b %d %H:%M")
    fig_sessions = px.bar(
        df_sessions,
        x="label",
        y="total_work_minutes",
        title="Work Sessions — Duration (minutes)",
        color_discrete_sequence=["#ce93d8"],
        template="plotly_dark",
    )
    fig_sessions.update_layout(
        plot_bgcolor="#1a1a2e",
        paper_bgcolor="#1a1a2e",
        xaxis_title="Session",
        yaxis_title="Minutes",
    )
    st.plotly_chart(fig_sessions, use_container_width=True)
else:
    st.info("No completed sessions yet.")

st.markdown("---")

# ============================================================
# SECTION 7 — RECENT ALERTS
# ============================================================

st.header("🔔 Recent Alerts")

df_alerts = dl.get_recent_alerts(limit=10)

if not df_alerts.empty:
    # Color code by alert type
    st.dataframe(
        df_alerts[["timestamp", "alert_type", "message"]],
        use_container_width=True,
        hide_index=True,
    )
else:
    st.success("No recent alerts.")