"""Draws the dashboard page in pure black, white and red."""

from datetime import datetime

from PIL import Image, ImageDraw, ImageFont

from . import config
from .data import Weather

BLACK = (0, 0, 0)
WHITE = (255, 255, 255)
RED = (255, 0, 0)

FONT_PATH = "/System/Library/Fonts/Helvetica.ttc"
REGULAR = 0
BOLD = 1

MARGIN = 10
HEADER_HEIGHT = 26
NEWS_TOP = 138
LINE_HEIGHT = 17
NEWS_FONT_SIZE = 15


def _font(size: int, index: int = REGULAR) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT_PATH, size, index=index)


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


def wrap(text: str, font: ImageFont.FreeTypeFont, width: int, max_lines: int) -> list[str]:
    """Word-wrap text, ending with an ellipsis if it doesn't fit."""
    lines: list[str] = []
    words = text.split()
    while words and len(lines) < max_lines:
        line = words.pop(0)
        while words and font.getlength(f"{line} {words[0]}") <= width:
            line = f"{line} {words.pop(0)}"
        lines.append(line)
    if words:
        last = lines[-1]
        while last and font.getlength(f"{last}...") > width:
            last = last.rsplit(" ", 1)[0] if " " in last else last[:-1]
        lines[-1] = f"{last}..."
    return lines


def _header(draw: ImageDraw.ImageDraw, now: datetime) -> None:
    draw.rectangle((0, 0, config.WIDTH, HEADER_HEIGHT - 1), fill=BLACK)
    draw.text((MARGIN, HEADER_HEIGHT // 2), config.LOCATION_NAME, font=_font(16, BOLD), fill=WHITE, anchor="lm")
    stamp = f"{now:%a} {now.day} {now:%b}, updated {now:%H:%M}"
    draw.text((config.WIDTH - MARGIN, HEADER_HEIGHT // 2), stamp, font=_font(14), fill=WHITE, anchor="rm")


def _weather(draw: ImageDraw.ImageDraw, weather: Weather) -> None:
    top = HEADER_HEIGHT + 6
    _icon(draw, MARGIN, top + 2, 56, weather.code, weather.is_day)
    temperature = f"{round(weather.temperature)}°"
    big = _font(46, BOLD)
    draw.text((MARGIN + 62, top - 3), temperature, font=big, fill=BLACK)

    x = MARGIN + 62 + int(big.getlength(temperature)) + 10
    today = weather.days[0]
    draw.text((x, top + 3), describe(weather.code), font=_font(16, BOLD), fill=BLACK)
    draw.text((x, top + 22), f"Feels {round(weather.feels_like)}°, wind {round(weather.wind_mph)} mph", font=_font(14), fill=BLACK)
    draw.text((x, top + 39), f"High {round(today.high)}°  Low {round(today.low)}°  Rain {today.rain_chance}%", font=_font(14), fill=BLACK)

    # Next three days.
    strip_top = top + 60
    forecast = weather.days[1:4]
    column = (config.WIDTH - 2 * MARGIN) // max(len(forecast), 1)
    for i, day in enumerate(forecast):
        cx = MARGIN + column * i
        _icon(draw, cx, strip_top + 1, 28, day.code)
        draw.text((cx + 32, strip_top), f"{day.date:%a}", font=_font(13, BOLD), fill=BLACK)
        draw.text((cx + 32, strip_top + 15), f"{round(day.high)}°/{round(day.low)}°", font=_font(13), fill=BLACK)


def _news(draw: ImageDraw.ImageDraw, headlines: list[str]) -> None:
    draw.line((MARGIN, NEWS_TOP, config.WIDTH - MARGIN, NEWS_TOP), fill=RED, width=2)
    draw.text((MARGIN, NEWS_TOP + 4), config.NEWS_LABEL.upper(), font=_font(13, BOLD), fill=RED)

    font = _font(NEWS_FONT_SIZE)
    bullet_indent = 10
    y = NEWS_TOP + 21
    for headline in headlines:
        lines = wrap(headline, font, config.WIDTH - 2 * MARGIN - bullet_indent, max_lines=2)
        if y + LINE_HEIGHT * len(lines) > config.HEIGHT - 2:
            break
        draw.rectangle((MARGIN, y + 6, MARGIN + 3, y + 9), fill=RED)
        for line in lines:
            draw.text((MARGIN + bullet_indent, y), line, font=font, fill=BLACK)
            y += LINE_HEIGHT
        y += 3


def render(weather: Weather, headlines: list[str], now: datetime) -> Image.Image:
    image = Image.new("RGB", (config.WIDTH, config.HEIGHT), WHITE)
    draw = ImageDraw.Draw(image)
    draw.fontmode = "1"  # No anti-aliasing: the panel has no greys.
    _header(draw, now)
    _weather(draw, weather)
    _news(draw, headlines)
    return image
