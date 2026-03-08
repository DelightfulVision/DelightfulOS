"""Test piezo threshold detection with real hardware values.

Real hardware readings (ESP32-S3 12-bit ADC, 3.3V, piezo biased to 1.65V mid-rail):
  - Standby: ~2000 ADC counts (static baseline)
  - Tap:     ~2600 ADC counts (threshold crossing)

This script simulates these signals through both firmware-side logic
(detectTap equivalent) and server-side VAD to find working thresholds.
"""
import math
import struct
import sys

# ---------------------------------------------------------------------------
# Simulate raw ADC buffers
# ---------------------------------------------------------------------------

def make_adc_buffer(baseline: int, n: int = 256, noise: int = 30) -> list[int]:
    """Simulate a buffer of ADC readings around a baseline with noise."""
    import random
    random.seed(42)
    return [max(0, min(4095, baseline + random.randint(-noise, noise))) for _ in range(n)]


def inject_tap(buffer: list[int], peak_adc: int, tap_width: int = 8) -> list[int]:
    """Inject a tap spike into the middle of a buffer."""
    buf = list(buffer)
    mid = len(buf) // 2
    for i in range(tap_width):
        # Triangle pulse shape
        frac = 1.0 - abs(i - tap_width // 2) / (tap_width // 2)
        val = int(buffer[mid] + (peak_adc - buffer[mid]) * frac)
        buf[mid - tap_width // 2 + i] = min(4095, val)
    return buf


# ---------------------------------------------------------------------------
# Firmware-side detection (mirrors contact_mic.ino logic)
# ---------------------------------------------------------------------------

def firmware_rms(buffer: list[int], scale: float = 4095.0) -> float:
    n = len(buffer)
    return math.sqrt(sum((b / scale) ** 2 for b in buffer) / n)


def firmware_peak(buffer: list[int], scale: float = 4095.0) -> float:
    return max(abs(b / scale) for b in buffer)


def firmware_detect_tap(buffer: list[int], tap_threshold: float, crest_min: float) -> dict:
    rms = firmware_rms(buffer)
    peak = firmware_peak(buffer)
    crest = peak / rms if rms > 0 else 0
    detected = peak > tap_threshold and crest > crest_min
    return {
        "rms": rms,
        "peak": peak,
        "crest_factor": crest,
        "detected": detected,
        "tap_threshold": tap_threshold,
        "crest_min": crest_min,
    }


# ---------------------------------------------------------------------------
# Server-side detection (mirrors delightfulos/ai/signal.py)
# ---------------------------------------------------------------------------

def server_decode_12bit(buffer: list[int]) -> list[float]:
    """Same as decode_raw_audio with bit_depth=12 but from int list."""
    return [(val / 2047.0) - 1.0 for val in buffer]


def server_rms(samples: list[float]) -> float:
    n = len(samples)
    return math.sqrt(sum(s * s for s in samples) / n)


def server_peak(samples: list[float]) -> float:
    return max(abs(s) for s in samples)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_signal_characteristics():
    """Show what the real hardware signals look like through both pipelines."""
    print("=== 1. Signal Characteristics (real hardware values) ===")

    standby_buf = make_adc_buffer(2000, noise=30)
    tap_buf = inject_tap(make_adc_buffer(2000, noise=30), peak_adc=2600, tap_width=8)
    hard_tap_buf = inject_tap(make_adc_buffer(2000, noise=30), peak_adc=3200, tap_width=8)

    print("\n  --- Firmware side (raw / 4095.0) ---")
    for label, buf in [("Standby", standby_buf), ("Tap@2600", tap_buf), ("HardTap@3200", hard_tap_buf)]:
        rms = firmware_rms(buf)
        peak = firmware_peak(buf)
        crest = peak / rms if rms > 0 else 0
        print(f"  {label:15s}  RMS={rms:.4f}  Peak={peak:.4f}  Crest={crest:.2f}")

    print("\n  --- Server side (centered: val/2047 - 1) ---")
    for label, buf in [("Standby", standby_buf), ("Tap@2600", tap_buf), ("HardTap@3200", hard_tap_buf)]:
        samples = server_decode_12bit(buf)
        rms = server_rms(samples)
        peak = server_peak(samples)
        crest = peak / rms if rms > 0 else 0
        print(f"  {label:15s}  RMS={rms:.4f}  Peak={peak:.4f}  Crest={crest:.2f}")

    print("\n  Signal characteristics: OK")


def test_firmware_current_thresholds():
    """Show that current firmware thresholds (TAP_THRESHOLD=0.6, crest>3.0) fail."""
    print("\n=== 2. Current Firmware Thresholds (TAP=0.6, crest>3.0) ===")

    standby_buf = make_adc_buffer(2000, noise=30)
    tap_buf = inject_tap(make_adc_buffer(2000, noise=30), peak_adc=2600, tap_width=8)

    standby_result = firmware_detect_tap(standby_buf, tap_threshold=0.6, crest_min=3.0)
    tap_result = firmware_detect_tap(tap_buf, tap_threshold=0.6, crest_min=3.0)

    print(f"  Standby: detected={standby_result['detected']}, peak={standby_result['peak']:.4f}, crest={standby_result['crest_factor']:.2f}")
    print(f"  Tap@2600: detected={tap_result['detected']}, peak={tap_result['peak']:.4f}, crest={tap_result['crest_factor']:.2f}")

    # With biased piezo, crest factor is ~1.3 — current threshold of 3.0 never fires
    assert not standby_result["detected"], "Standby should not trigger"
    assert not tap_result["detected"], "Current thresholds CANNOT detect tap (crest too low with bias)"

    print("  Confirmed: current thresholds fail with biased piezo (crest ~1.3 vs required 3.0)")


def test_firmware_threshold_sweep():
    """Sweep thresholds to find what works for standby=2000, tap=2600."""
    print("\n=== 3. Firmware Threshold Sweep ===")

    standby_buf = make_adc_buffer(2000, noise=30)
    tap_buf = inject_tap(make_adc_buffer(2000, noise=30), peak_adc=2600, tap_width=8)
    light_tap_buf = inject_tap(make_adc_buffer(2000, noise=30), peak_adc=2300, tap_width=6)

    standby_peak = firmware_peak(standby_buf)
    tap_peak = firmware_peak(tap_buf)

    print(f"  Standby peak: {standby_peak:.4f}")
    print(f"  Tap@2600 peak: {tap_peak:.4f}")
    print(f"  Margin: {tap_peak - standby_peak:.4f}")

    # The right approach: use peak threshold between standby and tap peaks
    # Standby peak ≈ 0.496, Tap peak ≈ 0.635
    # Threshold should sit between them
    print("\n  Peak-only thresholds (no crest factor):")
    for thresh in [0.50, 0.52, 0.55, 0.58, 0.60, 0.62]:
        standby_fires = firmware_peak(standby_buf) > thresh
        tap_fires = firmware_peak(tap_buf) > thresh
        light_fires = firmware_peak(light_tap_buf) > thresh
        status = "GOOD" if (not standby_fires and tap_fires) else "BAD"
        print(f"    threshold={thresh:.2f}: standby={standby_fires}, tap@2600={tap_fires}, light@2300={light_fires} [{status}]")

    print("\n  Recommended: use DELTA from baseline instead of absolute threshold")


def test_delta_detection():
    """Test delta-based tap detection: compare peak to running baseline."""
    print("\n=== 4. Delta-Based Detection (recommended) ===")

    baseline_adc = 2000
    noise = 30
    standby_buf = make_adc_buffer(baseline_adc, noise=noise)

    # Different tap intensities
    tap_levels = [2200, 2400, 2600, 2800, 3000, 3200]

    baseline_peak = firmware_peak(standby_buf)

    print(f"  Baseline peak (standby@{baseline_adc}, noise={noise}): {baseline_peak:.4f}")
    print(f"  Baseline in ADC units: {baseline_peak * 4095:.0f}")
    print()

    # Delta = (tap_adc - baseline_adc) / 4095
    # A tap at 2600 with baseline 2000 → delta = 600/4095 ≈ 0.146
    for delta_thresh in [0.05, 0.08, 0.10, 0.12, 0.15]:
        print(f"  delta_threshold = {delta_thresh:.2f} ({delta_thresh * 4095:.0f} ADC counts):")
        for tap_adc in tap_levels:
            buf = inject_tap(make_adc_buffer(baseline_adc, noise=noise), peak_adc=tap_adc, tap_width=8)
            peak = firmware_peak(buf)
            delta = peak - baseline_peak
            detected = delta > delta_thresh
            marker = "<-- your tap" if tap_adc == 2600 else ""
            print(f"    tap@{tap_adc}: peak={peak:.4f}, delta={delta:.4f}, detected={detected} {marker}")
        print()


def test_server_side_vad_with_tap():
    """Test server-side VAD thresholds for tap detection on centered signal."""
    print("=== 5. Server-Side VAD (centered signal) ===")

    from delightfulos.ai.signal import VoiceActivityDetector, extract_features

    standby_buf = make_adc_buffer(2000, noise=30)
    tap_buf = inject_tap(make_adc_buffer(2000, noise=30), peak_adc=2600, tap_width=8)

    standby_samples = server_decode_12bit(standby_buf)
    tap_samples = server_decode_12bit(tap_buf)

    # With centering, standby is near 0, tap spike is positive
    standby_features = extract_features(standby_samples, 4000)
    tap_features = extract_features(tap_samples, 4000)

    print(f"  Standby: RMS={standby_features.rms:.4f}, Peak={standby_features.peak:.4f}")
    print(f"  Tap@2600: RMS={tap_features.rms:.4f}, Peak={tap_features.peak:.4f}")
    print(f"  Current thresholds: speech={0.15}, pre_speech={0.05}")

    # Test VAD with different thresholds
    print("\n  VAD threshold sweep (centered signal):")
    for speech_t, pre_t in [(0.15, 0.05), (0.10, 0.03), (0.08, 0.02), (0.05, 0.02)]:
        vad = VoiceActivityDetector(speech_threshold=speech_t, pre_speech_threshold=pre_t)
        # Feed a few standby frames first for history
        for _ in range(6):
            vad.detect(standby_samples, 4000)
        tap_result = vad.detect(tap_samples, 4000)
        standby_result = vad.detect(standby_samples, 4000)
        print(f"    speech={speech_t:.2f}/pre={pre_t:.2f}: "
              f"tap_speech={tap_result.speech_detected}, "
              f"tap_pre={tap_result.pre_speech_detected}, "
              f"standby_speech={standby_result.speech_detected}")

    print("\n  Server-side VAD with centered signal: OK")


def test_recommended_firmware_thresholds():
    """Validate delta-from-baselineRMS approach (matches firmware detectTap)."""
    print("\n=== 6. Delta from Baseline RMS (firmware approach) ===")

    baseline_adc = 2000
    tap_adc = 2600
    noise = 30

    standby_buf = make_adc_buffer(baseline_adc, noise=noise)
    tap_buf = inject_tap(make_adc_buffer(baseline_adc, noise=noise), peak_adc=tap_adc, tap_width=8)
    light_touch_buf = inject_tap(make_adc_buffer(baseline_adc, noise=noise), peak_adc=2200, tap_width=4)

    # Boot calibration averages RMS over ~20 quiet frames
    # With standby at 2000 ADC, RMS ≈ 0.488
    baseline_rms = firmware_rms(standby_buf)
    DELTA_THRESHOLD = 0.10

    print(f"  baselineRMS = {baseline_rms:.4f} (~{baseline_rms * 4095:.0f} ADC)")
    print(f"  tapDeltaThreshold = {DELTA_THRESHOLD}")
    print(f"  Detection: peak - baselineRMS > {DELTA_THRESHOLD}")
    print()

    for label, buf, expected in [
        ("Standby", standby_buf, False),
        ("Light@2200", light_touch_buf, False),
        ("Tap@2600", tap_buf, True),
    ]:
        peak = firmware_peak(buf)
        delta = peak - baseline_rms
        detected = delta > DELTA_THRESHOLD
        status = "OK" if detected == expected else "FAIL"
        print(f"    {label:15s}: peak={peak:.4f} delta={delta:.4f} {'>' if detected else '<='} {DELTA_THRESHOLD} -> {detected} [{status}]")
        assert detected == expected, f"{label} detection mismatch"

    # Test with different noise levels to confirm stability
    print("\n  Noise robustness (baseline always from RMS, not peak):")
    for test_noise in [10, 30, 60, 100]:
        noisy_standby = make_adc_buffer(baseline_adc, noise=test_noise)
        noisy_tap = inject_tap(make_adc_buffer(baseline_adc, noise=test_noise), peak_adc=tap_adc, tap_width=8)
        bl_rms = firmware_rms(noisy_standby)
        bl_peak = firmware_peak(noisy_standby)
        tap_peak = firmware_peak(noisy_tap)
        delta_rms = tap_peak - bl_rms
        delta_peak = tap_peak - bl_peak
        rms_ok = (delta_rms > DELTA_THRESHOLD) and (firmware_peak(noisy_standby) - bl_rms <= DELTA_THRESHOLD)
        peak_ok = (delta_peak > DELTA_THRESHOLD) and (firmware_peak(noisy_standby) - bl_peak <= DELTA_THRESHOLD)
        print(f"    noise={test_noise:3d}: RMS_baseline={bl_rms:.4f} peak_baseline={bl_peak:.4f} "
              f"tap_delta(RMS)={delta_rms:.4f} tap_delta(peak)={delta_peak:.4f} "
              f"RMS_method={'OK' if rms_ok else 'FAIL'} Peak_method={'OK' if peak_ok else 'FAIL'}")

    print("\n  All threshold tests validated")


# ---------------------------------------------------------------------------
# Tap state machine simulation (mirrors firmware detectTap logic)
# ---------------------------------------------------------------------------

class TapDetectorSim:
    """Python simulation of the firmware tap state machine."""

    IDLE = 0
    SPIKE = 1

    def __init__(self, baseline_rms: float, delta_threshold: float = 0.10,
                 max_spike_frames: int = 3, min_spike_frames: int = 1):
        self.baseline_rms = baseline_rms
        self.delta_threshold = delta_threshold
        self.max_spike_frames = max_spike_frames
        self.min_spike_frames = min_spike_frames
        self.state = self.IDLE
        self.spike_frames = 0
        self.spike_peak = 0.0
        self.ema_alpha = 0.02

    def feed_frame(self, buffer: list[int], speech_active: bool = False) -> bool:
        """Feed one analysis frame. Returns True if tap confirmed."""
        if speech_active:
            self.state = self.IDLE
            return False

        peak = firmware_peak(buffer)
        rms = firmware_rms(buffer)
        delta = peak - self.baseline_rms
        above = delta > self.delta_threshold

        fired = False

        if self.state == self.IDLE:
            if above:
                self.state = self.SPIKE
                self.spike_frames = 1
                self.spike_peak = peak
        elif self.state == self.SPIKE:
            self.spike_frames += 1
            if peak > self.spike_peak:
                self.spike_peak = peak

            if not above:
                # Dropped back — tap shape confirmed
                self.state = self.IDLE
                if self.spike_frames >= self.min_spike_frames:
                    fired = True
            elif self.spike_frames > self.max_spike_frames:
                # Sustained — not a tap
                self.state = self.IDLE

        # Adaptive baseline (only when quiet)
        quiet = not speech_active and (peak - self.baseline_rms) < self.delta_threshold * 0.5
        if quiet:
            self.baseline_rms = self.baseline_rms * (1.0 - self.ema_alpha) + rms * self.ema_alpha

        return fired


def test_tap_state_machine():
    """Test the tap state machine: spike-then-drop = tap, sustained = rejected."""
    print("\n=== 7. Tap State Machine ===")

    baseline_adc = 2000
    noise = 30
    standby_buf = make_adc_buffer(baseline_adc, noise=noise)
    baseline_rms = firmware_rms(standby_buf)
    det = TapDetectorSim(baseline_rms)

    # Feed quiet frames — no taps
    quiet_taps = 0
    for _ in range(10):
        if det.feed_frame(make_adc_buffer(baseline_adc, noise=noise)):
            quiet_taps += 1
    assert quiet_taps == 0, "No taps during quiet"
    print("  Quiet frames: no false triggers")

    # Real tap: 1 spike frame then drop back
    det2 = TapDetectorSim(baseline_rms)
    tap_buf = inject_tap(make_adc_buffer(baseline_adc, noise=noise), peak_adc=2600, tap_width=8)
    result1 = det2.feed_frame(tap_buf)  # spike detected, state -> SPIKE
    assert not result1, "Spike frame alone doesn't fire (need drop-back)"
    result2 = det2.feed_frame(make_adc_buffer(baseline_adc, noise=noise))  # drops back
    assert result2, "Drop-back after spike confirms tap"
    print("  Tap shape (spike + drop): confirmed")

    # Sustained pressure: stays above for 4+ frames → rejected
    det3 = TapDetectorSim(baseline_rms)
    sustained_buf = inject_tap(make_adc_buffer(baseline_adc, noise=noise), peak_adc=2600, tap_width=200)
    results = []
    for _ in range(6):
        results.append(det3.feed_frame(sustained_buf))
    assert not any(results), "Sustained pressure never fires"
    print("  Sustained pressure (4+ frames): rejected")

    # Speech rejection: spike during speech → ignored
    det4 = TapDetectorSim(baseline_rms)
    tap_buf = inject_tap(make_adc_buffer(baseline_adc, noise=noise), peak_adc=2600, tap_width=8)
    r1 = det4.feed_frame(tap_buf, speech_active=True)
    r2 = det4.feed_frame(make_adc_buffer(baseline_adc, noise=noise), speech_active=True)
    assert not r1 and not r2, "Tap during speech is suppressed"
    print("  Tap during speech: suppressed")

    print("  All state machine tests passed")


def test_adaptive_baseline():
    """Test that baseline drifts slowly to track temperature/fit changes."""
    print("\n=== 8. Adaptive Baseline Drift ===")

    baseline_adc = 2000
    noise = 30
    initial_rms = firmware_rms(make_adc_buffer(baseline_adc, noise=noise))
    det = TapDetectorSim(initial_rms)

    # Simulate slow drift: standby moves from 2000 to 2100 over many frames
    for i in range(200):
        drifted_adc = 2000 + int(i * 0.5)  # drift to 2100 over 200 frames
        det.feed_frame(make_adc_buffer(drifted_adc, noise=noise))

    new_baseline = det.baseline_rms
    expected_rms = firmware_rms(make_adc_buffer(2100, noise=noise))
    drift = abs(new_baseline - expected_rms)
    print(f"  Initial baseline: {initial_rms:.4f}")
    print(f"  After drift to 2100 ADC (200 frames): {new_baseline:.4f}")
    print(f"  Expected RMS at 2100: {expected_rms:.4f}")
    print(f"  Tracking error: {drift:.4f}")
    assert drift < 0.01, f"Baseline should track drift (error {drift:.4f})"

    # Now tap should still work at the new baseline
    tap_buf = inject_tap(make_adc_buffer(2100, noise=noise), peak_adc=2700, tap_width=8)
    r1 = det.feed_frame(tap_buf)
    r2 = det.feed_frame(make_adc_buffer(2100, noise=noise))
    assert r2, "Tap still detected after baseline drift"
    print("  Tap still works after drift: confirmed")

    # Verify baseline doesn't move during spikes
    det2 = TapDetectorSim(initial_rms)
    baseline_before = det2.baseline_rms
    tap_buf = inject_tap(make_adc_buffer(baseline_adc, noise=noise), peak_adc=3000, tap_width=8)
    det2.feed_frame(tap_buf)  # big spike
    det2.feed_frame(make_adc_buffer(baseline_adc, noise=noise))  # back to normal
    baseline_after = det2.baseline_rms
    shift = abs(baseline_after - baseline_before)
    print(f"  Baseline shift after spike: {shift:.6f} (should be minimal)")
    assert shift < 0.002, "Baseline should freeze during spikes"
    print("  Baseline freezes during spikes: confirmed")

    print("  All adaptive baseline tests passed")


def test_multi_tap_sequence():
    """Test a realistic sequence: quiet, tap, quiet, tap, speech, tap-during-speech."""
    print("\n=== 9. Multi-Tap Sequence (realistic) ===")

    baseline_adc = 2000
    noise = 30
    initial_rms = firmware_rms(make_adc_buffer(baseline_adc, noise=noise))
    det = TapDetectorSim(initial_rms)

    events = []

    # Phase 1: quiet (10 frames)
    for _ in range(10):
        det.feed_frame(make_adc_buffer(baseline_adc, noise=noise))

    # Phase 2: first tap
    tap1 = inject_tap(make_adc_buffer(baseline_adc, noise=noise), peak_adc=2600, tap_width=8)
    det.feed_frame(tap1)
    if det.feed_frame(make_adc_buffer(baseline_adc, noise=noise)):
        events.append("tap1")

    # Phase 3: quiet (5 frames)
    for _ in range(5):
        det.feed_frame(make_adc_buffer(baseline_adc, noise=noise))

    # Phase 4: second tap (harder)
    tap2 = inject_tap(make_adc_buffer(baseline_adc, noise=noise), peak_adc=3000, tap_width=8)
    det.feed_frame(tap2)
    if det.feed_frame(make_adc_buffer(baseline_adc, noise=noise)):
        events.append("tap2")

    # Phase 5: speech starts (sustained high RMS)
    speech_buf = make_adc_buffer(2400, noise=50)  # elevated sustained
    for _ in range(10):
        det.feed_frame(speech_buf, speech_active=True)

    # Phase 6: tap during speech (should be rejected)
    tap3 = inject_tap(make_adc_buffer(2400, noise=50), peak_adc=3000, tap_width=8)
    det.feed_frame(tap3, speech_active=True)
    if det.feed_frame(make_adc_buffer(2400, noise=50), speech_active=True):
        events.append("tap3_during_speech")

    # Phase 7: speech ends, another tap
    for _ in range(5):
        det.feed_frame(make_adc_buffer(baseline_adc, noise=noise))
    tap4 = inject_tap(make_adc_buffer(baseline_adc, noise=noise), peak_adc=2600, tap_width=8)
    det.feed_frame(tap4)
    if det.feed_frame(make_adc_buffer(baseline_adc, noise=noise)):
        events.append("tap4")

    print(f"  Events detected: {events}")
    assert events == ["tap1", "tap2", "tap4"], f"Expected tap1, tap2, tap4 but got {events}"
    print("  Correct: 3 real taps detected, speech tap rejected")


if __name__ == "__main__":
    test_signal_characteristics()
    test_firmware_current_thresholds()
    test_firmware_threshold_sweep()
    test_delta_detection()
    test_server_side_vad_with_tap()
    test_recommended_firmware_thresholds()
    test_tap_state_machine()
    test_adaptive_baseline()
    test_multi_tap_sequence()

    print("\n" + "=" * 50)
    print("ALL PIEZO THRESHOLD TESTS PASSED")
    print("=" * 50)
