"""Draws the dashboard page in pure black, white and red."""

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageFont

from . import config
from .data import Share, Weather

BLACK = (0, 0, 0)
WHITE = (255, 255, 255)
RED = (255, 0, 0)

FONT_DIR = Path(__file__).parent / "fonts"
REGULAR = "LiberationSans-Regular.ttf"
BOLD = "LiberationSans-Bold.ttf"

MARGIN = 10
SHARES_TOP = 142
SHARE_ROW_HEIGHT = 45


def _font(size: int, name: str = REGULAR) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT_DIR / name, size)


def describe(code: int) -> str:
    """Short English label for a WMO weather code."""
    if code == 0:
        return "Clear"
    if code in (1, 2):
        return "Partly cloudy"
    if code == 3:
        return "Overcast"
    if code in (45, 48):
        return "Fog"
    if 51 <= code <= 57:
        return "Drizzle"
    if code in (66, 67):
        return "Freezing rain"
    if 61 <= code <= 65:
        return "Rain"
    if 71 <= code <= 77 or code in (85, 86):
        return "Snow"
    if 80 <= code <= 82:
        return "Showers"
    if code >= 95:
        return "Thunderstorm"
    return "Unknown"


def _sun(draw: ImageDraw.ImageDraw, cx: int, cy: int, r: int) -> None:
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=RED)
    long = r + r // 2 + 2
    short = r + 3
    diagonal_long = long * 7 // 10
    diagonal_short = short * 7 // 10
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        draw.line((cx + dx * short, cy + dy * short, cx + dx * long, cy + dy * long), fill=RED, width=2)
    for dx, dy in ((1, 1), (1, -1), (-1, 1), (-1, -1)):
        draw.line(
            (cx + dx * diagonal_short, cy + dy * diagonal_short, cx + dx * diagonal_long, cy + dy * diagonal_long),
            fill=RED,
            width=2,
        )


def _moon(draw: ImageDraw.ImageDraw, cx: int, cy: int, r: int) -> None:
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=BLACK)
    offset = r * 2 // 3
    draw.ellipse((cx - r + offset, cy - r - 2, cx + r + offset, cy + r - 2), fill=WHITE)


def _cloud(draw: ImageDraw.ImageDraw, x: int, y: int, w: int, fill=WHITE) -> None:
    """Cloud whose top-left is near (x, y)."""
    h = w // 2
    outline = BLACK
    shapes = [
        (x, y + h * 2 // 5, x + w * 2 // 5, y + h),
        (x + w // 5, y, x + w * 7 // 10, y + h * 4 // 5),
        (x + w // 2, y + h // 4, x + w, y + h),
    ]
    for box in shapes:
        draw.ellipse(box, fill=fill, outline=outline, width=2)
    draw.rectangle((x + w // 5, y + h // 2, x + w * 4 // 5, y + h), fill=fill)
    draw.line((x + w // 5, y + h, x + w * 4 // 5, y + h), fill=outline, width=2)


def _icon(draw: ImageDraw.ImageDraw, x: int, y: int, size: int, code: int, is_day: bool = True) -> None:
    """Weather icon in a size x size box at (x, y)."""
    cloud_w = size * 7 // 8
    cloud_x = x + (size - cloud_w) // 2
    cloud_y = y + size // 5
    below = cloud_y + cloud_w // 2 + 3

    def body(cx: int, cy: int, r: int) -> None:
        (_sun if is_day else _moon)(draw, cx, cy, r)

    label = describe(code)
    if label == "Clear":
        body(x + size // 2, y + size // 2, size // 4)
    elif label == "Partly cloudy":
        body(x + size * 2 // 3, y + size // 3, size // 6)
        _cloud(draw, x, y + size // 3, size * 3 // 4)
    elif label in ("Overcast", "Unknown"):
        _cloud(draw, cloud_x, cloud_y, cloud_w)
    elif label == "Fog":
        _cloud(draw, cloud_x, y, cloud_w)
        for i in range(2):
            line_y = y + cloud_w // 2 + 5 + i * 6
            draw.line((cloud_x, line_y, cloud_x + cloud_w, line_y), fill=BLACK, width=2)
    elif label == "Snow":
        _cloud(draw, cloud_x, y, cloud_w)
        for i in range(3):
            cx = cloud_x + cloud_w * (i + 1) // 4
            draw.ellipse((cx - 2, y + cloud_w // 2 + 5, cx + 2, y + cloud_w // 2 + 9), fill=BLACK)
    elif label == "Thunderstorm":
        _cloud(draw, cloud_x, y, cloud_w)
        cx = x + size // 2
        top = y + cloud_w // 2 + 2
        draw.line((cx + 3, top, cx - 3, top + size // 6, cx + 3, top + size // 6, cx - 3, top + size // 3), fill=RED, width=2)
    else:  # Drizzle, rain, showers, freezing rain
        _cloud(draw, cloud_x, y, cloud_w)
        below = y + cloud_w // 2 + 3
        for i in range(3):
            cx = cloud_x + cloud_w * (i + 1) // 4
            draw.line((cx + 2, below, cx - 2, below + size // 6), fill=RED, width=2)


def _weather(draw: ImageDraw.ImageDraw, weather: Weather) -> None:
    top = config.HEADER_HEIGHT + 5
    _icon(draw, MARGIN, top + 2, 56, weather.code, weather.is_day)
    temperature = f"{round(weather.temperature)}\u00b0"
    big = _font(46, BOLD)
    draw.text((MARGIN + 62, top), temperature, font=big, fill=BLACK)

    x = MARGIN + 62 + int(big.getlength(temperature)) + 12
    today = weather.days[0]
    small = _font(14)
    draw.text((x, top), describe(weather.code), font=_font(16, BOLD), fill=BLACK)
    draw.text((x, top + 18), f"Feels {round(weather.feels_like)}\u00b0, wind {round(weather.wind_mph)} mph", font=small, fill=BLACK)
    draw.text((x, top + 34), f"High {round(today.high)}\u00b0  Low {round(today.low)}\u00b0  Rain {today.rain_chance}%", font=small, fill=BLACK)
    draw.text((x, top + 50), f"Sunset {weather.sunset:%H:%M}", font=small, fill=BLACK)

    # Next five days.
    strip_top = top + 72
    forecast = weather.days[1:]
    column = (config.WIDTH - 2 * MARGIN) // len(forecast)
    for i, day in enumerate(forecast):
        cx = MARGIN + column * i
        _icon(draw, cx, strip_top + 1, 28, day.code)
        draw.text((cx + 30, strip_top), f"{day.date:%a}", font=_font(13, BOLD), fill=BLACK)
        draw.text((cx + 30, strip_top + 15), f"{round(day.high)}/{round(day.low)}\u00b0", font=_font(13), fill=BLACK)


def _shares(draw: ImageDraw.ImageDraw, shares: list[Share], now: datetime) -> None:
    draw.line((MARGIN, SHARES_TOP, config.WIDTH - MARGIN, SHARES_TOP), fill=RED, width=2)
    draw.text((MARGIN, SHARES_TOP + 4), "SHARES", font=_font(13, BOLD), fill=RED)

    # Two times, so stale data is visible: when the market last traded, and when
    # this page was drawn.
    uk = ZoneInfo(config.TIMEZONE)
    traded = max(share.market_time for share in shares).astimezone(uk)
    note = f"last trade {traded:%a %H:%M}, page drawn {now:%H:%M}"
    draw.text((config.WIDTH - MARGIN, SHARES_TOP + 4), note, font=_font(12), fill=BLACK, anchor="ra")

    price_right = 300
    change_right = config.WIDTH - MARGIN
    y = SHARES_TOP + 21
    for share in shares:
        draw.text((MARGIN, y + 1), share.name, font=_font(17, BOLD), fill=BLACK)
        draw.text((MARGIN, y + 21), f"{share.ticker} ({share.currency})", font=_font(12), fill=BLACK)
        draw.text((price_right, y + 3), f"{share.price:,.2f}", font=_font(27, BOLD), fill=BLACK, anchor="ra")
        change = share.change_percent
        draw.text(
            (change_right, y + 8),
            f"{change:+.1f}%",
            font=_font(19, BOLD),
            fill=RED if change < 0 else BLACK,
            anchor="ra",
        )
        y += SHARE_ROW_HEIGHT


def render(weather: Weather, shares: list[Share], now: datetime) -> Image.Image:
    """Draws the page, leaving a blank black band for the ESP32's header."""
    image = Image.new("RGB", (config.WIDTH, config.HEIGHT), WHITE)
    draw = ImageDraw.Draw(image)
    draw.fontmode = "1"  # No anti-aliasing: the panel has no greys.
    draw.rectangle((0, 0, config.WIDTH, config.HEADER_HEIGHT - 1), fill=BLACK)
    _weather(draw, weather)
    _shares(draw, shares, now)
    return image


def with_sample_header(page: Image.Image, now: datetime) -> Image.Image:
    """Approximates the ESP32's header, for preview.png only."""
    preview = page.copy()
    draw = ImageDraw.Draw(preview)
    draw.fontmode = "1"
    font = _font(15, BOLD)
    middle = config.HEADER_HEIGHT // 2
    new_york = now.astimezone(ZoneInfo("America/New_York"))
    draw.text((8, middle), f"{now:%a} {now.day} {now:%b}  UK {now:%H:%M}", font=font, fill=WHITE, anchor="lm")
    draw.text((282, middle), f"NY {new_york:%H:%M}", font=font, fill=WHITE, anchor="rm")
    draw.text((392, middle), "Batt 2.9V", font=font, fill=WHITE, anchor="rm")
    return preview
