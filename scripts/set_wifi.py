"""Sends the Wi-Fi details in firmware/src/secrets.h to the ESP32 over USB.

    .venv-fw/bin/python scripts/set_wifi.py /dev/cu.usbmodemXXXX

The board stores them. The password is never printed.
"""

import re
import sys
import time
from pathlib import Path

import serial

SECRETS = Path(__file__).resolve().parent.parent / "firmware" / "src" / "secrets.h"


def read_define(text: str, name: str) -> str:
    match = re.search(rf'#define\s+{name}\s+"(.*)"', text)
    if not match:
        sys.exit(f"{name} not found in {SECRETS}")
    return match.group(1)


def main() -> None:
    text = SECRETS.read_text()
    ssid = read_define(text, "WIFI_SSID")
    password = read_define(text, "WIFI_PASSWORD")

    with serial.Serial(sys.argv[1], 115200, timeout=1) as port:
        port.dtr = False
        port.rts = False
        time.sleep(1)
        port.reset_input_buffer()
        port.write(f"WIFI {ssid}\t{password}\n".encode())
        deadline = time.time() + 8
        while time.time() < deadline:
            if b"Wi-Fi details saved" in port.readline():
                print("Saved on the board")
                return
    sys.exit("The board didn't confirm. Is the firmware flashed?")


if __name__ == "__main__":
    main()
