# middleware/weather_service.py
# Fetches current weather and forecast from OpenWeatherMap API.
# Results are cached for 10 minutes to avoid exceeding API quota.
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
# CACHE — Avoids hitting API quota on every device request
# ============================================================

_cache = {
    "data":       None,   # Last successful API response
    "expires_at": 0,      # Unix timestamp when cache expires
}
CACHE_TTL = 600           # Cache duration in seconds (10 minutes)

# ============================================================
# ICON MAPPING — OpenWeatherMap icon codes to descriptive labels
# ============================================================

# Maps OWM icon codes to simple text labels used by M5Stack display.
# Full icon list: openweathermap.org/weather-conditions
ICON_LABELS = {
    "01d": "Clear Sky",
    "01n": "Clear Sky",
    "02d": "Few Clouds",
    "02n": "Few Clouds",
    "03d": "Scattered Clouds",
    "03n": "Scattered Clouds",
    "04d": "Broken Clouds",
    "04n": "Broken Clouds",
    "09d": "Shower Rain",
    "09n": "Shower Rain",
    "10d": "Rain",
    "10n": "Rain",
    "11d": "Thunderstorm",
    "11n": "Thunderstorm",
    "13d": "Snow",
    "13n": "Snow",
    "50d": "Mist",
    "50n": "Mist",
}

# ============================================================
# MAIN FUNCTION
# ============================================================

def get_weather():
    # Returns current weather and 5-day forecast.
    # Serves from cache if data is still fresh.
    # Raises an exception if API call fails — caller handles error.
    if _is_cache_valid():
        return _cache["data"]

    current  = _fetch_current()
    forecast = _fetch_forecast()

    result = {
        "current":  current,
        "forecast": forecast,
    }

    # Update cache
    _cache["data"]       = result
    _cache["expires_at"] = time.time() + CACHE_TTL

    return result

# ============================================================
# PRIVATE HELPERS
# ============================================================

def _is_cache_valid():
    # Returns True if cached data exists and has not expired.
    return _cache["data"] is not None and time.time() < _cache["expires_at"]

def _fetch_current():
    # Calls OWM /weather endpoint and returns normalized current conditions.
    url    = "{}/weather".format(BASE_URL)
    params = {"q": CITY, "appid": API_KEY, "units": UNITS}

    response = requests.get(url, params=params, timeout=5)
    response.raise_for_status()
    raw = response.json()

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

def _fetch_forecast():
    # Calls OWM /forecast endpoint and returns one entry per day
    # for the next 5 days (noon reading per day).
    # Forecast is not stored in BigQuery — display only.
    url    = "{}/forecast".format(BASE_URL)
    params = {"q": CITY, "appid": API_KEY, "units": UNITS, "cnt": 40}

    response = requests.get(url, params=params, timeout=5)
    response.raise_for_status()
    raw = response.json()

    # OWM returns readings every 3 hours — we pick the 12:00 entry per day
    daily = {}
    for entry in raw["list"]:
        date = entry["dt_txt"].split(" ")[0]   # Extract "YYYY-MM-DD"
        hour = entry["dt_txt"].split(" ")[1]   # Extract "HH:MM:SS"
        if hour == "12:00:00" and date not in daily:
            icon_code = entry["weather"][0]["icon"]
            daily[date] = {
                "date":      date,
                "temp_min":  entry["main"]["temp_min"],
                "temp_max":  entry["main"]["temp_max"],
                "condition": entry["weather"][0]["description"].capitalize(),
                "icon_code": icon_code,
                "icon_label": ICON_LABELS.get(icon_code, "Unknown"),
            }

    # Return sorted list — up to 5 days
    return [daily[d] for d in sorted(daily.keys())[:5]]