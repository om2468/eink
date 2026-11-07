import random

from PIL import Image

from dashboard.data import parse_headlines
from dashboard.display import (
    FLAG_FIRST_CHUNK,
    FLAG_RED_PLANE,
    FLAG_RLE,
    encode_planes,
    parse_session_reply,
    plane_packets,
    rle_chunks,
)


def rle_decode_chunk(chunk: bytes) -> bytes:
    """Mirrors the firmware: each chunk must decode by itself."""
    out = bytearray()
    i = 0
    while i < len(chunk):
        control = chunk[i]
        i += 1
        if control & 0x80:
            out += bytes((chunk[i],)) * ((control & 0x7F) + 3)
            i += 1
        else:
            length = control + 1
            assert i + length <= len(chunk), "code split across chunks"
            out += chunk[i : i + length]
            i += length
    return bytes(out)


def test_rle_round_trip_and_chunk_size():
    rng = random.Random(1)
    samples = [
        b"\xff" * 15000,
        bytes(rng.randrange(256) for _ in range(5000)),
        bytes(rng.choice((0, 255)) for _ in range(5000)),
        b"\xff" * 131 + b"\x00\x01\x01" + b"\x02" * 3,
        b"\x07",
    ]
    for data in samples:
        for max_chunk in (18, 242):
            chunks = rle_chunks(data, max_chunk)
            assert all(len(chunk) <= max_chunk for chunk in chunks)
            assert b"".join(rle_decode_chunk(chunk) for chunk in chunks) == data


def test_pixel_encoding():
    image = Image.new("RGB", (8, 2), (255, 255, 255))
    image.putpixel((0, 0), (0, 0, 0))
    image.putpixel((1, 0), (255, 0, 0))
    image.putpixel((7, 1), (255, 0, 0))
    bw, red = encode_planes(image)
    assert bw == bytes((0b00111111, 0b11111110))
    assert red == bytes((0b10111111, 0b11111110))


def test_packet_flags():
    packets = plane_packets(b"\xff" * 1000, True, 18)
    assert packets[0][0] == 0x30
    assert packets[0][1] == FLAG_RED_PLANE | FLAG_FIRST_CHUNK | FLAG_RLE
    assert all(not packet[1] & FLAG_FIRST_CHUNK for packet in packets[1:])

    incompressible = bytes(range(100))
    raw = plane_packets(incompressible, False, 18)
    assert raw[0][1] == FLAG_FIRST_CHUNK
    assert b"".join(packet[2:] for packet in raw) == incompressible


def test_session_reply():
    assert parse_session_reply("mtu=244 rle=1") == (244, True, 10)
    assert parse_session_reply("mtu=20 rle=1 intl=200") == (20, True, 50)
    assert parse_session_reply("mtu=20")[1] is False


def test_headlines_from_cdata_and_duplicates():
    feed = b"""<rss><channel><title>Feed</title>
    <item><title><![CDATA[First & story]]></title></item>
    <item><title>Second</title></item>
    <item><title>Second</title></item>
    </channel></rss>"""
    assert parse_headlines(feed) == ["First & story", "Second"]
