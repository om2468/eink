# E-ink display: NRF_EPD_C0DC

A Bluetooth e-ink calendar repurposed as a dashboard, updated by an ESP32-S3 so no computer needs to be on.

**The page shows:** London weather, a 5-day forecast and today's sunset, the UK and New York times, the display's battery, and Cloudflare, Novo Nordisk and Eli Lilly share prices. It updates every 30 minutes from 08:00 to 19:00 UK time.

## How it works

```
GitHub Actions (:25 and :55)            ESP32-S3 (:00 and :30, 08:00-19:00 UK)         Display
  fetch weather and shares      --->      download page.bin                    --->    show page
  draw page, publish page.bin             add times and battery
  to GitHub Pages                         send over Bluetooth, disconnect
```

- [dashboard/](dashboard/): draws the page. Location and share list are in [dashboard/config.py](dashboard/config.py).
- [.github/workflows/publish.yml](.github/workflows/publish.yml): runs it on a schedule and publishes to GitHub Pages.
- [firmware/](firmware/): the ESP32 program, compiled by [.github/workflows/firmware.yml](.github/workflows/firmware.yml).

The ESP32 draws the top bar because the battery reading comes from the display, and so the times stay right if a GitHub run starts late.

## Setup

### 1. Publish the page

The repo must be public for free GitHub Pages, and needs **Settings > Pages > Source: GitHub Actions**. The page is then at <https://om2468.github.io/eink/page.bin>, with a preview at <https://om2468.github.io/eink/preview.png>.

To try it locally:

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest
.venv/bin/python -m dashboard  # writes site/page.bin and site/preview.png
```

### 2. Flash the ESP32

GitHub Actions compiles the firmware, so no toolchain is needed locally. It's published without Wi-Fi details at the `firmware-latest` release.

```sh
cp firmware/src/secrets.h.example firmware/src/secrets.h  # then add your Wi-Fi details
python3 -m venv .venv-fw
.venv-fw/bin/pip install esptool pyserial

PORT=/dev/cu.usbmodemXXXX
curl -LO https://github.com/om2468/eink/releases/download/firmware-latest/firmware-merged.bin
.venv-fw/bin/esptool --port $PORT write-flash 0x0 firmware-merged.bin
.venv-fw/bin/python scripts/set_wifi.py $PORT  # stores your Wi-Fi details on the board
```

`secrets.h` is ignored by git. The Wi-Fi details stay on the board when firmware is reflashed this way. Send `u` over the serial port at 115200 baud to force an update.

The board must be on 2.4 GHz Wi-Fi, within Bluetooth range of the display, and on USB power.

## Things to know

- **One connection at a time:** a browser connected to the display blocks the ESP32. Always disconnect at epdiy.cn.
- **Failures:** if a fetch fails, the last published page stays. If the ESP32 can't update after 3 tries, the old page stays on screen. The share section shows when the page was drawn, so old data is visible.
- **GitHub schedules:** runs can start late, and GitHub disables scheduled workflows after 60 days without repo activity. If the "page drawn" time stops changing, re-enable the workflow in the Actions tab.
- **Share prices:** these come from Yahoo Finance's unofficial chart endpoint, which could change or block requests. Novo uses its New York listing (`NVO`) so all prices are in USD. The change is against the previous close.
- **Times:** the New York time is as of the last update, so it's up to 30 minutes old.
- **Battery:** each update uses power, and 23 updates a day is far more than the calendar's daily redraw. Stripes, garbled text, a white screen or 2.8 V mean it's low; the top bar then shows `LOW`.
- **Getting the calendar back:** stop the ESP32, then sync from epdiy.cn.

## The device

| | |
|---|---|
| Bluetooth name | `NRF_EPD_C0DC` |
| Reported firmware | `v1.10-nrf52811` |
| Model ID | `0x16` |
| Screen | 4.2-inch, 400×300, black/white/red, SSD1683 controller, per the vendor app's model table |
| Vendor web app | <https://epdiy.cn> |
| Battery | 3 V, 1.25 plug, or a rechargeable version |

The ESP32 used here is an ESP32-S3 with 16 MB flash and 8 MB PSRAM.

### Using the vendor web app

You need a browser with Web Bluetooth: Chrome on a computer, Bluefy on iPhone, Edge on Android. Open <https://epdiy.cn>, connect, choose `NRF_EPD_C0DC` and sync. To-do lists and class schedules are under **Templates** (模板).

**Always disconnect afterwards.** Closing the browser may leave the connection open. A steady blue light on the display means it's still connected, which drains the battery quickly.

## Firmware on the display

A vendor build that appears to be based on [EPD-nRF5](https://github.com/tsl0922/EPD-nRF5) (GPL-3.0). The vendor's source isn't available to us, and it differs from upstream:

- The version is returned as text rather than a single byte.
- The config is 14 bytes rather than 13.
- There are extra commands.
- **Model IDs don't match upstream**, so use the vendor table.

The protocol below comes from upstream commit `7e31961` and the vendor app's published JavaScript, read on 2026-11-07. Init, write image and refresh have been used on this display; the other commands are untested.

## Bluetooth protocol

| UUID | Purpose | Properties |
|---|---|---|
| `62750001-d828-918d-fb46-b6c11c675aec` | Display service | |
| `62750002-d828-918d-fb46-b6c11c675aec` | Commands and notifications | write, write without response, notify |
| `62750003-d828-918d-fb46-b6c11c675aec` | Firmware version | read |
| `0xFE59` | Nordic firmware update service | **Do not use** |

The display stops advertising while connected, so it won't appear in a scan.

### Reading the configuration

Turning on notifications makes the display send its configuration without changing the screen:

`mosi, sclk, cs, dc, rst, busy, bs, model_id, wakeup, led, en, display_mode, week_start`

This display returned `1413060504030216ff12070100ff`. The purpose of the 14th byte (`ff`) is unconfirmed.

### Commands

Each write is one command byte followed by its data.

| Byte | Command | Data | Notes |
|---|---|---|---|
| `0x01` | Init | optional model ID | Replies `mtu=<n> rle=1` and `t=<time> bat=<mV>`. **Passing a model ID saves it.** |
| `0x02` | Clear | optional refresh flag | Switches to picture mode |
| `0x05` | Refresh | | Shows the sent image and switches to picture mode |
| `0x06` | Panel sleep | | |
| `0x20` | Set time and mode | 4-byte Unix time (big-endian), signed timezone hours, mode | Redraws the screen |
| `0x21` | Week start | 0 = Sunday, 1 = Monday, and so on | Saved |
| `0x30` | Write image | flags, then image data | See below |

**Display modes:** `0` picture, `1` calendar, `2` clock. The mode is saved across restarts.

**Vendor-only, untested:** `0x07` LED blink, `0x22` countdown, `0x23` holidays, `0x31` set slot, `0x32` free slot (**permanently deletes the stored image**), `0x33` slideshow, `0x34` get image.

**Avoid:** `0x00` set pins, `0x03`/`0x04` raw panel access, `0x90` set config, `0x91` reset, `0x92` deep sleep and `0x99` erase config. These can change saved settings or stop the display working until it's reconfigured.

### Sending an image

1. Connect and turn on notifications.
2. Send `0x01` with no data. Read `mtu=<n>`, plus `intl=` if present. Wait 200 ms.
3. Send the black and white plane in chunks of at most `n - 2` bytes, each as `0x30, flags, data...`.
4. Send the red plane the same way.
5. Wait 300 ms, send `0x05`, wait for the redraw (30 seconds is known to work), then disconnect.

Between write responses, send `intl` chunks without response (capped at 50, or 10 if not set).

| Flag bit | Meaning when set |
|---|---|
| 0 | Red plane (not set = black and white plane) |
| 1 | First chunk of this plane |
| 2 | Chunk is RLE compressed |

**Pixel format for this panel:** two planes of 15,000 bytes each (50 bytes per row × 300 rows), row by row, most significant bit first.

| Pixel | Black and white plane | Red plane |
|---|---|---|
| White | `1` | `1` |
| Black | `0` | `1` |
| Red | `0` | `0` |

**RLE (optional):** each code is either `0x80 | (count - 3)` then the byte, for 3 to 130 repeats, or `count - 1` then that many bytes, for 1 to 128 literals. A code must not be split across chunks. The ESP32 sends uncompressed, which is simpler and quick enough.

## Sources

- [EPD-nRF5](https://github.com/tsl0922/EPD-nRF5) source
- The vendor web app's published JavaScript at <https://epdiy.cn>
- The vendor's printed user guide
- Direct inspection of the device on 2026-11-07
- Data: [Open-Meteo](https://open-meteo.com/) and Yahoo Finance
- Fonts: [Liberation Sans](https://github.com/liberationfonts/liberation-fonts) (SIL Open Font License)
