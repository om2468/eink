"""Fetches the forecast and headlines."""

import json
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date

from . import config

USER_AGENT = "eink-dashboard/1.0"
TIMEOUT_SECONDS = 20


@dataclass
class Day:
    date: date
    code: int
    high: float
    low: float
    rain_chance: int


@dataclass
class Weather:
    temperature: float
    feels_like: float
    code: int
    wind_mph: float
    is_day: bool
    days: list[Day]


def _get(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        return response.read()


def fetch_weather() -> Weather:
    query = urllib.parse.urlencode(
        {
            "latitude": config.LATITUDE,
            "longitude": config.LONGITUDE,
            "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m,is_day",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
            "wind_speed_unit": "mph",
            "timezone": config.TIMEZONE,
            "forecast_days": 4,
        }
    )
    body = json.loads(_get(f"https://api.open-meteo.com/v1/forecast?{query}"))
    current = body["current"]
    daily = body["daily"]
    days = [
        Day(
            date=date.fromisoformat(daily["time"][i]),
            code=daily["weather_code"][i],
            high=daily["temperature_2m_max"][i],
            low=daily["temperature_2m_min"][i],
            rain_chance=daily["precipitation_probability_max"][i] or 0,
        )
        for i in range(len(daily["time"]))
    ]
    return Weather(
        temperature=current["temperature_2m"],
        feels_like=current["apparent_temperature"],
        code=current["weather_code"],
        wind_mph=current["wind_speed_10m"],
        is_day=bool(current["is_day"]),
        days=days,
    )


def parse_headlines(feed: bytes) -> list[str]:
    titles = []
    for item in ET.fromstring(feed).iter("item"):
        title = (item.findtext("title") or "").strip()
        if title and title not in titles:
            titles.append(title)
    return titles


def fetch_headlines() -> list[str]:
    headlines = parse_headlines(_get(config.NEWS_FEED_URL))
    if not headlines:
        raise ValueError(f"no headlines in {config.NEWS_FEED_URL}")
    return headlines
