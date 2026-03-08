"""Glasses device handler — Snap Spectacles integration.

Manages connections from Spectacles (via Connected Lenses / BLE / phone bridge).
"""
from __future__ import annotations

import json
import logging
import time

from fastapi import WebSocket, WebSocketDisconnect

from delightfulos.os.types import Signal, DeviceInfo, DeviceType, Capability
from delightfulos.os.bus import bus
from delightfulos.os.registry import registry
from delightfulos.os.state import estimator

log = logging.getLogger("delightfulos.glasses")

GLASSES_CAPABILITIES = [
    Capability.SENSE_CAMERA,
    Capability.SENSE_DEPTH,
    Capability.SENSE_IMU,
    Capability.SENSE_AUDIO,
    Capability.OUTPUT_VISUAL_AR,
    Capability.OUTPUT_AUDIO,
]


async def handle_connection(ws: WebSocket, user_id: str, device_id: str | None = None):
    """WebSocket handler for Spectacles (or phone bridge to Spectacles)."""
    await ws.accept()
    did = device_id or f"glasses_{user_id}"

    registry.register(DeviceInfo(
        device_id=did,
        device_type=DeviceType.GLASSES,
        user_id=user_id,
        capabilities=list(GLASSES_CAPABILITIES),
        transport=ws,
    ))

    try:
        while True:
            raw_text = await ws.receive_text()
            try:
                data = json.loads(raw_text)
            except json.JSONDecodeError:
                log.warning("Malformed JSON from glasses %s: %s", did, raw_text[:100])
                continue

            msg_type = data.get("type", "events")

            if msg_type == "events":
                for event in data.get("events", []):
                    event_type = event.get("type")
                    if not event_type:
                        log.warning("Event missing 'type' from glasses %s: %s", did, event)
                        continue
                    await bus.emit_signal(Signal(
                        source_device=did,
                        source_user=user_id,
                        signal_type=event_type,
                        confidence=event.get("confidence", 1.0),
                        value=event.get("value", {}),
                        timestamp=data.get("timestamp", time.time()),
                    ))

            elif msg_type == "scene_state":
                await bus.emit_signal(Signal(
                    source_device=did,
                    source_user=user_id,
                    signal_type="scene_update",
                    value=data.get("scene", {}),
                ))

            state = estimator.get(user_id)
            await ws.send_text(json.dumps({"state": state.to_dict()}))

    except WebSocketDisconnect:
        log.info("Glasses %s disconnected (user %s)", did, user_id)
    except Exception:
        log.exception("Unexpected error in glasses handler for %s", did)
    finally:
        registry.unregister(did)
