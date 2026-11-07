"""Encodes images for the panel and sends them over Bluetooth.

The protocol is documented in README.md. Only model 0x16 (400x300,
black/white/red) is supported.
"""

import asyncio

from bleak import BleakClient, BleakScanner
from PIL import Image

from . import config

COMMAND_CHAR = "62750002-d828-918d-fb46-b6c11c675aec"

CMD_INIT = 0x01
CMD_REFRESH = 0x05
CMD_WRITE_IMAGE = 0x30

FLAG_RED_PLANE = 0x01
FLAG_FIRST_CHUNK = 0x02
FLAG_RLE = 0x04

CONFIG_MODEL_INDEX = 7
DEFAULT_ACK_INTERVAL = 10
MAX_ACK_INTERVAL = 50
REPLY_TIMEOUT_SECONDS = 5
# The panel takes a while to redraw in three colours. The display keeps working
# after we disconnect only if we leave it time to finish.
REFRESH_WAIT_SECONDS = 30


class DisplayError(Exception):
    pass


def encode_planes(image: Image.Image) -> tuple[bytes, bytes]:
    """Returns (black/white plane, red plane), using the vendor app's thresholds."""
    width, height = image.size
    row_bytes = (width + 7) // 8
    bw = bytearray(row_bytes * height)
    red = bytearray(row_bytes * height)
    pixels = image.convert("RGB").load()
    for y in range(height):
        for x in range(width):
            r, g, b = pixels[x, y]
            index = y * row_bytes + x // 8
            mask = 1 << (7 - x % 8)
            if round(0.299 * r + 0.587 * g + 0.114 * b) >= 140:
                bw[index] |= mask
            if not (r > 160 and r > g and r > b):
                red[index] |= mask
    return bytes(bw), bytes(red)


def rle_chunks(data: bytes, max_chunk: int) -> list[bytes]:
    """RLE-encodes data into chunks of at most max_chunk bytes.

    Codes are never split across chunks, because the display decodes each chunk
    separately.
    """
    max_literal = min(max_chunk - 1, 128)
    codes: list[bytes] = []
    i = 0
    n = len(data)
    while i < n:
        run = 1
        while i + run < n and run < 130 and data[i + run] == data[i]:
            run += 1
        if run >= 3:
            codes.append(bytes((0x80 | (run - 3), data[i])))
            i += run
            continue
        start = i
        while i < n and i - start < max_literal:
            if i + 2 < n and data[i] == data[i + 1] == data[i + 2]:
                break
            i += 1
        codes.append(bytes((i - start - 1,)) + data[start:i])

    chunks: list[bytes] = []
    current = bytearray()
    for code in codes:
        if current and len(current) + len(code) > max_chunk:
            chunks.append(bytes(current))
            current = bytearray()
        current += code
    if current:
        chunks.append(bytes(current))
    return chunks


def plane_packets(plane: bytes, is_red: bool, max_chunk: int) -> list[bytes]:
    """Builds the write-image packets for one plane, using RLE if it's smaller."""
    compressed = rle_chunks(plane, max_chunk)
    use_rle = sum(map(len, compressed)) < len(plane)
    if use_rle:
        chunks = compressed
    else:
        chunks = [plane[i : i + max_chunk] for i in range(0, len(plane), max_chunk)]

    packets = []
    for index, chunk in enumerate(chunks):
        flags = FLAG_RED_PLANE if is_red else 0
        if index == 0:
            flags |= FLAG_FIRST_CHUNK
        if use_rle:
            flags |= FLAG_RLE
        packets.append(bytes((CMD_WRITE_IMAGE, flags)) + chunk)
    return packets


def parse_session_reply(text: str) -> tuple[int, bool, int]:
    """Parses 'mtu=<n> rle=1 intl=<n>' into (mtu, rle, ack interval)."""
    parts = text.split()
    mtu = int(parts[0].removeprefix("mtu="))
    rle = False
    interval = DEFAULT_ACK_INTERVAL
    for part in parts[1:]:
        if part.startswith("rle="):
            rle = part == "rle=1"
        elif part.startswith("intl="):
            interval = min(int(part.removeprefix("intl=")), MAX_ACK_INTERVAL)
    return mtu, rle, interval


async def send_image(image: Image.Image, wait_for_refresh: bool = True) -> None:
    if image.size != (config.WIDTH, config.HEIGHT):
        raise DisplayError(f"image is {image.size}, panel is {(config.WIDTH, config.HEIGHT)}")
    bw, red = encode_planes(image)

    device = await BleakScanner.find_device_by_name(config.DEVICE_NAME, timeout=20)
    if device is None:
        raise DisplayError(
            f"{config.DEVICE_NAME} not found. Disconnect any browser session, and check the battery."
        )

    notifications: asyncio.Queue[bytes] = asyncio.Queue()

    async with BleakClient(device, timeout=20) as client:
        await client.start_notify(COMMAND_CHAR, lambda _, data: notifications.put_nowait(bytes(data)))

        # Turning on notifications makes the display send its config first.
        # Check it's the panel this code was written for before changing anything.
        panel_config = await asyncio.wait_for(notifications.get(), REPLY_TIMEOUT_SECONDS)
        model = panel_config[CONFIG_MODEL_INDEX]
        if model != config.MODEL_ID:
            raise DisplayError(f"expected model 0x{config.MODEL_ID:02x}, display reports 0x{model:02x}")

        await client.write_gatt_char(COMMAND_CHAR, bytes((CMD_INIT,)), response=True)
        while True:
            text = (await asyncio.wait_for(notifications.get(), REPLY_TIMEOUT_SECONDS)).decode("utf-8", "replace")
            if text.startswith("err="):
                raise DisplayError(f"display replied {text}")
            if text.startswith("mtu="):
                break
        mtu, rle, ack_interval = parse_session_reply(text)
        if not rle:
            raise DisplayError(f"display doesn't report RLE support: {text!r}")
        await asyncio.sleep(0.2)

        max_chunk = min(mtu, client.mtu_size - 3) - 2
        packets = plane_packets(bw, False, max_chunk) + plane_packets(red, True, max_chunk)
        since_ack = 0
        for packet in packets:
            needs_ack = since_ack >= ack_interval
            await client.write_gatt_char(COMMAND_CHAR, packet, response=needs_ack)
            since_ack = 0 if needs_ack else since_ack + 1

        await asyncio.sleep(0.3)
        await client.write_gatt_char(COMMAND_CHAR, bytes((CMD_REFRESH,)), response=True)
        if wait_for_refresh:
            await asyncio.sleep(REFRESH_WAIT_SECONDS)
