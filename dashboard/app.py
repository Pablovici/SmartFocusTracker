# dashboard/app.py
# Streamlit web dashboard — Smart Weather + Focus Monitor
# Upgraded UI/UX — Assigned to: Amir

import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime
import pandas as pd
from streamlit_autorefresh import st_autorefresh
import data_loader as dl

# ============================================================
# PAGE CONFIG — must be the FIRST Streamlit command called.
# layout="wide" removes the default content max-width cap.
# ============================================================
st.set_page_config(
    page_title="SmartFocusTracker",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ============================================================
# AUTO-REFRESH — non-blocking JavaScript timer injected by
# streamlit-autorefresh. Triggers a full script rerun every
# 10 000 ms without freezing the Streamlit server thread.
# The return value is the refresh count; we don't need it.
# ============================================================
st_autorefresh(interval=10_000, key="dashboard_refresh")

# ============================================================
# CSS — comprehensive dark theme.
#
# Font choices (deliberately non-generic):
#   Syne        — geometric display font for headers/labels
#   DM Sans     — clean, slightly rounded body text
#   JetBrains Mono — technical monospace for all numeric values
#
# Colors mirror the device UI palette for brand coherence:
#   Accent  #5bc8f5  (M5Stack accent blue)
#   Good    #00cc44  (working / green LED)
#   Warn    #ffaa00  (paused / orange LED)
#   Bad     #ff4444  (alerts / red LED)
#   BG      #06060f  (deeper than device for OLED-style depth)
# ============================================================
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Syne:wght@600;700;800&family=DM+Sans:wght@300;400;500&family=JetBrains+Mono:wght@400;500&display=swap');

/* ── Global ── */
html, body, [class*="css"] {
    font-family: 'DM Sans', sans-serif !important;
    -webkit-font-smoothing: antialiased;
}

/* ── App background with subtle dot-grid texture ── */
.stApp {
    background-color: #06060f !important;
    background-image: radial-gradient(circle, #1a1a38 1px, transparent 1px) !important;
    background-size: 28px 28px !important;
}
[data-testid="stAppViewContainer"] { background: transparent !important; }
.main .block-container { padding-top: 1.4rem; padding-bottom: 2rem; }

/* ── Metric cards — glassmorphism-lite ── */
[data-testid="metric-container"] {
    background: linear-gradient(145deg, rgba(13,13,30,0.95) 0%, rgba(18,18,40,0.9) 100%);
    border: 1px solid #1c1c3a;
    border-radius: 14px;
    padding: 18px 20px;
    backdrop-filter: blur(8px);
    transition: border-color 0.2s ease, transform 0.2s ease, box-shadow 0.2s ease;
    animation: fadeUp 0.4s ease both;
    position: relative;
    overflow: hidden;
}
[data-testid="metric-container"]::before {
    content: '';
    position: absolute; top: 0; left: 0; right: 0; height: 2px;
    background: linear-gradient(90deg, #5bc8f5 0%, rgba(91,200,245,0.1) 60%, transparent 100%);
}
[data-testid="metric-container"]:hover {
    border-color: #5bc8f5;
    transform: translateY(-3px);
    box-shadow: 0 10px 30px rgba(91,200,245,0.1);
}
[data-testid="stMetricLabel"] {
    font-family: 'Syne', sans-serif !important;
    font-size: 0.65rem !important;
    font-weight: 700 !important;
    text-transform: uppercase;
    letter-spacing: 0.14em;
    color: #44446a !important;
}
[data-testid="stMetricValue"] {
    font-family: 'JetBrains Mono', monospace !important;
    font-size: 1.65rem !important;
    font-weight: 500 !important;
    color: #dde4ff !important;
    letter-spacing: -0.01em;
}
[data-testid="stMetricDelta"] {
    font-family: 'DM Sans', sans-serif !important;
    font-size: 0.75rem !important;
}

/* ── Tabs ── */
[data-baseweb="tab-list"] {
    background: rgba(6,6,15,0.8) !important;
    border-bottom: 1px solid #1c1c3a !important;
    gap: 2px;
    padding: 0 4px;
}
[data-baseweb="tab"] {
    font-family: 'Syne', sans-serif !important;
    font-size: 0.78rem !important;
    font-weight: 700 !important;
    letter-spacing: 0.04em;
    color: #44446a !important;
    padding: 11px 20px !important;
    border-radius: 8px 8px 0 0 !important;
    transition: color 0.15s, background 0.15s;
}
[data-baseweb="tab"]:hover { color: #8888cc !important; }
[aria-selected="true"][data-baseweb="tab"] {
    color: #5bc8f5 !important;
    background: rgba(91,200,245,0.06) !important;
    border-bottom: 2px solid #5bc8f5 !important;
}

/* ── Section dividers ── */
.sec-head {
    font-family: 'Syne', sans-serif;
    font-size: 0.62rem;
    font-weight: 800;
    text-transform: uppercase;
    letter-spacing: 0.16em;
    color: #5bc8f5;
    margin: 28px 0 14px;
    display: flex;
    align-items: center;
    gap: 10px;
}
.sec-head::after {
    content: '';
    flex: 1;
    height: 1px;
    background: linear-gradient(90deg, #1c1c3a 0%, transparent 100%);
}

/* ── Middleware status banner ── */
.status-banner {
    padding: 9px 18px;
    border-radius: 10px;
    margin-bottom: 18px;
    font-family: 'Syne', sans-serif;
    font-size: 0.75rem;
    font-weight: 700;
    letter-spacing: 0.06em;
    display: flex;
    align-items: center;
    gap: 10px;
}
.status-ok   { background: rgba(0,204,68,0.07);  color: #00cc44; border: 1px solid rgba(0,204,68,0.2); }
.status-down { background: rgba(255,68,68,0.07); color: #ff4444; border: 1px solid rgba(255,68,68,0.2); }

/* ── Pulse animation for live dot ── */
@keyframes pulse { 0%,100%{opacity:1;transform:scale(1)} 50%{opacity:0.35;transform:scale(0.85)} }
.live-dot {
    display: inline-block;
    width: 7px; height: 7px;
    border-radius: 50%;
    background: #00cc44;
    animation: pulse 1.6s ease infinite;
    box-shadow: 0 0 6px #00cc44;
    vertical-align: middle;
}

/* ── Fade-up entrance animation ── */
@keyframes fadeUp { from{opacity:0;transform:translateY(10px)} to{opacity:1;transform:translateY(0)} }

/* ── Forecast cards ── */
.forecast-grid { display: flex; gap: 8px; }
.fc {
    flex: 1;
    background: linear-gradient(170deg, rgba(13,13,30,0.98) 0%, rgba(9,9,20,0.95) 100%);
    border: 1px solid #1c1c3a;
    border-radius: 16px;
    padding: 16px 8px;
    text-align: center;
    transition: all 0.2s ease;
    cursor: default;
}
.fc:hover {
    border-color: #5bc8f5;
    transform: translateY(-4px);
    box-shadow: 0 10px 28px rgba(91,200,245,0.1);
}
.fc-day  { font-family:'Syne',sans-serif; font-size:0.58rem; font-weight:800; text-transform:uppercase; letter-spacing:0.14em; color:#44446a; margin-bottom:10px; }
.fc-icon { font-size:2rem; margin-bottom:8px; display:block; }
.fc-cond { font-size:0.6rem; color:#555577; margin-bottom:10px; line-height:1.4; min-height:26px; }
.fc-hi   { font-family:'JetBrains Mono',monospace; font-size:1.05rem; font-weight:500; color:#ffcc80; }
.fc-lo   { font-family:'JetBrains Mono',monospace; font-size:0.8rem; color:#44446a; }

/* ── Session status badge ── */
.session-pill {
    border-radius: 10px;
    padding: 14px 18px;
    text-align: center;
    font-family: 'Syne', sans-serif;
    font-weight: 800;
    font-size: 0.85rem;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    margin-bottom: 6px;
}
.sp-working { background:rgba(0,204,68,0.09);  border:1px solid rgba(0,204,68,0.3);  color:#00cc44; }
.sp-paused  { background:rgba(255,170,0,0.09); border:1px solid rgba(255,170,0,0.3); color:#ffaa00; }
.sp-idle    { background:rgba(91,200,245,0.07); border:1px solid rgba(91,200,245,0.2); color:#5bc8f5; }

/* ── Alert rows ── */
.alert-row {
    border-radius: 0 10px 10px 0;
    padding: 10px 16px;
    margin-bottom: 8px;
    border-left: 3px solid;
    animation: fadeUp 0.3s ease both;
}
.ar-warn { background:rgba(255,170,0,0.06); border-left-color:#ffaa00; }
.ar-bad  { background:rgba(255,68,68,0.06);  border-left-color:#ff4444; }
.ar-info { background:rgba(91,200,245,0.05); border-left-color:#5bc8f5; }
.ar-time { font-family:'JetBrains Mono',monospace; font-size:0.65rem; color:#44446a; margin-bottom:3px; }
.ar-type { font-family:'Syne',sans-serif; font-size:0.62rem; font-weight:800; text-transform:uppercase; letter-spacing:0.1em; margin-bottom:3px; }
.ar-msg  { font-size:0.82rem; color:#aaaacc; }

/* ── Sidebar ── */
[data-testid="stSidebar"] {
    background: rgba(4,4,12,0.97) !important;
    border-right: 1px solid #12122a !important;
}
[data-testid="stSidebar"] .stMarkdown p,
[data-testid="stSidebar"] .stMarkdown li { font-size: 0.82rem; color: #555577; }

/* ── Dividers ── */
hr { border-color: #12122a !important; margin: 0.8rem 0 !important; }

/* ── Info / success boxes ── */
[data-testid="stInfo"]    { background:rgba(91,200,245,0.06) !important; border:1px solid rgba(91,200,245,0.18) !important; }
[data-testid="stSuccess"] { background:rgba(0,204,68,0.06)   !important; border:1px solid rgba(0,204,68,0.18)   !important; }

/* ── Scrollbar ── */
::-webkit-scrollbar { width:6px; height:6px; }
::-webkit-scrollbar-track { background:#06060f; }
::-webkit-scrollbar-thumb { background:#22224a; border-radius:3px; }
::-webkit-scrollbar-thumb:hover { background:#33336a; }
</style>
""", unsafe_allow_html=True)


# ============================================================
# HELPERS
# ============================================================

# Mapping of OpenWeatherMap condition keywords → emoji
# The dict is ordered: first match wins, so "thunderstorm" before "rain"
WEATHER_ICONS = {
    "thunder": "⛈️", "storm": "⛈️", "tornado": "🌪️",
    "snow": "❄️",    "sleet": "🌨️", "blizzard": "❄️",
    "rain": "🌧️",    "drizzle": "🌦️", "shower": "🌦️",
    "fog": "🌫️",     "mist": "🌫️",  "haze": "🌫️",
    "cloud": "☁️",   "overcast": "☁️",
    "clear": "☀️",   "sun": "☀️",
    "wind": "💨",
}

def _weather_icon(condition: str) -> str:
    """Returns the most relevant emoji for a condition string."""
    c = condition.lower()
    for keyword, icon in WEATHER_ICONS.items():
        if keyword in c:
            return icon
    return "🌤️"

def _fmt_duration(seconds) -> str:
    """
    Converts a raw seconds integer to a readable 'Xh Xm' or 'Xm Xs' string.
    Returns '—' for zero / None values so the UI never shows '0s'.
    """
    if not seconds or seconds <= 0:
        return "—"
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h > 0: return f"{h}h {m}m"
    if m > 0: return f"{m}m {sec}s"
    return f"{sec}s"

def _comfort_index(temp, humidity):
    """
    Calculates a thermal comfort score (0–100) from indoor temp and humidity.

    Logic:
      - Temperature ideal zone: 21–23°C  → peak score, drops 9 pts per °C away
      - Humidity ideal zone:    45–55%   → peak score, drops 2 pts per % away
      - Temp is weighted 60%, humidity 40% (temp has larger physiological impact)

    Returns (score int, label str, hex_color str).
    """
    if temp is None or humidity is None:
        return None, "N/A", "#44446a"
    temp_score = max(0, 100 - abs(temp - 22) * 9)
    hum_score  = max(0, 100 - abs(humidity - 50) * 2)
    score = round(temp_score * 0.6 + hum_score * 0.4)
    if score >= 70: return score, "Comfortable 😌", "#00cc44"
    if score >= 45: return score, "Acceptable 🙂",  "#ffaa00"
    return score, "Uncomfortable 😓", "#ff4444"

def _co2_color(ppm) -> str:
    """Maps a CO₂ ppm value to a traffic-light color string."""
    if ppm is None: return "#888899"
    if ppm < 800:   return "#00cc44"
    if ppm < 1000:  return "#ffaa00"
    return "#ff4444"

# Shared Plotly layout applied to every chart for visual consistency.
# Centralising this avoids repeating 12-line update_layout calls everywhere.
_CHART_BASE = dict(
    template="plotly_dark",
    plot_bgcolor="rgba(8,8,20,0.0)",
    paper_bgcolor="rgba(8,8,20,0.0)",
    font=dict(family="DM Sans, sans-serif", color="#555577", size=11),
    margin=dict(l=48, r=16, t=44, b=40),
    hovermode="x unified",
    hoverlabel=dict(
        bgcolor="#13132a", bordercolor="#2a2a50",
        font=dict(family="DM Sans", size=11)),
    legend=dict(bgcolor="rgba(0,0,0,0)", bordercolor="#1c1c3a"),
)

def _apply_theme(fig, title: str = None, y_title: str = None,
                 y2_title: str = None):
    """
    Stamps the shared dark theme onto a Plotly figure.
    Accepts optional axis labels so callers stay concise.
    """
    layout = dict(
        **_CHART_BASE,
        xaxis=dict(gridcolor="#12122a", linecolor="#1c1c3a", title="",
                   tickfont=dict(size=10)),
        yaxis=dict(gridcolor="#12122a", linecolor="#1c1c3a",
                   title=dict(text=y_title or "", font=dict(size=10)),
                   tickfont=dict(size=10)),
    )
    if title:
        layout["title"] = dict(
            text=title,
            font=dict(family="Syne, sans-serif", color="#ccccee", size=13),
            x=0, pad=dict(l=0))
    if y2_title:
        layout["yaxis2"] = dict(
            gridcolor="#0e0e22", linecolor="#1c1c3a",
            title=dict(text=y2_title, font=dict(size=10)),
            tickfont=dict(size=10), overlaying="y", side="right")
    fig.update_layout(**layout)
    return fig


# ============================================================
# DATA FETCHING — all calls at the top of the script.
# Streamlit re-runs the entire script on each refresh;
# by fetching here (cached in data_loader), every section
# below reuses the same response objects without extra HTTP calls.
# ============================================================
latest  = dl.get_latest()
weather = dl.get_current_weather()
session = dl.get_current_session()
stats   = dl.get_session_stats()     # reused in Overview AND Sessions tabs


# ============================================================
# MIDDLEWARE STATUS BANNER
# Shown at the very top so data staleness is immediately visible.
# server_ok is True if at least one endpoint returned data.
# ============================================================
server_ok = bool(latest or weather or session)
if server_ok:
    st.markdown(
        '<div class="status-banner status-ok">'
        '<span class="live-dot"></span>&nbsp;Middleware online — live data</div>',
        unsafe_allow_html=True)
else:
    st.markdown(
        '<div class="status-banner status-down">'
        '🔴&nbsp;Middleware unreachable — data may be stale</div>',
        unsafe_allow_html=True)


# ============================================================
# SIDEBAR
# Contains: live session mini-widget, history slider, refresh,
# timestamp, and app credits.
# The session widget is computed here so its variables
# (ss_cls, ss_label, ss_sub) can also be referenced in Tab 1.
# ============================================================
s_active = session.get("active", False)
s_paused = session.get("paused", False)
work_sec  = session.get("work_seconds") or 0

if s_active and not s_paused:
    ss_cls, ss_label, ss_sub = "sp-working", "🟢 WORKING", _fmt_duration(work_sec)
elif s_active and s_paused:
    ss_cls, ss_label, ss_sub = "sp-paused",  "🟡 PAUSED",  "Session paused"
else:
    ss_cls, ss_label, ss_sub = "sp-idle",    "⚪ NO SESSION", "Tap badge to start"

with st.sidebar:
    st.markdown(
        "<span style='font-family:Syne,sans-serif;font-size:1rem;"
        "font-weight:800;color:#dde4ff;letter-spacing:.04em'>"
        "🎯 SmartFocusTracker</span>",
        unsafe_allow_html=True)
    st.markdown("---")

    # Live session status widget
    st.markdown(
        f'<div class="session-pill {ss_cls}">{ss_label}<br>'
        f'<span style="font-size:.72rem;font-weight:400;opacity:.6">'
        f'{ss_sub}</span></div>',
        unsafe_allow_html=True)

    st.markdown("---")

    # History range slider — value used by every history chart
    days = st.slider("📅 History range (days)", 1, 30, 7)

    st.markdown("---")

    if st.button("🔄 Refresh Now", use_container_width=True):
        # Bust all @st.cache_data caches then rerun immediately
        st.cache_data.clear()
        st.rerun()

    st.markdown("---")
    st.caption(
        f"⏱ Updated: {datetime.now().strftime('%H:%M:%S')}\n\n"
        "Auto-refresh every 10 s")
    st.markdown("---")
    st.caption("Cloud & Advanced Analytics — UNIL 2026\nAmir & Pablo")


# ============================================================
# PAGE HEADER
# ============================================================
st.markdown(
    "<h2 style='font-family:Syne,sans-serif;font-weight:800;"
    "letter-spacing:.02em;color:#dde4ff;margin-bottom:2px'>"
    "🎯 SmartFocusTracker Dashboard</h2>"
    "<p style='font-size:.82rem;color:#44446a;margin-bottom:18px'>"
    "Real-time indoor/outdoor monitoring · Productivity analytics · "
    "Powered by M5Stack + BigQuery</p>",
    unsafe_allow_html=True)


# ============================================================
# HERO KPI ROW — most critical values visible immediately,
# before any tab interaction.
# 5 columns: Indoor Temp / Humidity / CO₂ / Outdoor / Comfort
# ============================================================
hc1, hc2, hc3, hc4, hc5 = st.columns(5)

with hc1:
    t = latest.get("temperature")
    st.metric("🌡️ Indoor Temp",
              f"{round(t,1)}°C" if t is not None else "—")

with hc2:
    h = latest.get("humidity")
    low_hum = h is not None and h < 40
    st.metric("💧 Humidity",
              f"{round(h,1)}%" if h is not None else "—",
              delta="⚠ Below 40%" if low_hum else None,
              delta_color="inverse" if low_hum else "normal")

with hc3:
    co2 = latest.get("co2_ppm")
    aq  = latest.get("air_quality_label", "—")
    st.metric("🌬️ CO₂",
              f"{co2} ppm" if co2 else "—",
              delta=aq,
              delta_color="normal" if aq == "Good" else "inverse")

with hc4:
    cur     = weather.get("current", {})
    out_t   = cur.get("temperature")
    st.metric("🌍 Outdoor",
              f"{round(out_t,1)}°C" if out_t is not None else "—",
              delta=cur.get("condition", ""))

with hc5:
    ci_score, ci_label, _ = _comfort_index(
        latest.get("temperature"), latest.get("humidity"))
    st.metric("😌 Comfort",
              ci_label if ci_label != "N/A" else "—",
              delta=f"Score {ci_score}/100" if ci_score else None)

st.markdown("---")


# ============================================================
# TAB NAVIGATION
# Five tabs replace the old linear scroll structure.
# Each tab is fully self-contained — charts only render
# when their tab is active, saving render time.
# ============================================================
tab_ov, tab_in, tab_out, tab_sess, tab_alerts = st.tabs([
    "🌤️  Overview",
    "🏠  Indoor",
    "🌍  Outdoor",
    "⏱️  Sessions",
    "🔔  Alerts",
])


# ────────────────────────────────────────────────────────────
# TAB 1 — OVERVIEW
# Forecast cards + current session status
# ────────────────────────────────────────────────────────────
with tab_ov:

    # ── Weather forecast ──
    st.markdown('<div class="sec-head">📅 Weather Forecast</div>',
                unsafe_allow_html=True)

    forecast = weather.get("forecast", [])
    if forecast:
        # Build custom HTML forecast cards — Streamlit columns cannot
        # produce the tight, equally-sized card grid we need here.
        cards_html = '<div class="forecast-grid">'
        for day in forecast:
            cond    = day.get("condition", "")
            icon    = _weather_icon(cond)
            hi      = round(day.get("temp_max", 0))
            lo      = round(day.get("temp_min", 0))
            date_s  = day.get("date", "---")
            cards_html += (
                f'<div class="fc">'
                f'<div class="fc-day">{date_s}</div>'
                f'<span class="fc-icon">{icon}</span>'
                f'<div class="fc-cond">{cond}</div>'
                f'<div class="fc-hi">{hi}°</div>'
                f'<div class="fc-lo">/ {lo}°</div>'
                f'</div>'
            )
        cards_html += '</div>'
        st.markdown(cards_html, unsafe_allow_html=True)
    else:
        st.info("Weather forecast unavailable.")

    st.markdown("&nbsp;", unsafe_allow_html=True)

    # ── Current session snapshot ──
    st.markdown('<div class="sec-head">⏱ Current Session</div>',
                unsafe_allow_html=True)

    ov1, ov2, ov3 = st.columns(3)
    with ov1:
        st.metric("Status", ss_label)
    with ov2:
        st.metric("Work Time", _fmt_duration(work_sec))
    with ov3:
        avg = stats.get("avg_work_minutes")
        st.metric("30-Day Avg",
                  f"{round(avg,0):.0f} min" if avg else "—")


# ────────────────────────────────────────────────────────────
# TAB 2 — INDOOR
# Current readings snapshot + CO₂ gauge + history charts
# ────────────────────────────────────────────────────────────
with tab_in:

    # ── Current readings ──
    st.markdown('<div class="sec-head">📡 Current Indoor Readings</div>',
                unsafe_allow_html=True)

    i1, i2, i3, i4 = st.columns(4)
    with i1:
        t = latest.get("temperature")
        st.metric("Temperature", f"{round(t,1)}°C" if t is not None else "—")
    with i2:
        h = latest.get("humidity")
        st.metric("Humidity",
                  f"{round(h,1)}%" if h is not None else "—",
                  delta="Open humidifier" if h is not None and h < 40 else None,
                  delta_color="inverse")
    with i3:
        co2 = latest.get("co2_ppm")
        aq  = latest.get("air_quality_label", "—")
        st.metric("CO₂", f"{co2} ppm" if co2 else "—",
                  delta=aq,
                  delta_color="normal" if aq == "Good" else "inverse")
    with i4:
        ci_score, ci_label, _ = _comfort_index(
            latest.get("temperature"), latest.get("humidity"))
        st.metric("Comfort Index", ci_label,
                  delta=f"{ci_score}/100" if ci_score else None)

    # ── CO₂ gauge — Plotly Indicator ──
    # The gauge provides an instant, glanceable CO₂ reading with
    # color-coded arcs (Good/Moderate/Poor) that are clearer than
    # a number alone. Placed in the centre column to avoid stretching.
    co2_val = latest.get("co2_ppm")
    if co2_val:
        g_color = _co2_color(co2_val)
        fig_gauge = go.Figure(go.Indicator(
            mode="gauge+number",
            value=co2_val,
            number={
                "suffix": " ppm",
                "font": {"family": "JetBrains Mono", "size": 26, "color": g_color},
            },
            title={
                "text": "CO₂ Level",
                "font": {"family": "Syne", "size": 12, "color": "#888899"},
            },
            gauge={
                "axis": {
                    "range": [400, 2000],
                    "tickcolor": "#2a2a4a",
                    "tickfont": {"size": 9, "color": "#444466"},
                    "nticks": 9,
                },
                "bar":       {"color": g_color, "thickness": 0.22},
                "bgcolor":   "rgba(0,0,0,0)",
                "bordercolor": "#1c1c3a",
                "steps": [
                    {"range": [400, 800],  "color": "rgba(0,204,68,0.1)"},
                    {"range": [800, 1000], "color": "rgba(255,170,0,0.1)"},
                    {"range": [1000, 2000],"color": "rgba(255,68,68,0.1)"},
                ],
                "threshold": {
                    "line": {"color": "#ff4444", "width": 2},
                    "thickness": 0.72,
                    "value": 1000,
                },
            },
        ))
        fig_gauge.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            height=210,
            margin=dict(l=30, r=30, t=40, b=10),
        )
        _, gcol, _ = st.columns([1, 2, 1])
        with gcol:
            st.plotly_chart(fig_gauge, use_container_width=True)

    # ── Indoor history charts ──
    st.markdown('<div class="sec-head">📊 Indoor History</div>',
                unsafe_allow_html=True)

    df = dl.get_indoor_history(days=days)

    if not df.empty:

        # Temperature — area chart with gradient fill
        fig_t = go.Figure(go.Scatter(
            x=df["timestamp"], y=df["temperature"],
            mode="lines",
            name="Temperature",
            line=dict(color="#5bc8f5", width=2.5),
            fill="tozeroy",
            fillcolor="rgba(91,200,245,0.07)",
            hovertemplate="%{y:.1f}°C<extra></extra>",
        ))
        st.plotly_chart(
            _apply_theme(fig_t, "Indoor Temperature (°C)", "°C"),
            use_container_width=True)

        ic1, ic2 = st.columns(2)

        with ic1:
            # Humidity — area chart with 40% alert line
            fig_h = go.Figure(go.Scatter(
                x=df["timestamp"], y=df["humidity"],
                mode="lines",
                line=dict(color="#81d4fa", width=2),
                fill="tozeroy",
                fillcolor="rgba(129,212,250,0.06)",
                hovertemplate="%{y:.1f}%<extra></extra>",
            ))
            # Horizontal dashed line marks the 40% alert threshold
            # set by the project requirements (issue alert if < 40%)
            fig_h.add_hline(
                y=40, line_dash="dot", line_color="#ffaa00",
                annotation_text="Min 40%",
                annotation_font=dict(color="#ffaa00", size=10),
                annotation_position="top right")
            st.plotly_chart(
                _apply_theme(fig_h, "Humidity (%)", "%"),
                use_container_width=True)

        with ic2:
            if "co2_ppm" in df.columns:
                # CO₂ history with three background quality zones
                fig_c = go.Figure(go.Scatter(
                    x=df["timestamp"], y=df["co2_ppm"],
                    mode="lines",
                    line=dict(color="#a5d6a7", width=2),
                    fill="tozeroy",
                    fillcolor="rgba(165,214,167,0.06)",
                    hovertemplate="%{y} ppm<extra></extra>",
                ))
                # add_hrect() paints horizontal band backgrounds
                for y0, y1, col, lbl in [
                    (0,    800,  "rgba(0,204,68,0.07)",  "Good"),
                    (800,  1000, "rgba(255,170,0,0.07)", "Moderate"),
                    (1000, 2000, "rgba(255,68,68,0.07)", "Poor"),
                ]:
                    fig_c.add_hrect(
                        y0=y0, y1=y1, fillcolor=col, line_width=0,
                        annotation_text=lbl,
                        annotation_position="top left",
                        annotation_font=dict(size=9, color="#666688"))
                fig_c.add_hline(
                    y=1000, line_dash="dot", line_color="#ff4444",
                    annotation_text="Poor threshold",
                    annotation_font=dict(color="#ff4444", size=10))
                st.plotly_chart(
                    _apply_theme(fig_c, "CO₂ (ppm)", "ppm"),
                    use_container_width=True)
    else:
        st.info("No indoor history for the selected period.")


# ────────────────────────────────────────────────────────────
# TAB 3 — OUTDOOR
# Current conditions snapshot + dual-axis history chart
# ────────────────────────────────────────────────────────────
with tab_out:

    # ── Current outdoor snapshot ──
    st.markdown('<div class="sec-head">🌍 Current Outdoor Conditions</div>',
                unsafe_allow_html=True)

    cur = weather.get("current", {})
    o1, o2, o3, o4 = st.columns(4)

    with o1:
        ot = cur.get("temperature")
        st.metric("🌡️ Temperature",
                  f"{round(ot,1)}°C" if ot is not None else "—")
    with o2:
        oh = cur.get("humidity")
        st.metric("💧 Humidity", f"{oh}%" if oh is not None else "—")
    with o3:
        ow = cur.get("wind_speed")
        st.metric("💨 Wind", f"{ow} km/h" if ow is not None else "—")
    with o4:
        oc = cur.get("condition", "—")
        st.metric(f"{_weather_icon(oc)} Condition", oc)

    # ── Outdoor history — dual Y-axis combo chart ──
    # make_subplots with secondary_y=True creates a figure with two
    # independent Y axes sharing the same X (time) axis.
    # Temperature uses the left axis; humidity uses the right axis.
    # This avoids scale conflicts (°C vs %) while keeping both series
    # on one chart for easy visual correlation.
    st.markdown('<div class="sec-head">📈 Outdoor History</div>',
                unsafe_allow_html=True)

    df_out = dl.get_outdoor_history(days=days)

    if not df_out.empty:
        fig_dual = make_subplots(specs=[[{"secondary_y": True}]])

        # Left axis — temperature (warm amber tone)
        fig_dual.add_trace(
            go.Scatter(
                x=df_out["timestamp"], y=df_out["temperature"],
                name="Temp (°C)",
                line=dict(color="#ffcc80", width=2.5),
                fill="tozeroy",
                fillcolor="rgba(255,204,128,0.06)",
                hovertemplate="%{y:.1f}°C<extra>Outdoor Temp</extra>",
            ),
            secondary_y=False,
        )

        # Right axis — humidity (teal), dashed to visually distinguish
        if "humidity" in df_out.columns:
            fig_dual.add_trace(
                go.Scatter(
                    x=df_out["timestamp"], y=df_out["humidity"],
                    name="Humidity (%)",
                    line=dict(color="#80cbc4", width=2, dash="dot"),
                    hovertemplate="%{y:.1f}%<extra>Outdoor Humidity</extra>",
                ),
                secondary_y=True,
            )

        # Style each Y-axis to match its trace color
        fig_dual.update_yaxes(
            title_text="Temperature (°C)", secondary_y=False,
            gridcolor="#12122a",
            titlefont=dict(color="#ffcc80", size=10),
            tickfont=dict(size=10))
        fig_dual.update_yaxes(
            title_text="Humidity (%)", secondary_y=True,
            gridcolor="#0e0e20",
            titlefont=dict(color="#80cbc4", size=10),
            tickfont=dict(size=10))

        _apply_theme(fig_dual, "Outdoor Temperature & Humidity")
        st.plotly_chart(fig_dual, use_container_width=True)
    else:
        st.info("No outdoor history for the selected period.")


# ────────────────────────────────────────────────────────────
# TAB 4 — SESSIONS
# KPI metrics + color-coded bar chart + duration histogram
# stats is reused from the top-level fetch — no extra HTTP call
# ────────────────────────────────────────────────────────────
with tab_sess:

    st.markdown('<div class="sec-head">📊 Session Statistics (last 30 days)</div>',
                unsafe_allow_html=True)

    sk1, sk2, sk3, sk4 = st.columns(4)
    with sk1:
        st.metric("📌 Total Sessions", stats.get("total_sessions", "—"))
    with sk2:
        avg = stats.get("avg_work_minutes")
        st.metric("⌀ Avg Duration",
                  f"{round(avg,1)} min" if avg else "—")
    with sk3:
        total_m = stats.get("total_work_minutes")
        st.metric("⏳ Total Work",
                  f"{round(total_m/60,1)} h" if total_m else "—")
    with sk4:
        longest = stats.get("longest_session_minutes")
        st.metric("🏆 Longest",
                  f"{round(longest,0):.0f} min" if longest else "—")

    # ── Session history bar chart ──
    st.markdown('<div class="sec-head">📅 Session History</div>',
                unsafe_allow_html=True)

    df_s = dl.get_session_history(limit=20)

    if not df_s.empty and "total_work_minutes" in df_s.columns:
        df_s["label"] = df_s["start_time"].dt.strftime("%b %d %H:%M")

        # Color each bar relative to the average:
        #   ≥ 120% avg → green (productive session)
        #   ≥  60% avg → orange (below average)
        #   <  60% avg → red  (very short session)
        avg_min = stats.get("avg_work_minutes") or df_s["total_work_minutes"].mean()
        df_s["bar_color"] = df_s["total_work_minutes"].apply(
            lambda v: "#00cc44" if v >= avg_min * 1.2
                      else "#ffaa00" if v >= avg_min * 0.6
                      else "#ff6666")

        fig_bars = go.Figure(go.Bar(
            x=df_s["label"],
            y=df_s["total_work_minutes"],
            marker=dict(
                color=df_s["bar_color"],
                line=dict(color="rgba(0,0,0,0)", width=0),
                cornerradius=4,         # rounded bar tops
            ),
            hovertemplate="<b>%{x}</b><br>%{y:.0f} min<extra></extra>",
        ))

        if avg_min:
            # Dashed average line helps judge session quality at a glance
            fig_bars.add_hline(
                y=avg_min, line_dash="dash", line_color="#5bc8f5",
                annotation_text=f"Avg — {avg_min:.0f} min",
                annotation_font=dict(color="#5bc8f5", size=10),
                annotation_position="top right")

        _apply_theme(fig_bars, "Work Sessions — Duration (min)", "Minutes")
        fig_bars.update_layout(bargap=0.28)
        st.plotly_chart(fig_bars, use_container_width=True)

        # ── Duration distribution histogram ──
        # Shows how session lengths cluster — useful for spotting
        # whether the user tends to have short bursts or long focused blocks.
        st.markdown('<div class="sec-head">📐 Duration Distribution</div>',
                    unsafe_allow_html=True)

        fig_hist = go.Figure(go.Histogram(
            x=df_s["total_work_minutes"],
            nbinsx=10,
            marker=dict(
                color="#ce93d8",
                line=dict(color="rgba(0,0,0,0)", width=0),
            ),
            hovertemplate="Duration: %{x} min<br>Count: %{y}<extra></extra>",
        ))
        if avg_min:
            fig_hist.add_vline(
                x=avg_min, line_dash="dash", line_color="#5bc8f5",
                annotation_text="Avg",
                annotation_font=dict(color="#5bc8f5", size=10))
        _apply_theme(fig_hist, "Session Duration Distribution", "Number of sessions")
        st.plotly_chart(fig_hist, use_container_width=True)

    else:
        st.info("No completed sessions yet.")


# ────────────────────────────────────────────────────────────
# TAB 5 — ALERTS
# Custom HTML alert rows (type, timestamp, message)
# Color-coded by severity: warn / bad / info
# ────────────────────────────────────────────────────────────
with tab_alerts:

    st.markdown('<div class="sec-head">🔔 Recent Alerts</div>',
                unsafe_allow_html=True)

    df_a = dl.get_recent_alerts(limit=15)

    if not df_a.empty:
        # Map known alert types to (emoji, CSS-class) pairs
        # so each row gets a distinct visual treatment.
        ALERT_META = {
            "TTS_ALERT": ("🔊", "ar-warn", "#ffaa00"),
            "HUMIDITY":  ("💧", "ar-bad",  "#ff4444"),
            "AIR":       ("🌬️", "ar-bad",  "#ff4444"),
            "WEATHER":   ("⛈️", "ar-warn", "#ffaa00"),
        }
        for _, row in df_a.iterrows():
            a_type = row.get("alert_type", "ALERT")
            icon, css_cls, color = ALERT_META.get(a_type, ("⚠️", "ar-warn", "#ffaa00"))
            ts  = (row["timestamp"].strftime("%Y-%m-%d %H:%M")
                   if pd.notna(row.get("timestamp")) else "—")
            msg = row.get("message", "")
            st.markdown(
                f'<div class="alert-row {css_cls}">'
                f'<div class="ar-time">{ts}</div>'
                f'<div class="ar-type" style="color:{color}">{icon} {a_type}</div>'
                f'<div class="ar-msg">{msg}</div>'
                f'</div>',
                unsafe_allow_html=True)
    else:
        st.success("✅ No recent alerts — all conditions nominal.")