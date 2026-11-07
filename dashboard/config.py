"""Settings for the page. Change these to change what the display shows."""

LOCATION_NAME = "London"
LATITUDE = 51.5074
LONGITUDE = -0.1278
TIMEZONE = "Europe/London"

# (name on the page, Yahoo Finance ticker). All are New York listings, in USD.
SHARES = [
    ("Cloudflare", "NET"),
    ("Novo Nordisk", "NVO"),
    ("Eli Lilly", "LLY"),
]

# 4.2-inch black/white/red panel (model 0x16).
WIDTH = 400
HEIGHT = 300

# The ESP32 draws the UK time, New York time and battery over this many rows at
# the top of the page. Keep in step with HEADER_HEIGHT in firmware/src/main.cpp.
HEADER_HEIGHT = 28
