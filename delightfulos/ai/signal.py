"""Signal processing for contact microphone data.

Handles raw piezo ADC streams from ESP32 and produces voice activity
and pre-speech detections.
"""
import math
import struct
from dataclasses import dataclass, field

from delightfulos.ai.config import settings


@dataclass
class SignalFeatures:
    rms: float = 0.0
    zcr: float = 0.0
    spectral_centroid: float = 0.0
    peak: float = 0.0
    crest_factor: float = 0.0


@dataclass
class VoiceActivityResult:
    speech_detected: bool = False
    pre_speech_detected: bool = False
    confidence: float = 0.0
    features: SignalFeatures = field(default_factory=SignalFeatures)


class VoiceActivityDetector:
    """Per-user VAD with sliding window state."""

    def __init__(
        self,
        speech_threshold: float = settings.speech_threshold,
        pre_speech_threshold: float = settings.pre_speech_threshold,
        history_size: int = 50,
    ):
        self.speech_threshold = speech_threshold
        self.pre_speech_threshold = pre_speech_threshold
        self._history: list[float] = []
        self._max_history = history_size

    def detect(self, samples: list[float], sample_rate: int = settings.piezo_sample_rate) -> VoiceActivityResult:
        features = extract_features(samples, sample_rate)

        self._history.append(features.rms)
        if len(self._history) > self._max_history:
            self._history.pop(0)

        speech_detected = features.rms >= self.speech_threshold
        pre_speech_detected = False
        confidence = 0.0

        if not speech_detected and features.rms > self.pre_speech_threshold:
            if len(self._history) >= 5:
                recent = sum(self._history[-3:]) / 3
                older = sum(self._history[-5:-3]) / 2
                if recent > older * 1.3:
                    pre_speech_detected = True
                    confidence = min(1.0, features.rms / self.speech_threshold)
                    if 0.15 < features.zcr < 0.5:
                        confidence = min(1.0, confidence * 1.3)

        if speech_detected:
            confidence = min(1.0, features.rms / self.speech_threshold)

        return VoiceActivityResult(
            speech_detected=speech_detected,
            pre_speech_detected=pre_speech_detected,
            confidence=confidence,
            features=features,
        )


def extract_features(samples: list[float], sample_rate: int = 4000) -> SignalFeatures:
    n = len(samples)
    if n == 0:
        return SignalFeatures()

    rms = math.sqrt(sum(s * s for s in samples) / n)
    crossings = sum(1 for i in range(1, n) if (samples[i] >= 0) != (samples[i - 1] >= 0))
    zcr = crossings / n
    peak = max(abs(s) for s in samples)
    crest_factor = peak / rms if rms > 0 else 0

    spectral_centroid = 0.0
    if rms > 0.001:
        mag_sum = 0.0
        weighted_sum = 0.0
        num_bins = min(n // 2, 64)
        for k in range(1, num_bins):
            re = sum(samples[i] * math.cos(2 * math.pi * k * i / n) for i in range(n))
            im = sum(samples[i] * math.sin(2 * math.pi * k * i / n) for i in range(n))
            mag = math.sqrt(re * re + im * im)
            freq = k * sample_rate / n
            mag_sum += mag
            weighted_sum += freq * mag
        if mag_sum > 0:
            spectral_centroid = weighted_sum / mag_sum

    return SignalFeatures(rms=rms, zcr=zcr, spectral_centroid=spectral_centroid, peak=peak, crest_factor=crest_factor)


def decode_raw_audio(raw_bytes: bytes, bit_depth: int = 12) -> list[float]:
    if bit_depth == 12:
        samples = []
        for i in range(0, len(raw_bytes) - 1, 2):
            val = struct.unpack_from("<H", raw_bytes, i)[0] & 0x0FFF
            samples.append((val / 2047.0) - 1.0)
        return samples
    elif bit_depth == 16:
        count = len(raw_bytes) // 2
        raw = struct.unpack(f"<{count}h", raw_bytes)
        return [s / 32767.0 for s in raw]
    return []
