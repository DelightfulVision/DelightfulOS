"""Collar device handler — manages WebSocket connections from ESP32-S3.

Modes:
  - Event mode: ESP32 sends pre-processed events as JSON
  - Raw mode: ESP32 streams piezo + PDM audio, server does VAD

Also handles:
  - Heartbeat messages (device health monitoring)
  - Calibration results (auto-threshold updates)
"""
from __future__ import annotations

import base64
import json
import logging
import time

from fastapi import WebSocket, WebSocketDisconnect

from delightfulos.os.types import Signal, DeviceInfo, DeviceType, Capability
from delightfulos.os.bus import bus
from delightfulos.os.registry import registry
from delightfulos.os.state import estimator
from delightfulos.ai.signal import VoiceActivityDetector, decode_raw_audio
from delightfulos.ai.transcribe import transcriber

log = logging.getLogger("delightfulos.collar")


COLLAR_CAPABILITIES = [
    Capability.SENSE_VIBRATION,
    Capability.SENSE_AUDIO,
    Capability.OUTPUT_HAPTIC,
]


async def _process_heartbeat(data: dict, did: str, user_id: str):
    """Update registry metadata from device heartbeat."""
    device = registry.get(did)
    if device:
        device.last_seen = time.time()
        device.metadata["wifi_rssi"] = data.get("wifi_rssi")
        device.metadata["uptime_s"] = data.get("uptime_s")
        device.metadata["free_heap"] = data.get("free_heap")
        device.metadata["piezo_rms"] = data.get("piezo_rms")
        device.metadata["speech_active"] = data.get("speech_active")


async def _process_calibration(data: dict, did: str, user_id: str):
    """Log calibration results from device auto-calibration."""
    log.info(
        "Calibration for %s: baseline=%.4f pre=%.4f speech=%.4f",
        did,
        data.get("baseline", 0),
        data.get("pre_speech_threshold", 0),
        data.get("speech_threshold", 0),
    )
    device = registry.get(did)
    if device:
        device.metadata["calibration"] = {
            "baseline": data.get("baseline"),
            "pre_speech_threshold": data.get("pre_speech_threshold"),
            "speech_threshold": data.get("speech_threshold"),
            "calibrated_at": time.time(),
        }


async def handle_events(ws: WebSocket, user_id: str, device_id: str | None = None):
    """Event-mode: ESP32 sends pre-processed events as JSON."""
    await ws.accept()
    did = device_id or f"collar_{user_id}"

    registry.register(DeviceInfo(
        device_id=did,
        device_type=DeviceType.COLLAR,
        user_id=user_id,
        capabilities=list(COLLAR_CAPABILITIES),
        transport=ws,
    ))

    try:
        while True:
            raw_text = await ws.receive_text()
            try:
                data = json.loads(raw_text)
            except json.JSONDecodeError:
                log.warning("Malformed JSON from %s: %s", did, raw_text[:100])
                continue

            msg_type = data.get("type", "events")

            if msg_type == "heartbeat":
                await _process_heartbeat(data, did, user_id)
                continue

            if msg_type == "calibration":
                await _process_calibration(data, did, user_id)
                continue

            # Process events
            for event in data.get("events", []):
                event_type = event.get("type")
                if not event_type:
                    log.warning("Event missing 'type' from %s: %s", did, event)
                    continue
                await bus.emit_signal(Signal(
                    source_device=did,
                    source_user=user_id,
                    signal_type=event_type,
                    confidence=event.get("confidence", 1.0),
                    value=event.get("value", {}),
                    timestamp=data.get("timestamp", time.time()),
                ))

            state = estimator.get(user_id)
            await ws.send_text(json.dumps({"state": state.to_dict()}))

    except WebSocketDisconnect:
        log.info("Collar %s disconnected (user %s)", did, user_id)
    except Exception:
        log.exception("Unexpected error in collar event handler for %s", did)
    finally:
        registry.unregister(did)


async def handle_raw_audio(ws: WebSocket, user_id: str, device_id: str | None = None):
    """Raw mode: ESP32 streams base64 piezo + PDM audio, server does VAD."""
    await ws.accept()
    did = device_id or f"collar_raw_{user_id}"
    piezo_vad = VoiceActivityDetector()
    pdm_vad = VoiceActivityDetector(
        speech_threshold=0.10,
        pre_speech_threshold=0.03,
    )

    registry.register(DeviceInfo(
        device_id=did,
        device_type=DeviceType.COLLAR,
        user_id=user_id,
        capabilities=list(COLLAR_CAPABILITIES),
        transport=ws,
    ))

    try:
        while True:
            raw_text = await ws.receive_text()
            try:
                data = json.loads(raw_text)
            except json.JSONDecodeError:
                log.warning("Malformed JSON from %s: %s", did, raw_text[:100])
                continue

            msg_type = data.get("type", "raw_audio")

            if msg_type == "heartbeat":
                await _process_heartbeat(data, did, user_id)
                continue

            if msg_type == "calibration":
                await _process_calibration(data, did, user_id)
                continue

            # Piezo audio (primary: pre-speech + speech detection)
            piezo_result = None
            audio_b64 = data.get("audio", "")
            if audio_b64:
                audio_bytes = base64.b64decode(audio_b64)
                samples = decode_raw_audio(
                    audio_bytes,
                    bit_depth=data.get("piezo_bit_depth", data.get("bit_depth", 12)),
                )
                if samples:
                    piezo_result = piezo_vad.detect(
                        samples,
                        data.get("piezo_sample_rate", data.get("sample_rate", 4000)),
                    )

            # PDM mic audio (secondary: actual speech content, higher quality)
            pdm_result = None
            pdm_b64 = data.get("pdm_audio", "")
            pdm_bytes = b""
            if pdm_b64:
                pdm_bytes = base64.b64decode(pdm_b64)
                pdm_samples = decode_raw_audio(pdm_bytes, bit_depth=data.get("pdm_bit_depth", 16))
                if pdm_samples:
                    pdm_result = pdm_vad.detect(
                        pdm_samples,
                        data.get("pdm_sample_rate", 16000),
                    )

            # Emit signals from piezo (primary for pre-speech)
            if piezo_result:
                if piezo_result.pre_speech_detected:
                    await bus.emit_signal(Signal(
                        source_device=did, source_user=user_id,
                        signal_type="about_to_speak", confidence=piezo_result.confidence,
                    ))
                if piezo_result.speech_detected:
                    sig = Signal(
                        source_device=did, source_user=user_id,
                        signal_type="speaking", confidence=piezo_result.confidence,
                        value={"source": "piezo"},
                    )
                    await bus.emit_signal(sig)
                    await transcriber.on_speech_signal(sig)

            # Emit signals from PDM (confirms/enriches speech detection)
            if pdm_result and pdm_result.speech_detected:
                # If both piezo and PDM detect speech, boost confidence
                confidence = pdm_result.confidence
                if piezo_result and piezo_result.speech_detected:
                    confidence = min(1.0, (piezo_result.confidence + pdm_result.confidence) / 1.5)
                sig = Signal(
                    source_device=did, source_user=user_id,
                    signal_type="speaking_confirmed", confidence=confidence,
                    value={"source": "pdm+piezo" if (piezo_result and piezo_result.speech_detected) else "pdm"},
                )
                await bus.emit_signal(sig)
                await transcriber.on_speech_signal(sig)

            # Feed PDM audio to transcription buffer (higher quality mic)
            if pdm_b64:
                await transcriber.add_audio(user_id, did, pdm_bytes)

            # Detect speech end: neither mic hears speech
            piezo_speaking = piezo_result and piezo_result.speech_detected
            pdm_speaking = pdm_result and pdm_result.speech_detected
            if not piezo_speaking and not pdm_speaking:
                buf = transcriber.get_buffer(user_id)
                if buf.is_recording:
                    sig = Signal(
                        source_device=did, source_user=user_id,
                        signal_type="speech_ended", confidence=0.8,
                    )
                    await bus.emit_signal(sig)
                    await transcriber.on_speech_signal(sig)

            # Also process any edge-detected events (taps etc)
            for event in data.get("events", []):
                event_type = event.get("type")
                if not event_type:
                    continue
                await bus.emit_signal(Signal(
                    source_device=did, source_user=user_id,
                    signal_type=event_type,
                    confidence=event.get("confidence", 1.0),
                    value=event.get("value", {}),
                ))

            # Build response
            state = estimator.get(user_id)
            response: dict = {"state": state.to_dict()}
            if piezo_result:
                response["vad"] = {
                    "rms": round(piezo_result.features.rms, 4),
                    "zcr": round(piezo_result.features.zcr, 4),
                    "centroid": round(piezo_result.features.spectral_centroid, 1),
                }
            if pdm_result:
                response["pdm_vad"] = {
                    "rms": round(pdm_result.features.rms, 4),
                    "speech": pdm_result.speech_detected,
                }

            await ws.send_text(json.dumps(response))

    except WebSocketDisconnect:
        log.info("Raw collar %s disconnected (user %s)", did, user_id)
    except Exception:
        log.exception("Unexpected error in raw collar handler for %s", did)
    finally:
        registry.unregister(did)
