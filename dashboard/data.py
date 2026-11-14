"""Fetches the forecast and share prices."""

import json
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timezone

from . import config

# Yahoo refuses requests without a browser-like user agent.
USER_AGENT = "Mozilla/5.0"
TIMEOUT_SECONDS = 20
ATTEMPTS = 3
RETRY_DELAY_SECONDS = 15
FORECAST_DAYS = 6  # Today plus the five days shown.


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
    sunset: datetime
    days: list[Day]


@dataclass
class Share:
    name: str
    ticker: str
    currency: str
    price: float
    previous_close: float
    month_high: float
    month_low: float
    market_time: datetime

    @property
    def change_percent(self) -> float:
        return (self.price - self.previous_close) / self.previous_close * 100


def _get_json(url: str) -> dict:
    # The data sources occasionally fail for a moment, so try a few times.
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(ATTEMPTS):
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
                return json.loads(response.read())
        except (OSError, ValueError):
            if attempt == ATTEMPTS - 1:
                raise
            time.sleep(RETRY_DELAY_SECONDS)


def fetch_weather() -> Weather:
    query = urllib.parse.urlencode(
        {
            "latitude": config.LATITUDE,
            "longitude": config.LONGITUDE,
            "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m,is_day",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,sunset",
            "wind_speed_unit": "mph",
            "timezone": config.TIMEZONE,
            "forecast_days": FORECAST_DAYS,
        }
    )
    body = _get_json(f"https://api.open-meteo.com/v1/forecast?{query}")
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
        sunset=datetime.fromisoformat(daily["sunset"][0]),
        days=days,
    )


def parse_share(name: str, body: dict) -> Share:
    result = body["chart"]["result"][0]
    meta = result["meta"]
    quote = result["indicators"]["quote"][0]
    # Days can be null, such as a day with no trades yet.
    closes = [value for value in quote["close"] if value is not None]
    return Share(
        name=name,
        ticker=meta["symbol"],
        currency=meta["currency"],
        price=meta["regularMarketPrice"],
        # With a one-month range, meta's previous close is from a month ago.
        previous_close=closes[-2],
        month_high=max(value for value in quote["high"] if value is not None),
        month_low=min(value for value in quote["low"] if value is not None),
        market_time=datetime.fromtimestamp(meta["regularMarketTime"], timezone.utc),
    )


def fetch_shares() -> list[Share]:
    shares = []
    for name, ticker in config.SHARES:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(ticker)}?range=1mo&interval=1d"
        shares.append(parse_share(name, _get_json(url)))
    return shares
