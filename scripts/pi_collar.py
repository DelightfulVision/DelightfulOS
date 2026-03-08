#!/usr/bin/env python3
"""Raspberry Pi collar bridge — reads XIAO ESP32-S3 over USB serial,
forwards to DelightfulOS server via WebSocket.

Architecture:
    XIAO (piezo + mic) --USB Serial--> Pi --WebSocket--> Server

The XIAO firmware outputs JSON frames prefixed with "JSON:" on Serial.
This script reads them and pipes them straight to the server's collar
WebSocket endpoint. Server responses (haptic commands etc.) are sent
back to the XIAO over serial.

Usage:
    pip install websockets pyserial

    # Auto-detect XIAO USB serial:
    python pi_collar.py --server ws://SERVER_IP:8000 --user alice

    # Explicit serial port:
    python pi_collar.py --server ws://SERVER_IP:8000 --user alice --port /dev/ttyACM0

    # Higher baud rate (match firmware Serial.begin):
    python pi_collar.py --server ws://SERVER_IP:8000 --user alice --baud 921600
"""
from __future__ import annotations

import argparse
import asyncio
import glob
import json
import logging
import sys
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("pi_bridge")

try:
    import websockets
except ImportError:
    print("pip install websockets")
    sys.exit(1)

try:
    import serial
    import serial.tools.list_ports
except ImportError:
    print("pip install pyserial")
    sys.exit(1)


def find_xiao_port() -> str | None:
    """Auto-detect XIAO ESP32-S3 USB serial port."""
    # Common XIAO/ESP32 USB identifiers
    for port in serial.tools.list_ports.comports():
        desc = (port.description or "").lower()
        vid = port.vid or 0
        # Seeed XIAO ESP32-S3: VID 0x303A (Espressif), or shows as "USB Serial"
        if vid == 0x303A or "esp32" in desc or "xiao" in desc:
            return port.device
    # Fallback: try common Linux/Mac paths
    for pattern in ["/dev/ttyACM*", "/dev/ttyUSB*", "/dev/cu.usbmodem*"]:
        ports = glob.glob(pattern)
        if ports:
            return ports[0]
    return None


class SerialReader:
    """Reads JSON frames from XIAO over USB serial.

    The XIAO outputs lines like:
        JSON:{"type":"events","timestamp":12.3,"events":[{"type":"touch","confidence":1.0}]}
        JSON:{"type":"heartbeat","timestamp":12.5,...}
        [TX] touch (1.00)     <-- debug output, ignored

    Only lines starting with "JSON:" are forwarded.
    """

    def __init__(self, port: str, baud: int = 115200):
        self.port = port
        self.baud = baud
        self.ser: serial.Serial | None = None
        self.stats = {"frames": 0, "errors": 0, "bytes": 0}

    def open(self):
        self.ser = serial.Serial(self.port, self.baud, timeout=0.05)
        # Flush any boot garbage
        time.sleep(0.1)
        self.ser.reset_input_buffer()
        log.info("Serial opened: %s @ %d baud", self.port, self.baud)

    def close(self):
        if self.ser:
            self.ser.close()
            self.ser = None

    def write(self, data: str):
        """Send data back to XIAO (e.g. haptic commands)."""
        if self.ser and self.ser.is_open:
            self.ser.write((data + "\n").encode())

    def read_json_frame(self) -> str | None:
        """Read one JSON frame. Returns JSON string or None."""
        if not self.ser or not self.ser.is_open:
            return None
        try:
            if self.ser.in_waiting == 0:
                return None
            line = self.ser.readline().decode("utf-8", errors="replace").strip()
            if not line:
                return None
            self.stats["bytes"] += len(line)
            if line.startswith("JSON:"):
                json_str = line[5:]
                # Quick validate
                json.loads(json_str)
                self.stats["frames"] += 1
                return json_str
            # Debug output from firmware — log at debug level
            if line and not line.startswith("==="):
                log.debug("XIAO: %s", line[:120])
        except json.JSONDecodeError:
            self.stats["errors"] += 1
            log.warning("Bad JSON from XIAO: %s", line[:100])
        except serial.SerialException:
            log.warning("Serial read error")
        return None


async def bridge_loop(reader: SerialReader, server_url: str, user_id: str):
    """Main bridge: serial → WebSocket, WebSocket → serial."""
    path = f"/collar/ws/{user_id}"
    url = server_url.rstrip("/") + path

    while True:
        try:
            log.info("Connecting to %s", url)
            async with websockets.connect(url, ping_interval=20, ping_timeout=10) as ws:
                log.info("Connected to server. Bridging serial <-> WebSocket")
                log.info("  Serial: %s", reader.port)
                log.info("  User: %s", user_id)
                log.info("  Endpoint: %s", path)

                last_stats_time = time.time()

                while True:
                    # Read all available serial frames
                    frames_sent = 0
                    for _ in range(50):  # drain up to 50 frames per tick
                        frame = reader.read_json_frame()
                        if frame is None:
                            break
                        await ws.send(frame)
                        frames_sent += 1

                    # Read server responses (non-blocking)
                    try:
                        resp = await asyncio.wait_for(ws.recv(), timeout=0.01)
                        # Forward haptic/config commands back to XIAO
                        try:
                            data = json.loads(resp)
                            action = data.get("action")
                            if action:
                                # Forward the whole JSON to XIAO
                                reader.write(resp)
                                log.info("→ XIAO: action=%s", action)
                        except (json.JSONDecodeError, KeyError):
                            pass
                    except asyncio.TimeoutError:
                        pass

                    # Print stats every 10s
                    now = time.time()
                    if now - last_stats_time > 10:
                        last_stats_time = now
                        s = reader.stats
                        log.info("Stats: %d frames, %d errors, %.1f KB",
                                 s["frames"], s["errors"], s["bytes"] / 1024)

                    await asyncio.sleep(0.005)  # 5ms tick — 200 Hz polling

        except (ConnectionRefusedError, OSError) as e:
            log.warning("Server connection failed: %s — retrying in 3s", e)
            await asyncio.sleep(3)
        except websockets.exceptions.ConnectionClosed:
            log.warning("WebSocket closed — reconnecting in 1s")
            await asyncio.sleep(1)
        except Exception:
            log.exception("Bridge error — retrying in 3s")
            await asyncio.sleep(3)


def main():
    parser = argparse.ArgumentParser(
        description="DelightfulOS Pi Collar Bridge (XIAO serial → server WebSocket)")
    parser.add_argument("--server", default="ws://localhost:8000",
                        help="Server WebSocket URL (default: ws://localhost:8000)")
    parser.add_argument("--user", default="alice",
                        help="User ID (default: alice)")
    parser.add_argument("--port", default=None,
                        help="Serial port (auto-detect if not specified)")
    parser.add_argument("--baud", type=int, default=115200,
                        help="Serial baud rate (default: 115200)")
    args = parser.parse_args()

    # Find serial port
    port = args.port or find_xiao_port()
    if not port:
        log.error("No XIAO serial port found. Specify with --port /dev/ttyACM0")
        log.error("Available ports:")
        for p in serial.tools.list_ports.comports():
            log.error("  %s — %s (VID:%s PID:%s)",
                      p.device, p.description, hex(p.vid or 0), hex(p.pid or 0))
        sys.exit(1)

    reader = SerialReader(port, args.baud)
    reader.open()

    log.info("")
    log.info("DelightfulOS Pi Collar Bridge")
    log.info("  XIAO: %s @ %d baud", port, args.baud)
    log.info("  Server: %s", args.server)
    log.info("  User: %s", args.user)
    log.info("")

    try:
        asyncio.run(bridge_loop(reader, args.server, args.user))
    except KeyboardInterrupt:
        log.info("Shutting down")
    finally:
        reader.close()


if __name__ == "__main__":
    main()
