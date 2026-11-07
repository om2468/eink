"""Fetches the data and writes the page for the ESP32 to download.

    python -m dashboard

Writes site/page.bin, the page in the panel's format, and site/preview.png.
If a fetch fails this exits with an error and writes nothing, so the last
published page stays in place.
"""

import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from . import config
from .data import fetch_shares, fetch_weather
from .encode import encode_planes
from .render import render, with_sample_header

SITE = Path(__file__).resolve().parent.parent / "site"


def main() -> int:
    now = datetime.now(ZoneInfo(config.TIMEZONE))
    page = render(fetch_weather(), fetch_shares(), now)

    SITE.mkdir(exist_ok=True)
    (SITE / "page.bin").write_bytes(encode_planes(page))
    with_sample_header(page, now).save(SITE / "preview.png")
    print(f"{now:%Y-%m-%d %H:%M} wrote {SITE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
