"""System-level routes — wearable OS status, device registry, state, simulation."""
import asyncio
import json
import logging
import time

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

from delightfulos.os.registry import registry
from delightfulos.os.state import estimator, UserMode
from delightfulos.os.bus import bus
from delightfulos.networking import glasses, simulator
from delightfulos.xr.handler import handle_xr_connection
from delightfulos.xr.session import session_manager

log = logging.getLogger("delightfulos.api.system")

router = APIRouter(prefix="/system", tags=["system"])


# === Device Registry ===

@router.get("/devices")
async def list_devices():
    return {"devices": registry.snapshot()}


@router.get("/devices/{user_id}")
async def user_devices(user_id: str):
    devices = registry.get_user_devices(user_id)
    return {
        "user_id": user_id,
        "devices": [
            {
                "device_id": d.device_id,
                "device_type": d.device_type.value,
                "capabilities": [c.value for c in d.capabilities],
            }
            for d in devices
        ],
    }


# === State ===

@router.get("/state")
async def all_states():
    return {"users": [s.to_dict() for s in estimator.all_states()]}


@router.get("/state/{user_id}")
async def user_state(user_id: str):
    return estimator.get(user_id).to_dict()


# === Signal Log ===

@router.get("/signals")
async def recent_signals(user_id: str | None = None, limit: int = 50):
    signals = bus.recent_signals(user_id=user_id, limit=limit)
    return {
        "count": len(signals),
        "signals": [
            {
                "source_device": s.source_device,
                "source_user": s.source_user,
                "signal_type": s.signal_type,
                "confidence": s.confidence,
                "value": s.value,
                "timestamp": s.timestamp,
            }
            for s in signals
        ],
    }


# === Transcriptions ===

@router.get("/transcriptions")
async def recent_transcriptions(user_id: str | None = None, limit: int = 20):
    signals = bus.recent_signals(user_id=user_id, limit=200)
    txns = [
        {
            "source_user": s.source_user,
            "text": s.value.get("text", ""),
            "latency": s.value.get("latency", 0),
            "timestamp": s.timestamp,
        }
        for s in signals
        if s.signal_type == "transcription"
    ][-limit:]
    return {"count": len(txns), "transcriptions": txns}


# === XR WebSocket (universal — works for all platforms) ===

@router.websocket("/xr/ws/{user_id}")
async def xr_ws(ws: WebSocket, user_id: str):
    """Universal XR WebSocket. Spectacles, Quest, etc. all connect here."""
    await handle_xr_connection(ws, user_id)


# === XR Sessions ===

@router.get("/xr/sessions")
async def xr_sessions():
    """List all active XR sessions."""
    return {"sessions": [s.to_dict() for s in session_manager.all_sessions()]}


# === Glasses WebSocket (legacy — redirects to XR handler) ===

@router.websocket("/glasses/ws/{user_id}")
async def glasses_ws(ws: WebSocket, user_id: str):
    await handle_xr_connection(ws, user_id)


# === Simulator ===

@router.post("/simulate/{user_id}")
async def start_sim(user_id: str):
    device_id = await simulator.start_simulator(user_id)
    return {"status": "started", "device_id": device_id, "user_id": user_id}


@router.delete("/simulate/{user_id}")
async def stop_sim(user_id: str):
    await simulator.stop_simulator(user_id)
    return {"status": "stopped", "user_id": user_id}


@router.get("/simulate")
async def list_sims():
    return {"simulators": simulator.list_simulators()}


# === Mode Switching ===

@router.post("/mode/{user_id}/{mode}")
async def set_mode(user_id: str, mode: str):
    """Switch a user's operating mode: social, focus, minimal, calibration."""
    try:
        user_mode = UserMode(mode)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown mode '{mode}'. Valid: {[m.value for m in UserMode]}",
        )
    estimator.set_mode(user_id, user_mode)
    return {"user_id": user_id, "mode": user_mode.value}


@router.get("/modes")
async def list_modes():
    """List all available modes and which users are in which mode."""
    return {
        "available_modes": [m.value for m in UserMode],
        "users": {
            s.user_id: s.mode.value
            for s in estimator.all_states()
        },
    }


# === Dashboard WebSocket (real-time feed) ===

@router.websocket("/dashboard/ws")
async def dashboard_ws(ws: WebSocket):
    """Live feed of entire OS state for the dashboard UI. Pushes every 500ms."""
    await ws.accept()
    try:
        while True:
            now = time.time()
            devices = registry.all_devices()
            states = estimator.all_states()
            signals = bus.recent_signals(limit=20)

            frame = {
                "timestamp": now,
                "devices": [
                    {
                        "device_id": d.device_id,
                        "device_type": d.device_type.value,
                        "user_id": d.user_id,
                        "alive": (now - d.last_seen) < 10,
                        "last_seen": round(now - d.last_seen, 1),
                        "wifi_rssi": d.metadata.get("wifi_rssi"),
                    }
                    for d in devices
                ],
                "users": [s.to_dict() for s in states],
                "recent_signals": [
                    {
                        "source_user": s.source_user,
                        "signal_type": s.signal_type,
                        "confidence": round(s.confidence, 2),
                        "age": round(now - s.timestamp, 1),
                    }
                    for s in signals[-10:]
                ],
                "transcriptions": [
                    {
                        "source_user": s.source_user,
                        "text": s.value.get("text", ""),
                        "latency": s.value.get("latency", 0),
                        "age": round(now - s.timestamp, 1),
                    }
                    for s in signals
                    if s.signal_type == "transcription"
                ][-10:],
                "summary": {
                    "total_devices": len(devices),
                    "total_users": len(states),
                    "active_speakers": sum(1 for s in states if s.speech_active),
                    "about_to_speak": sum(1 for s in states if s.speech_intent > 0.7 and not s.speech_active),
                    "stressed": sum(1 for s in states if s.stress_level > 0.6),
                    "overloaded": sum(1 for s in states if s.overloaded),
                },
            }

            await ws.send_text(json.dumps(frame))
            await asyncio.sleep(0.5)
    except WebSocketDisconnect:
        pass
    except Exception:
        log.exception("Dashboard WebSocket error")
