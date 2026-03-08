"""Test signal processing pipeline with synthetic data.

No API keys needed — pure local computation.
Run: cd server && .venv/Scripts/python -m tests.test_signal
"""
import math

from delightfulos.ai.signal import extract_features, VoiceActivityDetector


def make_sine(freq, amplitude, duration_s, sample_rate=4000):
    n = int(duration_s * sample_rate)
    return [amplitude * math.sin(2 * math.pi * freq * i / sample_rate) for i in range(n)]


def test_features():
    print("=== Feature Extraction ===")
    silence = [0.001 * (i % 2 * 2 - 1) for i in range(256)]
    f = extract_features(silence)
    print(f"  Silence:     RMS={f.rms:.4f}  ZCR={f.zcr:.3f}")
    assert f.rms < 0.01, "Silence RMS should be near zero"

    pre_speech = make_sine(150, 0.08, 0.064)
    f = extract_features(pre_speech)
    print(f"  Pre-speech:  RMS={f.rms:.4f}  ZCR={f.zcr:.3f}  Centroid={f.spectral_centroid:.0f}Hz")
    assert 0.04 < f.rms < 0.1, "Pre-speech RMS should be moderate"

    speech = make_sine(180, 0.4, 0.064)
    f = extract_features(speech)
    print(f"  Speech:      RMS={f.rms:.4f}  ZCR={f.zcr:.3f}  Centroid={f.spectral_centroid:.0f}Hz")
    assert f.rms > 0.2, "Speech RMS should be high"


def test_vad_sequence():
    print("\n=== Voice Activity Detection Sequence ===")
    vad = VoiceActivityDetector()

    for _ in range(10):
        samples = [0.002 * (j % 2 * 2 - 1) for j in range(256)]
        result = vad.detect(samples)
    assert not result.speech_detected, "Silence should not trigger speech"
    assert not result.pre_speech_detected, "Silence should not trigger pre-speech"
    print("  Silence: OK (no detections)")

    detected_pre = False
    for i in range(5):
        amp = 0.03 + i * 0.02
        samples = make_sine(150, amp, 0.064)
        result = vad.detect(samples)
        if result.pre_speech_detected:
            detected_pre = True
            print(f"  Pre-speech detected at amplitude {amp:.2f} (conf={result.confidence:.2f})")
    assert detected_pre, "Should detect pre-speech during rising envelope"

    for _ in range(3):
        samples = make_sine(180, 0.4, 0.064)
        result = vad.detect(samples)
    assert result.speech_detected, "Should detect full speech"
    assert not result.pre_speech_detected, "Should not detect pre-speech during speech"
    print(f"  Speech: OK (conf={result.confidence:.2f})")


if __name__ == "__main__":
    test_features()
    test_vad_sequence()
    print("\nAll signal tests passed.")
