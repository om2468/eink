# E-ink display: NRF_EPD_C0DC

Notes on a Bluetooth e-ink calendar, and on using it to show weather and news.

**Status (2026-11-07):** a weather and news page has been sent to the display without errors. How it looks on the screen and the hourly job are both still to be confirmed.

## Quick start

Requires macOS, because the page uses the system Helvetica font.

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

.venv/bin/python -m dashboard --dry-run  # write preview.png only
.venv/bin/python -m dashboard            # update the display (takes about a minute)
.venv/bin/python -m pytest               # run the tests
```

Disconnect any browser session first, because the display accepts one connection at a time.

Location, news feed and device name are in [dashboard/config.py](dashboard/config.py).

### Updating every hour

```sh
zsh scripts/install_schedule.sh
```

This installs a launchd job that runs at the start of each hour and logs to `logs/dashboard.log`. If the laptop was asleep at that time, the job runs once when it wakes. macOS may ask for Bluetooth permission the first time.

To remove it:

```sh
launchctl bootout gui/$(id -u)/com.eink.dashboard
rm ~/Library/LaunchAgents/com.eink.dashboard.plist
```

If a weather or news fetch fails, the display keeps the previous page. The time in the header shows when it last updated.

## The device

| | |
|---|---|
| Bluetooth name | `NRF_EPD_C0DC` |
| Reported firmware | `v1.10-nrf52811` |
| Chip family | Nordic nRF52811, going by the firmware string |
| Vendor web app | <https://epdiy.cn> |
| Battery | 3 V, 1.25 plug, or a rechargeable version |
| Model ID | `0x16` |
| Screen | 4.2-inch, 400×300, black/white/red, SSD1683 controller, according to the vendor app's model table |
| Current mode | Calendar, week starting Sunday |

The name is not a pairing code. The `C0DC` suffix comes from the last two bytes of the device's Bluetooth address.

## Using it with the vendor web app

You need a browser with Web Bluetooth:

- **Computer:** Chrome
- **iPhone:** Bluefy, from the App Store
- **Android:** Edge

Most phones' built-in browsers don't support Bluetooth.

1. Open <https://epdiy.cn>.
2. Connect and choose `NRF_EPD_C0DC`.
3. Sync. To-do lists and class schedules are under **Templates** (模板).
4. **Disconnect when finished.**

### Battery

- **Always disconnect.** Closing the browser may leave the connection open. A steady blue light means it's still connected, which drains the battery quickly.
- **Low battery signs:** a white screen, artifacts, stripes, garbled text, or a reading of 2.8 V. Replace or recharge the battery, then sync once.
- **Supplied battery:** the non-rechargeable version ships with a trial battery that may not last long.

## Firmware

The display runs a vendor build that appears to be based on [EPD-nRF5](https://github.com/tsl0922/EPD-nRF5) (GPL-3.0). The vendor's source isn't available to us.

**What matches upstream:** the Bluetooth service ID, the name format, the core commands and the image transfer format.

**What differs:**

- The version is returned as text rather than a single byte.
- The config is 14 bytes rather than 13.
- There are extra commands (see [Vendor-only commands](#vendor-only-commands)).
- **Model IDs don't match.** `0x16` isn't in the upstream list, and some IDs mean different panels (`0x0e`, `0x0f`, `0x10`, `0x11`). Use the vendor table, not the upstream one.

The protocol below comes from upstream commit `7e31961` and the vendor app's published JavaScript, read on 2026-11-07. Init, write image and refresh have been sent to this display without errors. **The other commands are untested.**

## Bluetooth protocol

### Services

| UUID | Purpose | Properties |
|---|---|---|
| `62750001-d828-918d-fb46-b6c11c675aec` | Display service | |
| `62750002-d828-918d-fb46-b6c11c675aec` | Commands and notifications | write, write without response, notify |
| `62750003-d828-918d-fb46-b6c11c675aec` | Firmware version | read |
| `0xFE59` | Nordic firmware update service | **Do not use** |

The display accepts one connection at a time and stops advertising while connected. It won't appear in a scan while a browser is connected to it.

### Reading the configuration

Turning on notifications makes the display send its configuration, without changing the screen. The fields, one byte each, are:

`mosi, sclk, cs, dc, rst, busy, bs, model_id, wakeup, led, en, display_mode, week_start`

This display returned `1413060504030216ff12070100ff`. The 14th byte (`ff`) isn't in the upstream layout. The vendor app stores it in the same place as a value from its `slots=` reply, so it's probably slot-related.

### Commands

Each write is one command byte followed by its data.

| Byte | Command | Data | Notes |
|---|---|---|---|
| `0x01` | Init | optional model ID | Replies `mtu=<n> rle=1` and `t=<time>`. **Passing a model ID saves it.** |
| `0x02` | Clear | optional refresh flag | Switches to picture mode |
| `0x05` | Refresh | | Shows the sent image and switches to picture mode |
| `0x06` | Panel sleep | | |
| `0x20` | Set time and mode | 4-byte Unix time (big-endian), signed timezone hours, mode | Redraws the screen |
| `0x21` | Week start | 0 = Sunday, 1 = Monday, and so on | Saved |
| `0x30` | Write image | flags, then image data | See below |

**Display modes:** `0` picture, `1` calendar, `2` clock. The mode is saved across restarts.

### Vendor-only commands

These names come from the vendor app. Whether this firmware supports them is untested.

| Byte | Command | What the app sends | Notes |
|---|---|---|---|
| `0x07` | LED blink | | |
| `0x22` | Set countdown | | Format not checked |
| `0x23` | Set holidays | | Format not checked |
| `0x31` | Set slot | `1, slot` | Shows or selects a stored image |
| `0x32` | Free slot | `slot` | **Permanently deletes the stored image** |
| `0x33` | Set slideshow | interval in minutes, 2 bytes big-endian (1 to 65535) | Rotates stored images |
| `0x34` | Get image | `slot` | Reads a stored image back; the app warns some firmware doesn't support it |

The app also handles these notifications: `slots=<count> <used mask> <value>`, `img=...`, `err=busy` (screen already refreshing), `clock_enable=<0|1>` and `intl=<n>` (part of the `mtu=` reply).

### Commands to avoid

These can change saved settings or stop the display working until it's reconfigured:

| Byte | Command | Risk |
|---|---|---|
| `0x00` | Set pins | Wrong values break communication with the panel |
| `0x03`, `0x04` | Raw panel command or data | Bypasses the driver |
| `0x90` | Set config | Overwrites saved settings |
| `0x91`, `0x92` | Reset, deep sleep | Deep sleep may need a physical wake-up |
| `0x99` | Erase config | Erases saved settings and resets |

### Sending an image

These steps follow the vendor app, for this display's model.

1. Connect and turn on notifications.
2. Send `0x01` with no data. Read `mtu=<n>`, plus `rle=` and `intl=` if present. Wait 200 ms.
3. Send the black and white plane in chunks of at most `n - 2` bytes, each as `0x30, flags, data...`.
4. Send the red plane the same way.
5. Wait 300 ms, then send `0x05` to refresh.
6. Wait for the refresh to finish, then disconnect.

Between write responses, the app sends `intl` chunks without response (capped at 50, or 10 if not set).

**Flags:**

| Bit | Meaning when set |
|---|---|
| 0 | Red plane (not set = black and white plane) |
| 1 | First chunk of this plane |
| 2 | Chunk is RLE compressed |

**Pixel format for this panel:** two planes of 15,000 bytes each (50 bytes per row × 300 rows). Pixels run row by row, most significant bit first.

| Pixel | Black and white plane | Red plane |
|---|---|---|
| White | `1` | `1` |
| Black | `0` | `1` |
| Red | either | `0` |

Other models use other formats. The vendor table and conversion code are in the app's JavaScript.

**RLE:** each code is one of these, and a code must not be split across chunks:

- **Repeat:** `0x80 | (count - 3)`, then the byte, for 3 to 130 repeats
- **Literal:** `count - 1`, then that many bytes, for 1 to 128 bytes

### Returning to the calendar

Sending an image leaves the display in picture mode, so the calendar stops updating. To restore it, send `0x20` with the current time, timezone and mode `1`. Syncing from the web app should do the same.

## Weather and news page

The display has no weather or news feature we know of, so the page is sent as an image:

1. Fetch the London forecast from [Open-Meteo](https://open-meteo.com/) and headlines from the BBC News RSS feed.
2. Draw a 400×300 page in black, white and red.
3. Send it over Bluetooth and disconnect.

Limits:

- **Laptop:** new data only arrives while it's awake and within Bluetooth range.
- **Battery:** hourly updates use noticeably more power than the daily calendar redraw. Watch for the low battery signs above.
- **Calendar:** the built-in calendar is replaced while this is running. Sync from the web app to bring it back, and remove the hourly job or it will be replaced again.

If this firmware supports image slots, weather and news could be stored as separate images and rotated with the slideshow command.

## Open questions

- [ ] Does the page look right on the physical screen, including red?
- [ ] Does the hourly job get Bluetooth permission when run by launchd?
- [ ] How long does the battery last at hourly updates?
- [ ] Does this firmware support slots, and how many? The `slots=` reply should show this.

## Sources

- [EPD-nRF5](https://github.com/tsl0922/EPD-nRF5): `EPD/EPD_service.c`, `EPD/EPD_service.h`, `EPD/EPD_config.h`, `html/js/main.js`, `html/js/rle.js`, `html/js/dithering.js`
- The vendor web app at <https://epdiy.cn>: model table, commands and image-sending code in its published JavaScript
- The vendor's printed user guide
- Direct inspection of the device on 2026-11-07: scan, service list, version and config
