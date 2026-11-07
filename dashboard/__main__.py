"""Fetch weather and news, draw the page and send it to the display.

    python -m dashboard            # update the display
    python -m dashboard --dry-run  # only write the preview image
"""

import argparse
import asyncio
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from . import config
from .data import fetch_headlines, fetch_weather
from .display import send_image
from .render import render

PREVIEW_PATH = Path(__file__).resolve().parent.parent / "preview.png"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="write preview.png without using Bluetooth")
    args = parser.parse_args()

    now = datetime.now(ZoneInfo(config.TIMEZONE))
    # If a fetch fails, this exits before touching the display, so the previous
    # page stays on screen rather than a partial one.
    image = render(fetch_weather(), fetch_headlines(), now)
    image.save(PREVIEW_PATH)
    print(f"{now:%Y-%m-%d %H:%M} wrote {PREVIEW_PATH}", flush=True)

    if args.dry_run:
        return 0

    asyncio.run(send_image(image))
    print(f"{now:%Y-%m-%d %H:%M} sent to {config.DEVICE_NAME}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
