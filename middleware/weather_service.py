# middleware/weather_service.py
# Fetches current weather and forecast from OpenWeatherMap API.
# Supports dynamic city selection — any city name valid on OWM can be queried.
# Each city has its own cache slot to avoid re-fetching unchanged data.
# Assigned to: Pablo

import os
import time
import requests

# ============================================================
# CONFIGURATION
# ============================================================

API_KEY  = os.environ["OPENWEATHER_API_KEY"]
CITY     = os.environ["OPENWEATHER_CITY"]
UNITS    = os.environ["OPENWEATHER_UNITS"]
BASE_URL = "https://api.openweathermap.org/data/2.5"

# ============================================================
# PER-CITY CACHE
#
# Structure: _cache["lausanne"] = {"data": {...}, "expires_at": 1234567.89}
# Each city has its own independent TTL slot so multiple callers
# (Streamlit city selector, LLM enrichment, device default) don't
# evict each other.
# ============================================================
_cache: dict = {}
CACHE_TTL = 600  # seconds (10 min per city)

# ============================================================
# ICON MAPPING — OpenWeatherMap icon codes → descriptive labels
# ============================================================
ICON_LABELS = {
    "01d": "Clear Sky",    "01n": "Clear Sky",
    "02d": "Few Clouds",   "02n": "Few Clouds",
    "03d": "Scattered Clouds", "03n": "Scattered Clouds",
    "04d": "Broken Clouds",    "04n": "Broken Clouds",
    "09d": "Shower Rain",  "09n": "Shower Rain",
    "10d": "Rain",         "10n": "Rain",
    "11d": "Thunderstorm", "11n": "Thunderstorm",
    "13d": "Snow",         "13n": "Snow",
    "50d": "Mist",         "50n": "Mist",
}

# ============================================================
# PUBLIC API
# ============================================================

def get_weather(city: str = None) -> dict:
    """
    Returns current weather + 5-day forecast for the requested city.

    city defaults to OPENWEATHER_CITY env var when None.
    Each city has its own cache slot (TTL = CACHE_TTL).
    Raises requests.HTTPError for unknown cities.
    """
    resolved_city = (city or CITY).strip()
    cache_key     = resolved_city.lower()

    slot = _cache.get(cache_key)
    if slot and time.time() < slot["expires_at"]:
        return slot["data"]

    current  = _fetch_current(resolved_city)
    forecast = _fetch_forecast(resolved_city)
    result   = {"current": current, "forecast": forecast}

    _cache[cache_key] = {"data": result, "expires_at": time.time() + CACHE_TTL}
    return result

# ============================================================
# PRIVATE HELPERS
# ============================================================

def _fetch_current(city: str) -> dict:
    url      = "{}/weather".format(BASE_URL)
    params   = {"q": city, "appid": API_KEY, "units": UNITS}
    response = requests.get(url, params=params, timeout=5)
    response.raise_for_status()
    raw       = response.json()
    icon_code = raw["weather"][0]["icon"]
    return {
        "city":        raw["name"],
        "temperature": raw["main"]["temp"],
        "humidity":    raw["main"]["humidity"],
        "condition":   raw["weather"][0]["description"].capitalize(),
        "wind_speed":  raw["wind"]["speed"],
        "icon_code":   icon_code,
        "icon_label":  ICON_LABELS.get(icon_code, "Unknown"),
    }

def _fetch_forecast(city: str) -> list:
    url      = "{}/forecast".format(BASE_URL)
    params   = {"q": city, "appid": API_KEY, "units": UNITS, "cnt": 40}
    response = requests.get(url, params=params, timeout=5)
    response.raise_for_status()
    raw = response.json()

    daily = {}
    for entry in raw["list"]:
        date = entry["dt_txt"].split(" ")[0]
        hour = entry["dt_txt"].split(" ")[1]
        if hour == "12:00:00" and date not in daily:
            icon_code = entry["weather"][0]["icon"]
            daily[date] = {
                "date":       date,
                "temp_min":   entry["main"]["temp_min"],
                "temp_max":   entry["main"]["temp_max"],
                "condition":  entry["weather"][0]["description"].capitalize(),
                "icon_code":  icon_code,
                "icon_label": ICON_LABELS.get(icon_code, "Unknown"),
            }
    return [daily[d] for d in sorted(daily.keys())[:5]]
