"""Weather — Open-Meteo, no API key required.

Geocodes the city, then returns current conditions + a 3-day forecast.
"""

from __future__ import annotations

from typing import Any

import requests

from tools.registry import Tool, ToolRegistry

WEATHER_CODES = {
    0: "clear sky", 1: "mainly clear", 2: "partly cloudy", 3: "overcast",
    45: "fog", 48: "depositing rime fog",
    51: "light drizzle", 53: "drizzle", 55: "dense drizzle",
    56: "light freezing drizzle", 57: "dense freezing drizzle",
    61: "slight rain", 63: "rain", 65: "heavy rain",
    66: "light freezing rain", 67: "heavy freezing rain",
    71: "slight snow", 73: "snow", 75: "heavy snow", 77: "snow grains",
    80: "slight rain showers", 81: "rain showers", 82: "violent rain showers",
    85: "slight snow showers", 86: "heavy snow showers",
    95: "thunderstorm", 96: "thunderstorm with slight hail",
    99: "thunderstorm with heavy hail",
}


def get_weather(city: str = "Lahore") -> str:
    """Current weather + 3-day forecast for a city (Open-Meteo, free)."""
    try:
        geo = requests.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": city, "count": 1},
            timeout=15,
        )
        geo.raise_for_status()
        results = geo.json().get("results") or []
        if not results:
            return f"Could not find a place called '{city}'."
        place = results[0]
        lat, lon = place["latitude"], place["longitude"]
        name = place.get("name", city)
        country = place.get("country", "")
        fc = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": lat,
                "longitude": lon,
                "current": "temperature_2m,relative_humidity_2m,wind_speed_10m,weather_code",
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
                "timezone": "auto",
                "forecast_days": 3,
            },
            timeout=15,
        )
        fc.raise_for_status()
        data = fc.json()
        cur = data.get("current") or {}
        daily = data.get("daily") or {}
        desc = WEATHER_CODES.get(cur.get("weather_code"), "unknown conditions")
        lines = [
            f"Weather in {name}, {country}: {desc}, "
            f"{cur.get('temperature_2m')}°C, humidity "
            f"{cur.get('relative_humidity_2m')}%, wind "
            f"{cur.get('wind_speed_10m')} km/h."
        ]
        days = daily.get("time") or []
        for i, day in enumerate(days):
            lines.append(
                f"  {day}: {daily['temperature_2m_min'][i]}–"
                f"{daily['temperature_2m_max'][i]}°C, "
                f"rain chance {daily['precipitation_probability_max'][i]}%."
            )
        return "\n".join(lines)
    except Exception as exc:  # noqa: BLE001
        return f"Weather lookup failed: {exc}"


def register(registry: ToolRegistry, context: dict[str, Any]) -> None:
    registry.register(
        Tool(
            name="get_weather",
            description="Current weather and a 3-day forecast for a city.",
            parameters={
                "type": "object",
                "properties": {
                    "city": {"type": "string", "description": "city name"},
                },
                "required": [],
            },
            func=lambda city=None: get_weather(city or context["config"].city),
        )
    )
