# Updates the e-ink display. Downloads the published page, adds the date and
# battery level, and sends it over Bluetooth, every 30 minutes from 08:00 to
# 19:00 UK time. The protocol is documented in the repo's README.
#
# Start it from main.py as a background task:   asyncio.create_task(eink.run())
# Force an update from the REPL:                asyncio.run(eink.update())

import asyncio
import gc
import time

import bluetooth
import framebuf
import network
import ntptime
import requests
from header_font import GLYPHS, HEIGHT as GLYPH_HEIGHT

PAGE_URL = "https://om2468.github.io/eink/page.bin"
DEVICE_NAME = b"NRF_EPD_C0DC"
COMMAND_CHAR = bluetooth.UUID("62750002-d828-918d-fb46-b6c11c675aec")

FIRST_UPDATE_MINUTE = 8 * 60
LAST_UPDATE_MINUTE = 19 * 60
ATTEMPTS = 3
RETRY_DELAY_S = 60

WIDTH = 400
HEIGHT = 300
ROW_BYTES = WIDTH // 8
PLANE_SIZE = ROW_BYTES * HEIGHT
PAGE_SIZE = PLANE_SIZE * 2
# Keep in step with HEADER_HEIGHT in dashboard/config.py.
HEADER_HEIGHT = 28

EXPECTED_MODEL = 0x16
CONFIG_MODEL_INDEX = 7
CMD_INIT = b"\x01"
CMD_REFRESH = b"\x05"
CMD_WRITE_IMAGE = 0x30
FLAG_RED_PLANE = 0x01
FLAG_FIRST_CHUNK = 0x02
DEFAULT_ACK_INTERVAL = 10
MAX_ACK_INTERVAL = 50
REPLY_TIMEOUT_MS = 5000
# Stay connected while the panel redraws. 30 seconds is known to work.
REFRESH_WAIT_S = 30
# The display's guide says 2.8 V means the battery is low.
LOW_BATTERY_MV = 2800

_IRQ_SCAN_RESULT = 5
_IRQ_SCAN_DONE = 6
_IRQ_PERIPHERAL_CONNECT = 7
_IRQ_PERIPHERAL_DISCONNECT = 8
_IRQ_GATTC_CHARACTERISTIC_RESULT = 11
_IRQ_GATTC_CHARACTERISTIC_DONE = 12
_IRQ_GATTC_WRITE_DONE = 17
_IRQ_GATTC_NOTIFY = 18
_IRQ_MTU_EXCHANGED = 21

_page = bytearray(PAGE_SIZE)
_days = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_months = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


# Time. The board's clock runs on UTC.


def _sunday(year, month, first_day):
    """First Sunday on or after first_day."""
    day = first_day
    while time.gmtime(time.mktime((year, month, day, 0, 0, 0, 0, 0)))[6] != 6:
        day += 1
    return day


def _utc(year, month, day, hour):
    return time.mktime((year, month, day, hour, 0, 0, 0, 0))


def _uk_time(now):
    year = time.gmtime(now)[0]
    start = _utc(year, 3, _sunday(year, 3, 25), 1)
    end = _utc(year, 10, _sunday(year, 10, 25), 1)
    return time.gmtime(now + (3600 if start <= now < end else 0))


def _clock_is_set():
    return time.gmtime()[0] >= 2024


# Network.


async def _connect_wifi():
    sta = network.WLAN(network.STA_IF)
    # boot.py may still be connecting, and starting again during that is an error.
    for _ in range(20):
        if sta.isconnected():
            return True
        await asyncio.sleep(1)
    import wifi  # The board's existing helper, which uses wifi.json.

    return wifi.auto(15)


def _sync_clock():
    # Single requests often time out, and each one only waits about a second.
    for _ in range(5):
        try:
            ntptime.settime()
            return
        except Exception as e:
            error = e
    print("eink: clock sync failed:", error)


def _download_page():
    response = requests.get("%s?t=%d" % (PAGE_URL, time.time()))
    try:
        if response.status_code != 200:
            raise OSError("download status %d" % response.status_code)
        view = memoryview(_page)
        received = 0
        while received < PAGE_SIZE:
            count = response.raw.readinto(view[received:])
            if not count:
                break
            received += count
        # One extra byte would mean the file is bigger than the panel.
        if received != PAGE_SIZE or response.raw.read(1):
            raise OSError("wrong page size")
    finally:
        response.close()


# Top bar.


def _text_width(text):
    return sum(GLYPHS[c][0] if c in GLYPHS else GLYPHS["?"][0] for c in text)


def _text(canvas, text, x):
    y = (HEADER_HEIGHT - GLYPH_HEIGHT) // 2
    for c in text:
        width, pixels = GLYPHS[c] if c in GLYPHS else GLYPHS["?"]
        # The extra argument makes unset pixels transparent.
        canvas.blit(framebuf.FrameBuffer(bytearray(pixels), width, GLYPH_HEIGHT, framebuf.MONO_HLSB), x, y, 0)
        x += width


def _draw_header(battery_mv):
    """Draws into the black and white plane, where a set bit is white."""
    uk = _uk_time(time.time())

    pixels = bytearray(ROW_BYTES * HEADER_HEIGHT)
    canvas = framebuf.FrameBuffer(pixels, WIDTH, HEADER_HEIGHT, framebuf.MONO_HLSB)
    canvas.fill(0)
    _text(canvas, "London  %s %d %s" % (_days[uk[6]], uk[2], _months[uk[1] - 1]), 8)
    if battery_mv <= 0:
        battery = "Batt ?"
    else:
        label = "LOW" if battery_mv <= LOW_BATTERY_MV else "Batt"
        battery = "%s %d.%02dV" % (label, battery_mv // 1000, battery_mv % 1000 // 10)
    _text(canvas, battery, WIDTH - 8 - _text_width(battery))

    # MONO_HLSB rows match the panel's layout, so they can be copied straight in.
    _page[: ROW_BYTES * HEADER_HEIGHT] = pixels


# Bluetooth.


def _adv_name(data):
    i = 0
    while i + 1 < len(data):
        length = data[i]
        if length and data[i + 1] in (0x08, 0x09):
            return bytes(data[i + 2 : i + 1 + length])
        i += 1 + length
    return None


class _Display:
    def __init__(self):
        self.ble = bluetooth.BLE()
        self.found = None
        self.scan_done = False
        self.conn = None
        self.disconnected = False
        self.handle = None
        self.discovery_done = False
        self.write_done = False
        self.mtu = 23
        self.notifications = []

    def _irq(self, event, data):
        if event == _IRQ_SCAN_RESULT:
            addr_type, addr, _, _, adv_data = data
            if self.found is None and _adv_name(adv_data) == DEVICE_NAME:
                self.found = (addr_type, bytes(addr))
                self.ble.gap_scan(None)
        elif event == _IRQ_SCAN_DONE:
            self.scan_done = True
        elif event == _IRQ_PERIPHERAL_CONNECT:
            self.conn = data[0]
        elif event == _IRQ_PERIPHERAL_DISCONNECT:
            self.disconnected = True
        elif event == _IRQ_GATTC_CHARACTERISTIC_RESULT:
            if data[4] == COMMAND_CHAR:
                self.handle = data[2]
        elif event == _IRQ_GATTC_CHARACTERISTIC_DONE:
            self.discovery_done = True
        elif event == _IRQ_GATTC_WRITE_DONE:
            self.write_done = True
        elif event == _IRQ_GATTC_NOTIFY:
            self.notifications.append(bytes(data[2]))
        elif event == _IRQ_MTU_EXCHANGED:
            self.mtu = data[1]

    async def _wait(self, condition, timeout_ms, what):
        started = time.ticks_ms()
        while not condition():
            if self.disconnected:
                raise OSError("display disconnected while waiting for " + what)
            if time.ticks_diff(time.ticks_ms(), started) > timeout_ms:
                raise OSError("timed out waiting for " + what)
            await asyncio.sleep_ms(10)

    async def _write(self, data, mode):
        # Fails with an error while the Bluetooth stack's buffers are full.
        for _ in range(100):
            try:
                self.ble.gattc_write(self.conn, self.handle, data, mode)
                return
            except OSError:
                await asyncio.sleep_ms(10)
        raise OSError("write failed")

    async def _write_acked(self, data):
        self.write_done = False
        await self._write(data, 1)
        await self._wait(lambda: self.write_done, REPLY_TIMEOUT_MS, "write")

    async def _write_fast(self, data):
        await self._write(data, 0)

    async def _next_notification(self, timeout_ms=REPLY_TIMEOUT_MS):
        await self._wait(lambda: self.notifications, timeout_ms, "reply")
        return self.notifications.pop(0)

    async def connect(self):
        self.ble.active(True)
        self.ble.config(mtu=247)
        self.ble.irq(self._irq)
        self.ble.gap_scan(20000, 30000, 30000, True)
        # Connecting only works once the scan has fully stopped.
        await self._wait(lambda: self.scan_done, 25000, "scan")
        if not self.found:
            raise OSError("display not found. Is a browser connected to it?")
        self.ble.gap_connect(self.found[0], self.found[1])
        await self._wait(lambda: self.conn is not None, 15000, "connection")
        try:
            self.ble.gattc_exchange_mtu(self.conn)
        except OSError:
            pass  # Already negotiated when connecting; the result still arrives as an event.
        await asyncio.sleep_ms(500)
        self.ble.gattc_discover_characteristics(self.conn, 1, 0xFFFF)
        await self._wait(lambda: self.discovery_done, REPLY_TIMEOUT_MS, "services")
        if self.handle is None:
            raise OSError("display service not found")

    async def start_session(self):
        """Returns (largest chunk, ack interval, battery in mV)."""
        # Turning on notifications makes the display send its config. The
        # notification setting is the handle straight after the characteristic.
        self.write_done = False
        self.ble.gattc_write(self.conn, self.handle + 1, b"\x01\x00", 1)
        await self._wait(lambda: self.write_done, REPLY_TIMEOUT_MS, "notifications")

        # Check the model before changing anything.
        config = await self._next_notification()
        if len(config) <= CONFIG_MODEL_INDEX or config[CONFIG_MODEL_INDEX] != EXPECTED_MODEL:
            raise OSError("unexpected display config")

        await self._write_acked(CMD_INIT)
        reply_mtu = 0
        rle = False
        ack_interval = DEFAULT_ACK_INTERVAL
        battery_mv = 0
        started = time.ticks_ms()
        # The time and battery reply follows the MTU reply, but may not be there.
        while not battery_mv and time.ticks_diff(time.ticks_ms(), started) < REPLY_TIMEOUT_MS:
            if not self.notifications:
                await asyncio.sleep_ms(10)
                continue
            text = self.notifications.pop(0).decode()
            print("eink: display says", text)
            for part in text.split():
                if part.startswith("err="):
                    raise OSError("display replied " + text)
                if part.startswith("mtu="):
                    reply_mtu = int(part[4:])
                elif part == "rle=1":
                    rle = True
                elif part.startswith("intl="):
                    ack_interval = min(int(part[5:]), MAX_ACK_INTERVAL)
                elif part.startswith("bat="):
                    battery_mv = int(part[4:])
        # rle=1 marks the firmware generation whose image flags are used here.
        if reply_mtu <= 2 or not rle:
            raise OSError("display didn't report a supported session")
        return min(reply_mtu, self.mtu - 3) - 2, ack_interval, battery_mv

    async def send_plane(self, plane, is_red, max_chunk, ack_interval):
        view = memoryview(plane)
        since_ack = 0
        for offset in range(0, PLANE_SIZE, max_chunk):
            flags = (FLAG_RED_PLANE if is_red else 0) | (FLAG_FIRST_CHUNK if offset == 0 else 0)
            packet = bytes((CMD_WRITE_IMAGE, flags)) + view[offset : offset + max_chunk]
            if since_ack >= ack_interval:
                await self._write_acked(packet)
                since_ack = 0
            else:
                await self._write_fast(packet)
                since_ack += 1
                await asyncio.sleep_ms(5)

    async def refresh(self):
        await asyncio.sleep_ms(300)
        await self._write_acked(CMD_REFRESH)
        await asyncio.sleep(REFRESH_WAIT_S)

    async def close(self):
        # Always disconnect: staying connected drains the display's battery fast.
        try:
            if self.conn is not None and not self.disconnected:
                self.ble.gap_disconnect(self.conn)
                await asyncio.sleep_ms(500)
        except OSError:
            pass
        self.ble.irq(None)
        self.ble.active(False)


async def update():
    """One full update. Raises an exception if it fails."""
    if not await _connect_wifi():
        raise OSError("no Wi-Fi")
    _sync_clock()
    if not _clock_is_set():
        raise OSError("clock not set")
    gc.collect()
    _download_page()

    display = _Display()
    try:
        await display.connect()
        max_chunk, ack_interval, battery_mv = await display.start_session()
        await asyncio.sleep_ms(200)
        _draw_header(battery_mv)
        print("eink: sending, chunk", max_chunk, "ack every", ack_interval, "battery", battery_mv)
        await display.send_plane(memoryview(_page)[:PLANE_SIZE], False, max_chunk, ack_interval)
        await display.send_plane(memoryview(_page)[PLANE_SIZE:], True, max_chunk, ack_interval)
        await display.refresh()
    finally:
        await display.close()
    print("eink: update complete")


async def _update_with_retries():
    for attempt in range(ATTEMPTS):
        try:
            await update()
            return
        except Exception as e:
            print("eink: attempt", attempt + 1, "failed:", e)
            if attempt + 1 < ATTEMPTS:
                await asyncio.sleep(RETRY_DELAY_S)
    print("eink: giving up until the next slot; the previous page stays on screen")


async def run():
    """Runs forever, updating at each slot. Errors never stop the caller's tasks."""
    last_slot = None
    while True:
        try:
            if not _clock_is_set():
                if await _connect_wifi():
                    _sync_clock()
            if _clock_is_set():
                uk = _uk_time(time.time())
                minute = uk[3] * 60 + uk[4]
                slot = (uk[7], minute)
                is_slot = uk[4] % 30 == 0 and FIRST_UPDATE_MINUTE <= minute <= LAST_UPDATE_MINUTE
                if is_slot and slot != last_slot:
                    last_slot = slot
                    await _update_with_retries()
        except Exception as e:
            print("eink: scheduler error:", e)
        await asyncio.sleep(20)
