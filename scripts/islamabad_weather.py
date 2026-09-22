#!/usr/bin/env python3
"""Print current weather and a 7-day forecast for Islamabad, Pakistan.

The script uses Open-Meteo's free forecast API. It needs no API key and no
third-party Python packages.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


LOCATION = "Islamabad, Pakistan"
LATITUDE = 33.6844
LONGITUDE = 73.0479
TIMEZONE = "Asia/Karachi"
API_URL = "https://api.open-meteo.com/v1/forecast"

WEATHER_CODES = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Depositing rime fog",
    51: "Light drizzle",
    53: "Moderate drizzle",
    55: "Dense drizzle",
    56: "Light freezing drizzle",
    57: "Dense freezing drizzle",
    61: "Slight rain",
    63: "Moderate rain",
    65: "Heavy rain",
    66: "Light freezing rain",
    67: "Heavy freezing rain",
    71: "Slight snowfall",
    73: "Moderate snowfall",
    75: "Heavy snowfall",
    77: "Snow grains",
    80: "Slight rain showers",
    81: "Moderate rain showers",
    82: "Violent rain showers",
    85: "Slight snow showers",
    86: "Heavy snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm with slight hail",
    99: "Thunderstorm with heavy hail",
}


def weather_description(code: int | None) -> str:
    """Convert a WMO weather code into a readable description."""
    return WEATHER_CODES.get(code, f"Unknown conditions (code {code})")


def compass_direction(degrees: float | None) -> str:
    """Convert wind direction in degrees to a 16-point compass direction."""
    if degrees is None:
        return "N/A"
    directions = (
        "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
        "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
    )
    return directions[round(degrees / 22.5) % 16]


def get_weather() -> dict:
    """Fetch Islamabad weather data from Open-Meteo."""
    params = {
        "latitude": LATITUDE,
        "longitude": LONGITUDE,
        "timezone": TIMEZONE,
        "forecast_days": 7,
        "temperature_unit": "celsius",
        "wind_speed_unit": "kmh",
        "precipitation_unit": "mm",
        "current": ",".join(
            [
                "temperature_2m",
                "apparent_temperature",
                "relative_humidity_2m",
                "precipitation",
                "rain",
                "weather_code",
                "cloud_cover",
                "surface_pressure",
                "wind_speed_10m",
                "wind_direction_10m",
                "wind_gusts_10m",
            ]
        ),
        "hourly": ",".join(
            [
                "temperature_2m",
                "apparent_temperature",
                "relative_humidity_2m",
                "precipitation_probability",
                "precipitation",
                "weather_code",
                "cloud_cover",
                "wind_speed_10m",
                "wind_gusts_10m",
            ]
        ),
        "daily": ",".join(
            [
                "weather_code",
                "temperature_2m_max",
                "temperature_2m_min",
                "apparent_temperature_max",
                "apparent_temperature_min",
                "sunrise",
                "sunset",
                "daylight_duration",
                "uv_index_max",
                "precipitation_sum",
                "precipitation_probability_max",
                "wind_speed_10m_max",
                "wind_gusts_10m_max",
            ]
        ),
    }

    request = Request(
        f"{API_URL}?{urlencode(params)}",
        headers={"User-Agent": "IslamabadWeather/1.0"},
    )
    try:
        with urlopen(request, timeout=20) as response:
            return json.load(response)
    except HTTPError as exc:
        raise RuntimeError(f"Weather service returned HTTP {exc.code}.") from exc
    except URLError as exc:
        raise RuntimeError(f"Could not reach the weather service: {exc.reason}") from exc
    except (json.JSONDecodeError, TimeoutError) as exc:
        raise RuntimeError(f"Could not read the weather response: {exc}") from exc


def print_current(data: dict, now: datetime) -> None:
    current = data["current"]
    print("=" * 78)
    print(f"WEATHER FOR {LOCATION.upper()}")
    print(f"Local time: {now:%A, %d %B %Y — %I:%M %p} ({TIMEZONE})")
    print(f"Forecast updated for: {current['time'].replace('T', ' ')}")
    print("=" * 78)
    print("\nCURRENT CONDITIONS")
    print(f"  Conditions:       {weather_description(current['weather_code'])}")
    print(f"  Temperature:      {current['temperature_2m']:.1f} °C")
    print(f"  Feels like:       {current['apparent_temperature']:.1f} °C")
    print(f"  Humidity:         {current['relative_humidity_2m']}%")
    print(f"  Cloud cover:      {current['cloud_cover']}%")
    print(f"  Precipitation:    {current['precipitation']:.1f} mm")
    print(f"  Surface pressure: {current['surface_pressure']:.0f} hPa")
    print(
        f"  Wind:             {current['wind_speed_10m']:.1f} km/h "
        f"{compass_direction(current['wind_direction_10m'])} "
        f"(gusts {current['wind_gusts_10m']:.1f} km/h)"
    )


def print_today_hourly(data: dict, today_iso: str) -> None:
    hourly = data["hourly"]
    rows = []
    for index, timestamp in enumerate(hourly["time"]):
        if timestamp.startswith(today_iso):
            rows.append(
                {
                    "time": datetime.fromisoformat(timestamp),
                    "temp": hourly["temperature_2m"][index],
                    "feels": hourly["apparent_temperature"][index],
                    "rain_chance": hourly["precipitation_probability"][index],
                    "rain": hourly["precipitation"][index],
                    "humidity": hourly["relative_humidity_2m"][index],
                    "wind": hourly["wind_speed_10m"][index],
                    "condition": weather_description(hourly["weather_code"][index]),
                }
            )

    print("\nTODAY'S HOURLY FORECAST (00:00–23:00)")
    print("-" * 112)
    print(
        f"{'Time':<9}{'Temp':>7}{'Feels':>8}{'Rain %':>9}{'Rain mm':>10}"
        f"{'Humidity':>11}{'Wind':>12}  Conditions"
    )
    print("-" * 112)
    for row in rows:
        print(
            f"{row['time']:%I:%M %p}"
            f"{row['temp']:>6.1f}°"
            f"{row['feels']:>7.1f}°"
            f"{row['rain_chance']:>8}%"
            f"{row['rain']:>9.1f}"
            f"{row['humidity']:>10}%"
            f"{row['wind']:>9.1f} km/h  "
            f"{row['condition']}"
        )


def print_week(data: dict, today_iso: str) -> None:
    daily = data["daily"]
    print("\n7-DAY FORECAST")
    print("-" * 128)
    print(
        f"{'Day':<18}{'Conditions':<28}{'Low/High':>12}{'Feels':>13}"
        f"{'Rain':>10}{'Rainfall':>11}{'UV':>7}{'Wind max':>13}  Sunrise–Sunset"
    )
    print("-" * 128)

    for index, date_string in enumerate(daily["time"]):
        date = datetime.fromisoformat(date_string)
        day_label = "Today" if date_string == today_iso else date.strftime("%A")
        day_label = f"{day_label}, {date:%d %b}"
        sunrise = datetime.fromisoformat(daily["sunrise"][index]).strftime("%I:%M %p")
        sunset = datetime.fromisoformat(daily["sunset"][index]).strftime("%I:%M %p")
        low_high = (
            f"{daily['temperature_2m_min'][index]:.0f}°/"
            f"{daily['temperature_2m_max'][index]:.0f}°C"
        )
        feels = (
            f"{daily['apparent_temperature_min'][index]:.0f}°/"
            f"{daily['apparent_temperature_max'][index]:.0f}°C"
        )
        print(
            f"{day_label:<18}"
            f"{weather_description(daily['weather_code'][index]):<28}"
            f"{low_high:>12}"
            f"{feels:>13}"
            f"{daily['precipitation_probability_max'][index]:>9}%"
            f"{daily['precipitation_sum'][index]:>8.1f} mm"
            f"{daily['uv_index_max'][index]:>7.1f}"
            f"{daily['wind_speed_10m_max'][index]:>9.1f} km/h  "
            f"{sunrise}–{sunset}"
        )


def main() -> int:
    now = datetime.now(ZoneInfo(TIMEZONE))
    try:
        data = get_weather()
        print_current(data, now)
        print_today_hourly(data, now.date().isoformat())
        print_week(data, now.date().isoformat())
        print("\nData source: Open-Meteo (https://open-meteo.com/)\n")
        return 0
    except (RuntimeError, KeyError, TypeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
