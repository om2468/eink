"""Converts an image to the panel's format. See README.md for the layout."""

from PIL import Image


def encode_planes(image: Image.Image) -> bytes:
    """Returns the black/white plane followed by the red plane.

    Uses the same colour thresholds as the vendor's web app.
    """
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
    return bytes(bw + red)
