"""XR WebSocket Handler — platform-agnostic connection handler for XR devices.

Handles the XR protocol: hello handshake, scene updates, gesture events, etc.
Translates XR input events into OS Signals and routes OS Actions as XR output commands.

This replaces the old glasses.py handler with a proper protocol-based approach
that works for any XR platform.
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
from delightfulos.xr.types import XRPlatform, XRCapability, XRSceneState
from delightfulos.xr.protocol import (
    XRInputEvent, XRInputType, XROutputCommand, XROutputType, PROTOCOL_VERSION,
)
from delightfulos.xr.session import XRSession, session_manager

log = logging.getLogger("delightfulos.xr")

# Map XR capabilities to OS capabilities
_XR_TO_OS_CAPS: dict[XRCapability, Capability] = {
    XRCapability.HAND_TRACKING: Capability.SENSE_GESTURE,
    XRCapability.EYE_TRACKING: Capability.SENSE_CAMERA,
    XRCapability.HEAD_TRACKING: Capability.SENSE_IMU,
    XRCapability.DEPTH_SENSING: Capability.SENSE_DEPTH,
    XRCapability.VOICE_INPUT: Capability.SENSE_AUDIO,
    XRCapability.AR_OVERLAY: Capability.OUTPUT_VISUAL_AR,
    XRCapability.SPATIAL_AUDIO: Capability.OUTPUT_AUDIO,
    XRCapability.HAPTIC_OUTPUT: Capability.OUTPUT_HAPTIC,
}

# Map XR input types to OS signal types
_INPUT_TO_SIGNAL: dict[str, str] = {
    XRInputType.GESTURE: "gesture",
    XRInputType.GAZE_SHIFT: "orientation_shift",
    XRInputType.PINCH: "touch",
    XRInputType.HEAD_NOD: "gesture",
    XRInputType.HEAD_SHAKE: "gesture",
    XRInputType.VOICE_COMMAND: "voice_command",
    XRInputType.VOICE_ACTIVITY: "speaking",
    XRInputType.USER_DETECTED: "user_detected",
    XRInputType.USER_LOST: "user_lost",
}


async def handle_xr_connection(ws: WebSocket, user_id: str):
    """Universal XR WebSocket handler. Works for any platform.

    Protocol:
      1. Client connects
      2. Client sends 'hello' with platform + capabilities
      3. Server acknowledges with state + protocol version
      4. Bidirectional event/command flow
    """
    await ws.accept()
    session_id = f"xr_{user_id}_{int(time.time() * 1000) % 100000}"
    session: XRSession | None = None

    try:
        while True:
            raw_text = await ws.receive_text()
            try:
                data = json.loads(raw_text)
            except json.JSONDecodeError:
                log.warning("Malformed JSON from XR client %s: %s", session_id, raw_text[:100])
                continue

            event = XRInputEvent.from_dict(data)
            event.user_id = event.user_id or user_id

            # --- Hello handshake ---
            if event.type == XRInputType.HELLO:
                session = _handle_hello(event, session_id, user_id, ws)
                # Send acknowledgment
                ack = XROutputCommand(
                    type=XROutputType.STATE_UPDATE,
                    payload={
                        "protocol_version": PROTOCOL_VERSION,
                        "session_id": session_id,
                        "state": estimator.get(user_id).to_dict(),
                    },
                )
                await ws.send_text(json.dumps(ack.to_dict()))
                continue

            if not session:
                # Haven't received hello yet — auto-create a generic session
                session = _handle_hello(XRInputEvent(
                    type=XRInputType.HELLO,
                    user_id=user_id,
                    payload={"platform": "spectacles", "capabilities": []},
                ), session_id, user_id, ws)

            # --- Heartbeat ---
            if event.type == XRInputType.HEARTBEAT:
                session_manager.touch(session_id)
                registry.touch(session_id)
                continue

            # --- Scene update ---
            if event.type == XRInputType.SCENE_UPDATE:
                scene = XRSceneState.from_dict(event.payload)
                await bus.emit_signal(Signal(
                    source_device=session_id,
                    source_user=user_id,
                    signal_type="scene_update",
                    value=scene.to_dict(),
                ))
                # Send back current state
                state = estimator.get(user_id)
                await ws.send_text(json.dumps(XROutputCommand(
                    type=XROutputType.STATE_UPDATE,
                    payload={"state": state.to_dict()},
                ).to_dict()))
                continue

            # --- All other input events -> OS Signals ---
            signal_type = _INPUT_TO_SIGNAL.get(event.type, event.type)
            value = dict(event.payload)
            value["xr_input_type"] = event.type  # preserve original type

            await bus.emit_signal(Signal(
                source_device=session_id,
                source_user=user_id,
                signal_type=signal_type,
                confidence=event.payload.get("confidence", 0.8),
                value=value,
                timestamp=event.timestamp or time.time(),
            ))

            # Send back updated state
            state = estimator.get(user_id)
            await ws.send_text(json.dumps(XROutputCommand(
                type=XROutputType.STATE_UPDATE,
                payload={"state": state.to_dict()},
            ).to_dict()))

    except WebSocketDisconnect:
        log.info("XR session %s disconnected (user %s)", session_id, user_id)
    except Exception:
        log.exception("Unexpected error in XR handler for %s", session_id)
    finally:
        session_manager.unregister(session_id)
        registry.unregister(session_id)


def _handle_hello(
    event: XRInputEvent,
    session_id: str,
    user_id: str,
    ws: WebSocket,
) -> XRSession:
    """Process the hello handshake — register the session and device."""
    platform_str = event.payload.get("platform", "spectacles")
    try:
        platform = XRPlatform(platform_str)
    except ValueError:
        log.warning("Unknown XR platform '%s', defaulting to spectacles", platform_str)
        platform = XRPlatform.SPECTACLES

    cap_strs = event.payload.get("capabilities", [])
    xr_caps = []
    for c in cap_strs:
        try:
            xr_caps.append(XRCapability(c))
        except ValueError:
            pass

    session = XRSession(
        session_id=session_id,
        user_id=user_id,
        platform=platform,
        capabilities=xr_caps,
        transport=ws,
        metadata=event.payload.get("metadata", {}),
    )
    session_manager.register(session)

    # Also register as a device in the OS registry
    os_caps = [_XR_TO_OS_CAPS[c] for c in xr_caps if c in _XR_TO_OS_CAPS]
    if Capability.OUTPUT_VISUAL_AR not in os_caps:
        os_caps.append(Capability.OUTPUT_VISUAL_AR)

    registry.register(DeviceInfo(
        device_id=session_id,
        device_type=DeviceType.GLASSES,
        user_id=user_id,
        capabilities=os_caps,
        transport=ws,
        metadata={
            "xr_platform": platform.value,
            "xr_capabilities": [c.value for c in xr_caps],
        },
    ))

    log.info("XR hello: %s on %s with %d capabilities",
             user_id, platform.value, len(xr_caps))
    return session
