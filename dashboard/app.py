# dashboard/app.py
# Streamlit web dashboard — Smart Weather + Focus Monitor
# Assigned to: Amir

import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime
import pandas as pd
from streamlit_autorefresh import st_autorefresh
import data_loader as dl

# ============================================================
# PAGE CONFIG
# ============================================================
st.set_page_config(
    page_title="Smart Monitor",
    page_icon="🌤️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ============================================================
# AUTO-REFRESH — non-blocking JavaScript timer
# Reruns the script every 10s without freezing the worker.
# st_autorefresh returns the current refresh count (unused here).
# ============================================================
st_autorefresh(interval=10000, key="dashboard_refresh")

# ============================================================
# STYLING
# ============================================================
st.markdown("""
<style>
    /* Metric cards */
    [data-testid="metric-container"] {
        background: #0f0f1a;
        border: 1px solid #2a2a4a;
        border-radius: 10px;
        padding: 14px;
        transition: border-color .2s;
    }
    [data-testid="metric-container"]:hover { border-color: #4fc3f7; }

    /* Alert badges */
    .badge-ok   { background:#0d2b1a; color:#00cc44; border:1px solid #00cc44;
                  border-radius:6px; padding:2px 10px; font-size:.8rem; }
    .badge-warn { background:#2b1a00; color:#ffaa00; border:1px solid #ffaa00;
                  border-radius:6px; padding:2px 10px; font-size:.8rem; }
    .badge-bad  { background:#2b0000; color:#ff4444; border:1px solid #ff4444;
                  border-radius:6px; padding:2px 10px; font-size:.8rem; }

    /* Middleware status banner */
    .status-banner { padding:8px 16px; border-radius:8px; margin-bottom:12px;
                     font-size:.85rem; font-weight:600; }
    .status-ok   { background:#0d2b1a; color:#00cc44; border:1px solid #00cc44; }
    .status-down { background:#2b0000; color:#ff4444; border:1px solid #ff4444; }

    h2 { color:#4fc3f7; }
    [data-testid="stSidebar"] { background:#080810; }
</style>
""", unsafe_allow_html=True)

# ============================================================
# MIDDLEWARE HEALTH — displayed at the top so user sees immediately
# if data is stale because the server is down.
# ============================================================
latest  = dl.get_latest()
weather = dl.get_current_weather()
session = dl.get_current_session()
stats   = dl.get_session_stats()   # fetched ONCE, reused in sections 3 and 6

server_ok = bool(latest or weather or session)
if server_ok:
    st.markdown('<div class="status-banner status-ok">🟢 Middleware reachable — data live</div>',
                unsafe_allow_html=True)
else:
    st.markdown('<div class="status-banner status-down">🔴 Middleware unreachable — data may be stale</div>',
                unsafe_allow_html=True)

# ============================================================
# SIDEBAR
# ============================================================
with st.sidebar:
    st.title("⚙️ Settings")
    st.markdown("---")
    days = st.slider("History (days)", 1, 30, 7)

    if st.button("🔄 Refresh Now"):
        st.cache_data.clear()
        st.rerun()

    st.markdown("---")
    # Show last refresh time so user knows data freshness
    st.caption("🕐 Last refresh: {}".format(
        datetime.now().strftime("%H:%M:%S")))
    st.caption("Auto-refresh every 10s")
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
# SECTION 1 — CURRENT CONDITIONS
# ============================================================
st.header("📡 Current Conditions")

col1, col2, col3, col4 = st.columns(4)

with col1:
    temp = latest.get("temperature")
    st.metric("🌡️ Indoor Temp",
              "{}°C".format(round(temp, 1)) if temp is not None else "N/A")

with col2:
    hum = latest.get("humidity")
    low_hum = hum is not None and hum < 40
    st.metric("💧 Humidity",
              "{}%".format(round(hum, 1)) if hum is not None else "N/A",
              delta="Low — use humidifier" if low_hum else None,
              delta_color="inverse" if low_hum else "normal")

with col3:
    co2 = latest.get("co2_ppm")
    aq  = latest.get("air_quality_label", "N/A")
    badge_cls = {"Good": "badge-ok", "Moderate": "badge-warn", "Poor": "badge-bad"}.get(aq, "")
    st.metric("🌬️ Air Quality", aq,
              delta="CO2: {} ppm".format(co2) if co2 else None,
              delta_color="inverse" if aq == "Poor" else "normal")

with col4:
    current  = weather.get("current", {})
    out_temp = current.get("temperature")
    st.metric("🌍 Outdoor Temp",
              "{}°C".format(round(out_temp, 1)) if out_temp is not None else "N/A",
              delta=current.get("condition", ""))

st.markdown("---")

# ============================================================
# SECTION 2 — WEATHER FORECAST
# Icons mapped from OpenWeatherMap condition strings
# ============================================================
st.header("📅 Weather Forecast")

WEATHER_ICONS = {
    "clear": "☀️", "sun": "☀️", "cloud": "☁️", "rain": "🌧️",
    "drizzle": "🌦️", "thunder": "⛈️", "storm": "⛈️",
    "snow": "❄️", "mist": "🌫️", "fog": "🌫️", "haze": "🌫️",
}

def _weather_icon(condition):
    c = condition.lower()
    for k, v in WEATHER_ICONS.items():
        if k in c: return v
    return "🌤️"

forecast = weather.get("forecast", [])
if forecast:
    cols = st.columns(len(forecast))
    for i, day in enumerate(forecast):
        with cols[i]:
            cond = day.get("condition", "N/A")
            st.markdown("**{}**".format(day.get("date", "---")))
            st.markdown("## {}".format(_weather_icon(cond)))
            st.markdown("_{}_".format(cond))
            st.markdown("🌡️ **{}°** / {}°".format(
                round(day.get("temp_max", 0)),
                round(day.get("temp_min", 0))))
else:
    st.info("Weather forecast unavailable.")

st.markdown("---")

# ============================================================
# SECTION 3 — WORK SESSION STATUS
# stats already fetched above — no duplicate request
# ============================================================
st.header("⏱️ Work Session")

col1, col2, col3 = st.columns(3)

with col1:
    active = session.get("active", False)
    paused = session.get("paused", False)
    if active and not paused:
        status, color = "🟢 Active", "normal"
    elif active and paused:
        status, color = "🟡 Paused", "normal"
    else:
        status, color = "⚪ No Session", "off"
    st.metric("Status", status)

with col2:
    work_sec = session.get("work_seconds") or 0
    if work_sec > 0:
        h = int(work_sec // 3600)
        m = int((work_sec % 3600) // 60)
        s = int(work_sec % 60)
        work_str = ("{}h {}m".format(h, m) if h > 0
                    else "{}m {}s".format(m, s) if m > 0
                    else "{}s".format(s))
    else:
        work_str = "—"
    st.metric("Work Time", work_str)

with col3:
    avg = stats.get("avg_work_minutes")
    st.metric("Avg Session",
              "{}min".format(round(avg, 0)) if avg else "—")

st.markdown("---")

# ============================================================
# SECTION 4 — INDOOR HISTORY
# CO2 chart now has colored background zones (Good/Moderate/Poor)
# ============================================================
st.header("📊 Indoor History")

df = dl.get_indoor_history(days=days)

if not df.empty:
    # Temperature
    fig_t = px.line(df, x="timestamp", y="temperature",
                    title="Indoor Temperature (°C)",
                    color_discrete_sequence=["#4fc3f7"],
                    template="plotly_dark")
    fig_t.update_layout(plot_bgcolor="#0f0f1a", paper_bgcolor="#0f0f1a",
                        xaxis_title="", yaxis_title="°C")
    st.plotly_chart(fig_t, use_container_width=True)

    col1, col2 = st.columns(2)

    with col1:
        fig_h = px.line(df, x="timestamp", y="humidity",
                        title="Humidity (%)",
                        color_discrete_sequence=["#81d4fa"],
                        template="plotly_dark")
        fig_h.add_hline(y=40, line_dash="dash", line_color="orange",
                        annotation_text="Min 40%")
        fig_h.update_layout(plot_bgcolor="#0f0f1a", paper_bgcolor="#0f0f1a")
        st.plotly_chart(fig_h, use_container_width=True)

    with col2:
        if "co2_ppm" in df.columns:
            fig_c = px.line(df, x="timestamp", y="co2_ppm",
                            title="CO₂ (ppm) — colored zones",
                            color_discrete_sequence=["#a5d6a7"],
                            template="plotly_dark")
            # Background quality zones
            x_range = [df["timestamp"].min(), df["timestamp"].max()]
            for y0, y1, col, label in [
                (0, 800,  "rgba(0,204,68,.08)",  "Good"),
                (800, 1000,"rgba(255,170,0,.08)", "Moderate"),
                (1000,2000,"rgba(255,68,68,.08)", "Poor"),
            ]:
                fig_c.add_hrect(y0=y0, y1=y1, fillcolor=col,
                                line_width=0, annotation_text=label,
                                annotation_position="top left",
                                annotation_font_size=10)
            fig_c.add_hline(y=1000, line_dash="dash", line_color="red",
                            annotation_text="Poor threshold")
            fig_c.update_layout(plot_bgcolor="#0f0f1a", paper_bgcolor="#0f0f1a")
            st.plotly_chart(fig_c, use_container_width=True)
else:
    st.info("No indoor history for the selected period.")

st.markdown("---")

# ============================================================
# SECTION 5 — OUTDOOR HISTORY
# Now shows temperature + humidity together
# ============================================================
st.header("🌍 Outdoor Weather History")

df_out = dl.get_outdoor_history(days=days)

if not df_out.empty:
    col1, col2 = st.columns(2)
    with col1:
        fig_o = px.line(df_out, x="timestamp", y="temperature",
                        title="Outdoor Temperature (°C)",
                        color_discrete_sequence=["#ffcc80"],
                        template="plotly_dark")
        fig_o.update_layout(plot_bgcolor="#0f0f1a", paper_bgcolor="#0f0f1a")
        st.plotly_chart(fig_o, use_container_width=True)
    with col2:
        if "humidity" in df_out.columns:
            fig_oh = px.line(df_out, x="timestamp", y="humidity",
                             title="Outdoor Humidity (%)",
                             color_discrete_sequence=["#80cbc4"],
                             template="plotly_dark")
            fig_oh.update_layout(plot_bgcolor="#0f0f1a", paper_bgcolor="#0f0f1a")
            st.plotly_chart(fig_oh, use_container_width=True)
else:
    st.info("No outdoor history for the selected period.")

st.markdown("---")

# ============================================================
# SECTION 6 — SESSION ANALYTICS
# stats reused from section 3 — no duplicate request
# Bar chart now includes average line
# ============================================================
st.header("🎯 Session Analytics")

col1, col2, col3, col4 = st.columns(4)
with col1:
    st.metric("Total Sessions",  stats.get("total_sessions", "—"))
with col2:
    avg = stats.get("avg_work_minutes")
    st.metric("Avg Work Time",   "{}min".format(round(avg, 1)) if avg else "—")
with col3:
    total = stats.get("total_work_minutes")
    st.metric("Total Work Time", "{}min".format(round(total, 0)) if total else "—")
with col4:
    longest = stats.get("longest_session_minutes")
    st.metric("Longest Session", "{}min".format(round(longest, 0)) if longest else "—")

df_s = dl.get_session_history(limit=20)

if not df_s.empty and "total_work_minutes" in df_s.columns:
    df_s["label"] = df_s["start_time"].dt.strftime("%b %d %H:%M")
    fig_s = px.bar(df_s, x="label", y="total_work_minutes",
                   title="Work Sessions — Duration (min)",
                   color_discrete_sequence=["#ce93d8"],
                   template="plotly_dark")
    # Average line across sessions
    if avg:
        fig_s.add_hline(y=avg, line_dash="dash", line_color="#4fc3f7",
                        annotation_text="Average ({:.0f}min)".format(avg),
                        annotation_position="top right")
    fig_s.update_layout(plot_bgcolor="#0f0f1a", paper_bgcolor="#0f0f1a",
                        xaxis_title="Session", yaxis_title="Minutes")
    st.plotly_chart(fig_s, use_container_width=True)
else:
    st.info("No completed sessions yet.")

st.markdown("---")

# ============================================================
# SECTION 7 — ALERTS
# Color-coded rows by alert type
# ============================================================
st.header("🔔 Recent Alerts")

df_a = dl.get_recent_alerts(limit=10)

if not df_a.empty:
    # Map alert types to emoji for quick visual scanning
    if "alert_type" in df_a.columns:
        icon_map = {"TTS_ALERT": "🔊", "HUMIDITY": "💧",
                    "AIR": "🌬️", "WEATHER": "⛈️"}
        df_a["Type"] = df_a["alert_type"].map(
            lambda x: "{} {}".format(icon_map.get(x, "⚠️"), x))
        st.dataframe(
            df_a[["timestamp", "Type", "message"]].rename(
                columns={"timestamp": "Time", "message": "Message"}),
            use_container_width=True, hide_index=True)
    else:
        st.dataframe(df_a, use_container_width=True, hide_index=True)
else:
    st.success("✅ No recent alerts — everything looks good.")