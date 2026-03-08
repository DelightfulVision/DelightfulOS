#!/usr/bin/env python3
"""Raspberry Pi microphone streamer — captures USB mic audio and streams
to DelightfulOS server via WebSocket for VAD + transcription.

Architecture:
    USB Mic → Pi (arecord/pyaudio) → WebSocket → Server (VAD + Whisper)

The server's raw collar endpoint accepts PDM audio. This script sends
audio chunks as base64 in the `pdm_audio` field, which the server
processes through its VAD pipeline and transcription engine.

Usage:
    pip install websockets

    # Stream mic to server:
    python pi_mic.py --server ws://SERVER_IP:8000 --user alice

    # Specify audio device:
    python pi_mic.py --server ws://SERVER_IP:8000 --user alice --device plughw:2,0

    # Adjust chunk size (ms):
    python pi_mic.py --server ws://SERVER_IP:8000 --user alice --chunk-ms 200
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import logging
import struct
import subprocess
import sys
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("pi_mic")

try:
    import websockets
except ImportError:
    print("pip install websockets")
    sys.exit(1)


SAMPLE_RATE = 16000
CHANNELS = 1
SAMPLE_WIDTH = 2  # 16-bit = 2 bytes


def find_capture_device() -> str | None:
    """Auto-detect USB audio capture device via arecord -l."""
    try:
        out = subprocess.check_output(["arecord", "-l"], text=True, stderr=subprocess.STDOUT)
        for line in out.splitlines():
            if "card" in line and "USB" in line:
                # Extract card and device numbers
                parts = line.split(":")
                card = parts[0].strip().split()[-1]
                # Find device number
                for p in parts:
                    if "device" in p.lower():
                        dev = p.strip().split()[-1].rstrip(",")
                        return f"plughw:{card},{dev}"
        # Fallback: card 2 device 0 (common for USB mic on Pi)
        return "plughw:2,0"
    except Exception:
        return "plughw:2,0"


class MicCapture:
    """Captures audio from USB mic using arecord subprocess."""

    def __init__(self, device: str, sample_rate: int = SAMPLE_RATE, chunk_ms: int = 200):
        self.device = device
        self.sample_rate = sample_rate
        self.chunk_ms = chunk_ms
        self.chunk_bytes = int(sample_rate * SAMPLE_WIDTH * CHANNELS * chunk_ms / 1000)
        self.process: subprocess.Popen | None = None
        self.stats = {"chunks": 0, "bytes": 0, "rms_sum": 0.0}

    def start(self):
        """Start arecord subprocess streaming raw PCM to stdout."""
        cmd = [
            "arecord",
            "-D", self.device,
            "-f", "S16_LE",
            "-r", str(self.sample_rate),
            "-c", str(CHANNELS),
            "-t", "raw",
            "--buffer-size", str(self.sample_rate),  # 1 second buffer
            "-",
        ]
        self.process = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )
        log.info("Mic capture started: %s @ %d Hz, %d ms chunks", self.device, self.sample_rate, self.chunk_ms)

    def stop(self):
        if self.process:
            self.process.terminate()
            self.process.wait(timeout=2)
            self.process = None

    def read_chunk(self) -> bytes | None:
        """Read one audio chunk. Returns raw PCM bytes or None."""
        if not self.process or not self.process.stdout:
            return None
        try:
            data = self.process.stdout.read(self.chunk_bytes)
            if not data:
                return None
            self.stats["chunks"] += 1
            self.stats["bytes"] += len(data)
            return data
        except Exception:
            return None

    @staticmethod
    def compute_rms(pcm_bytes: bytes) -> float:
        """Compute RMS of 16-bit PCM audio."""
        n = len(pcm_bytes) // 2
        if n == 0:
            return 0.0
        samples = struct.unpack(f"<{n}h", pcm_bytes)
        rms = (sum(s * s for s in samples) / n) ** 0.5
        return rms / 32768.0  # normalize to 0-1


async def stream_loop(mic: MicCapture, server_url: str, user_id: str):
    """Main streaming loop: mic → WebSocket."""
    path = f"/collar/ws/{user_id}/raw"
    url = server_url.rstrip("/") + path

    while True:
        try:
            log.info("Connecting to %s", url)
            async with websockets.connect(url, ping_interval=20, ping_timeout=10) as ws:
                log.info("Connected. Streaming mic audio...")
                log.info("  Device: %s", mic.device)
                log.info("  User: %s", user_id)
                log.info("  Chunk: %d ms (%d bytes)", mic.chunk_ms, mic.chunk_bytes)

                last_stats = time.time()

                while True:
                    # Read audio chunk (blocking, but chunk_ms is short)
                    chunk = await asyncio.get_event_loop().run_in_executor(
                        None, mic.read_chunk
                    )
                    if chunk is None:
                        log.warning("Mic read failed — restarting capture")
                        mic.stop()
                        await asyncio.sleep(1)
                        mic.start()
                        continue

                    rms = MicCapture.compute_rms(chunk)
                    mic.stats["rms_sum"] += rms

                    # Send as raw audio frame (matches server's handle_raw_audio format)
                    frame = {
                        "type": "raw_audio",
                        "timestamp": time.time(),
                        "pdm_audio": base64.b64encode(chunk).decode("ascii"),
                        "pdm_sample_rate": mic.sample_rate,
                        "pdm_bit_depth": 16,
                    }
                    await ws.send(json.dumps(frame))

                    # Read server response (non-blocking)
                    try:
                        resp = await asyncio.wait_for(ws.recv(), timeout=0.01)
                        data = json.loads(resp)
                        if data.get("pdm_vad", {}).get("speech"):
                            log.info("Speech detected (RMS: %.4f)", rms)
                    except asyncio.TimeoutError:
                        pass
                    except Exception:
                        pass

                    # Stats every 10s
                    now = time.time()
                    if now - last_stats > 10:
                        last_stats = now
                        s = mic.stats
                        avg_rms = s["rms_sum"] / max(s["chunks"], 1)
                        log.info(
                            "Stats: %d chunks, %.1f KB, avg RMS: %.4f",
                            s["chunks"], s["bytes"] / 1024, avg_rms,
                        )

        except (ConnectionRefusedError, OSError) as e:
            log.warning("Server connection failed: %s — retrying in 3s", e)
            await asyncio.sleep(3)
        except websockets.exceptions.ConnectionClosed:
            log.warning("WebSocket closed — reconnecting in 1s")
            await asyncio.sleep(1)
        except Exception:
            log.exception("Stream error — retrying in 3s")
            await asyncio.sleep(3)


def main():
    parser = argparse.ArgumentParser(
        description="DelightfulOS Pi Mic Streamer (USB mic → server WebSocket)")
    parser.add_argument("--server", default="ws://localhost:8000",
                        help="Server WebSocket URL (default: ws://localhost:8000)")
    parser.add_argument("--user", default="alice",
                        help="User ID (default: alice)")
    parser.add_argument("--device", default=None,
                        help="ALSA capture device (auto-detect if not specified)")
    parser.add_argument("--chunk-ms", type=int, default=200,
                        help="Audio chunk size in ms (default: 200)")
    args = parser.parse_args()

    device = args.device or find_capture_device()
    if not device:
        log.error("No capture device found. Specify with --device plughw:2,0")
        sys.exit(1)

    mic = MicCapture(device, chunk_ms=args.chunk_ms)
    mic.start()

    log.info("")
    log.info("DelightfulOS Pi Mic Streamer")
    log.info("  Device: %s @ %d Hz", device, SAMPLE_RATE)
    log.info("  Server: %s", args.server)
    log.info("  User: %s", args.user)
    log.info("")

    try:
        asyncio.run(stream_loop(mic, args.server, args.user))
    except KeyboardInterrupt:
        log.info("Shutting down")
    finally:
        mic.stop()


if __name__ == "__main__":
    main()
