from datetime import date, datetime, timezone

from PIL import Image

from dashboard import config
from dashboard.data import Day, Share, Weather, parse_share
from dashboard.encode import encode_planes
from dashboard.render import render


def test_pixel_encoding():
    image = Image.new("RGB", (8, 2), (255, 255, 255))
    image.putpixel((0, 0), (0, 0, 0))
    image.putpixel((1, 0), (255, 0, 0))
    image.putpixel((7, 1), (255, 0, 0))
    encoded = encode_planes(image)
    assert encoded[:2] == bytes((0b00111111, 0b11111110))  # Black and white plane.
    assert encoded[2:] == bytes((0b10111111, 0b11111110))  # Red plane.


def test_parse_share():
    body = {
        "chart": {
            "result": [
                {
                    "meta": {
                        "symbol": "NET",
                        "currency": "USD",
                        "regularMarketPrice": 110.0,
                        "chartPreviousClose": 100.0,
                        "regularMarketTime": 0,
                    }
                }
            ]
        }
    }
    share = parse_share("Cloudflare", body)
    assert share.ticker == "NET"
    assert share.change_percent == 10.0


def test_page_has_panel_size_and_blank_header():
    day = Day(date(2026, 11, 7), 61, 11.0, 7.0, 40)
    weather = Weather(8.0, 7.0, 3, 5.0, True, datetime(2026, 11, 7, 16, 23), [day] * 6)
    share = Share("Eli Lilly", "LLY", "USD", 1354.0, 1364.73, datetime(2026, 11, 7, tzinfo=timezone.utc))
    page = render(weather, [share] * 3, datetime(2026, 11, 7, 10, 30, tzinfo=timezone.utc))

    assert page.size == (config.WIDTH, config.HEIGHT)
    assert len(encode_planes(page)) == 30000
    # The ESP32 overwrites the header, so nothing may be drawn there.
    header = page.crop((0, 0, config.WIDTH, config.HEADER_HEIGHT))
    assert header.getcolors() == [(config.WIDTH * config.HEADER_HEIGHT, (0, 0, 0))]
