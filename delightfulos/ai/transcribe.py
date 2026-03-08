"""Audio transcription via Gemini multimodal input.

Takes raw PCM audio (16-bit, 16kHz from PDM mic), wraps in WAV,
sends to Gemini 2.5 Flash as input_audio for transcription.

Design:
  - Per-user AudioBuffer collects PCM while VAD says speech is active
  - On speech end (or max duration), flushes buffer to Gemini
  - Emits 'transcription' signal on the bus with the text
"""
from __future__ import annotations

import asyncio
import base64
import logging
import struct
import time
from dataclasses import dataclass, field

from delightfulos.os.types import Signal
from delightfulos.os.bus import bus

log = logging.getLogger("delightfulos.transcribe")

SYSTEM_PROMPT = (
    "You are a speech transcription engine for a wearable device. "
    "Output ONLY the transcribed text, nothing else. "
    "If no speech is detected, output exactly: [NO_SPEECH]. "
    "Never hallucinate or invent speech. Keep punctuation minimal."
)

MAX_BUFFER_SECONDS = 10.0
MIN_BUFFER_SECONDS = 0.5


def _pcm_to_wav(pcm: bytes, sample_rate: int = 16000, bit_depth: int = 16) -> bytes:
    """Wrap raw PCM bytes in a WAV header."""
    channels = 1
    bytes_per_sample = bit_depth // 8
    byte_rate = sample_rate * channels * bytes_per_sample
    block_align = channels * bytes_per_sample
    data_size = len(pcm)

    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF", 36 + data_size, b"WAVE",
        b"fmt ", 16, 1, channels,
        sample_rate, byte_rate, block_align, bit_depth,
        b"data", data_size,
    )
    return header + pcm


@dataclass
class AudioBuffer:
    """Per-user buffer that collects PDM PCM while speech is active."""

    user_id: str
    sample_rate: int = 16000
    bit_depth: int = 16

    _chunks: list[bytes] = field(default_factory=list, repr=False)
    _total_samples: int = 0
    _speech_active: bool = False
    _speech_start: float = 0.0
    _flush_task: asyncio.Task | None = field(default=None, repr=False)

    @property
    def duration(self) -> float:
        bytes_per_sample = self.bit_depth // 8
        return self._total_samples / self.sample_rate if self.sample_rate else 0.0

    @property
    def is_recording(self) -> bool:
        return self._speech_active

    def on_speech_start(self):
        if not self._speech_active:
            self._speech_active = True
            self._speech_start = time.time()
            log.debug("Audio buffer started for %s", self.user_id)

    def on_speech_end(self):
        self._speech_active = False

    def add_pcm(self, pcm_bytes: bytes):
        """Add a chunk of raw PCM audio to the buffer."""
        if not pcm_bytes:
            return
        self._chunks.append(pcm_bytes)
        bytes_per_sample = self.bit_depth // 8
        self._total_samples += len(pcm_bytes) // bytes_per_sample

        # Auto-flush if we hit max duration
        if self.duration >= MAX_BUFFER_SECONDS and self._speech_active:
            self._speech_active = False

    def flush(self) -> bytes | None:
        """Return accumulated WAV bytes and reset, or None if too short."""
        if not self._chunks or self.duration < MIN_BUFFER_SECONDS:
            self._chunks.clear()
            self._total_samples = 0
            return None

        pcm = b"".join(self._chunks)
        self._chunks.clear()
        self._total_samples = 0

        return _pcm_to_wav(pcm, self.sample_rate, self.bit_depth)

    def clear(self):
        self._chunks.clear()
        self._total_samples = 0
        self._speech_active = False


class TranscriptionEngine:
    """Manages per-user audio buffers and sends to Gemini for transcription."""

    def __init__(self):
        self._buffers: dict[str, AudioBuffer] = {}
        self._enabled = False
        self._pending: dict[str, asyncio.Task] = {}

    def get_buffer(self, user_id: str) -> AudioBuffer:
        if user_id not in self._buffers:
            self._buffers[user_id] = AudioBuffer(user_id=user_id)
        return self._buffers[user_id]

    def start(self):
        from delightfulos.ai.config import settings
        if not settings.prime_api_key:
            log.info("Transcription disabled (no PRIME_API_KEY)")
            return
        self._enabled = True
        log.info("Transcription engine started (model=%s)", settings.model_transcription)

    async def on_speech_signal(self, signal: Signal):
        """Called by the collar handler when speech state changes."""
        if not self._enabled:
            return

        buf = self.get_buffer(signal.source_user)

        if signal.signal_type in ("speaking", "speaking_confirmed"):
            buf.on_speech_start()
        elif signal.signal_type == "speech_ended":
            buf.on_speech_end()
            await self._maybe_flush(signal.source_user, signal.source_device)

    async def add_audio(self, user_id: str, device_id: str, pcm_bytes: bytes):
        """Add raw PCM audio from a collar. Called from collar handler."""
        if not self._enabled:
            return

        buf = self.get_buffer(user_id)
        buf.add_pcm(pcm_bytes)

        # If buffer hit max, flush it even if speech is ongoing
        if buf.duration >= MAX_BUFFER_SECONDS:
            await self._maybe_flush(user_id, device_id)

    async def _maybe_flush(self, user_id: str, device_id: str):
        """Flush buffer and send to Gemini if there's enough audio."""
        buf = self.get_buffer(user_id)
        wav_bytes = buf.flush()
        if wav_bytes is None:
            return

        # Don't stack up concurrent transcriptions for the same user
        existing = self._pending.get(user_id)
        if existing and not existing.done():
            return

        self._pending[user_id] = asyncio.create_task(
            self._transcribe(user_id, device_id, wav_bytes)
        )

    async def _transcribe(self, user_id: str, device_id: str, wav_bytes: bytes):
        """Send audio to Gemini and emit transcription signal."""
        from delightfulos.ai.config import settings
        from delightfulos.ai.prime import get_client

        audio_b64 = base64.b64encode(wav_bytes).decode()
        client = get_client()

        try:
            t0 = time.time()
            resp = await client.chat.completions.create(
                model=settings.model_transcription,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": [
                        {"type": "input_audio", "input_audio": {"data": audio_b64, "format": "wav"}},
                        {"type": "text", "text": "Transcribe:"},
                    ]},
                ],
                max_tokens=300,
                temperature=0.0,
            )
            text = resp.choices[0].message.content.strip()
            latency = time.time() - t0

            if not text or "[NO_SPEECH]" in text:
                log.debug("No speech in audio for %s (%.2fs latency)", user_id, latency)
                return

            log.info("Transcription for %s (%.2fs): %s", user_id, latency, text[:80])

            await bus.emit_signal(Signal(
                source_device=device_id,
                source_user=user_id,
                signal_type="transcription",
                confidence=1.0,
                value={"text": text, "latency": round(latency, 2)},
            ))

        except Exception as e:
            log.warning("Transcription failed for %s: %s", user_id, e)


# Singleton
transcriber = TranscriptionEngine()
