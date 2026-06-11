"""
Grid-area temperature data via Open-Meteo (free, no API key).

API docs: https://open-meteo.com/en/docs
No registration required. Rate limit: 10,000 calls/day per IP.

Usage:
    from iso_data import weather
    df = weather.get_current_temperatures()  # latest temp for all grid hubs
    df = weather.get_hourly_temperatures(hours=24)  # last N hours
"""
from __future__ import annotations

from datetime import datetime, timezone

from . import _http

_API = "https://api.open-meteo.com/v1/forecast"

# Representative grid-hub cities: (iso, city_name, lat, lon)
_GRID_HUBS: list[tuple[str, str, float, float]] = [
    ("CAISO",  "Los Angeles, CA",   34.05,  -118.24),
    ("ERCOT",  "Houston, TX",       29.76,   -95.37),
    ("PJM",    "Philadelphia, PA",  39.95,   -75.17),
    ("MISO",   "Chicago, IL",       41.88,   -87.63),
    ("NYISO",  "New York, NY",      40.71,   -74.01),
    ("ISONE",  "Boston, MA",        42.36,   -71.06),
    ("SPP",    "Wichita, KS",       37.69,   -97.34),
    ("BPAT",   "Portland, OR",      45.52,  -122.68),
    ("TVA",    "Nashville, TN",     36.17,   -86.78),
    ("SOCO",   "Atlanta, GA",       33.75,   -84.39),
]


def get_current_temperatures() -> list[dict]:
    """
    Current temperature (°F) + humidity at each grid-hub city.
    Returns list of {iso, city, ts, temp_f, humidity_pct, wind_mph}.
    """
    results = []
    for iso, city, lat, lon in _GRID_HUBS:
        try:
            r = _http.get(_API, params={
                "latitude":      lat,
                "longitude":     lon,
                "current":       "temperature_2m,relative_humidity_2m,wind_speed_10m",
                "temperature_unit": "fahrenheit",
                "wind_speed_unit":  "mph",
                "timezone":      "UTC",
            })
            data = r.json()
            curr = data.get("current", {})
            ts_str = curr.get("time")
            if not ts_str:
                continue
            ts = datetime.strptime(ts_str, "%Y-%m-%dT%H:%M").replace(tzinfo=timezone.utc)
            results.append({
                "iso":          iso,
                "city":         city,
                "lat":          lat,
                "lon":          lon,
                "ts":           ts,
                "temp_f":       curr.get("temperature_2m"),
                "humidity_pct": curr.get("relative_humidity_2m"),
                "wind_mph":     curr.get("wind_speed_10m"),
            })
        except Exception:
            continue
    return results


def get_hourly_temperatures(hours: int = 48) -> list[dict]:
    """
    Past N hours of temperature history at each grid-hub city.
    Returns list of {iso, city, ts, temp_f}.
    """
    results = []
    for iso, city, lat, lon in _GRID_HUBS:
        try:
            r = _http.get(_API, params={
                "latitude":         lat,
                "longitude":        lon,
                "hourly":           "temperature_2m",
                "temperature_unit": "fahrenheit",
                "timezone":         "UTC",
                "past_hours":       min(hours, 168),  # open-meteo max past_hours
                "forecast_hours":   0,
            })
            data = r.json()
            hourly = data.get("hourly", {})
            times  = hourly.get("time", [])
            temps  = hourly.get("temperature_2m", [])
            for ts_str, temp in zip(times, temps):
                try:
                    ts = datetime.strptime(ts_str, "%Y-%m-%dT%H:%M").replace(tzinfo=timezone.utc)
                    results.append({
                        "iso": iso, "city": city, "lat": lat, "lon": lon,
                        "ts": ts, "temp_f": temp,
                    })
                except Exception:
                    continue
        except Exception:
            continue
    return results
