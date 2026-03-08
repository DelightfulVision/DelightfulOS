"""System-level routes — wearable OS status, device registry, state, simulation."""
import asyncio
import json
import logging
import time

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

from delightfulos.os.registry import registry
from delightfulos.os.state import estimator, UserMode
from delightfulos.os.bus import bus
from delightfulos.networking import simulator
from delightfulos.networking.supabase_rt import supabase_bridge
from delightfulos.ai.config import settings
from delightfulos.ai.context import context_log
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


# === Context Log ===

@router.get("/context")
async def context_events(user_id: str | None = None, limit: int = 30):
    """Get recent structured context events (semantic events for AI)."""
    return {
        "count": len(context_log.recent(limit=limit, user=user_id)),
        "events": context_log.recent(limit=limit, user=user_id),
    }


@router.get("/context/narrative")
async def context_narrative(user_id: str | None = None, limit: int = 20):
    """Get a plain-text narrative of recent events (for LLM prompts)."""
    return {
        "narrative": context_log.narrative(limit=limit, user=user_id),
    }


@router.get("/context/llm")
async def context_for_llm(limit: int = 20):
    """Get the full structured context dict ready for LLM consumption."""
    return context_log.for_llm(limit=limit)


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
                "context_events": context_log.recent(limit=15),
                "context_narrative": context_log.narrative(limit=10),
                "summary": {
                    "total_devices": len(devices),
                    "total_users": len(states),
                    "active_speakers": sum(1 for s in states if s.speech_active),
                    "about_to_speak": sum(1 for s in states if s.speech_intent > 0.7 and not s.speech_active),
                    "stressed": sum(1 for s in states if s.stress_level > 0.6),
                    "overloaded": sum(1 for s in states if s.overloaded),
                    "simulators": len(simulator.list_simulators()),
                    "sim_paused": {
                        uid: simulator.is_paused(uid)
                        for uid in simulator.list_simulators()
                    },
                },
            }

            await ws.send_text(json.dumps(frame))
            await asyncio.sleep(0.5)
    except WebSocketDisconnect:
        pass
    except Exception:
        log.exception("Dashboard WebSocket error")


# === Supabase Realtime (Snap Spectacles) ===

@router.get("/supabase/status")
async def supabase_status():
    """Check Supabase Realtime bridge status."""
    return {
        "connected": supabase_bridge.connected,
        "channel": supabase_bridge._channel,
        "url": supabase_bridge._url,
    }


@router.post("/supabase/connect")
async def supabase_connect():
    """Connect the Supabase Realtime bridge (uses env config)."""
    if supabase_bridge.connected:
        return {"status": "already_connected", "channel": supabase_bridge._channel}

    if not settings.supabase_url or not settings.supabase_anon_key:
        raise HTTPException(status_code=503, detail="SUPABASE_URL/SUPABASE_ANON_KEY not configured")

    await supabase_bridge.connect(
        settings.supabase_url,
        settings.supabase_anon_key,
        settings.supabase_channel,
    )
    return {"status": "connected", "channel": settings.supabase_channel}


@router.post("/supabase/disconnect")
async def supabase_disconnect():
    """Disconnect the Supabase Realtime bridge."""
    await supabase_bridge.disconnect()
    return {"status": "disconnected"}


@router.post("/supabase/broadcast/{event}")
async def supabase_broadcast(event: str, payload: dict):
    """Send a broadcast event to the Spectacles channel."""
    if not supabase_bridge.connected:
        raise HTTPException(status_code=503, detail="Supabase bridge not connected")
    await supabase_bridge.broadcast(event, payload)
    return {"status": "sent", "event": event}


# === Demo Mode ===

@router.post("/demo/start")
async def demo_start():
    """Spin up a 2-user demo scenario with simulated collars.

    Creates users 'alice' and 'bob' in social mode with simulators running.
    Returns user IDs so the dashboard can show them immediately.
    """
    users = ["alice", "bob"]
    results = []
    for uid in users:
        device_id = await simulator.start_simulator(uid)
        estimator.set_mode(uid, UserMode.SOCIAL)
        results.append({"user_id": uid, "device_id": device_id})
    return {"status": "demo_started", "users": results}


@router.post("/demo/stop")
async def demo_stop():
    """Stop all simulators and clear state."""
    sims = list(simulator.list_simulators())
    for uid in sims:
        await simulator.stop_simulator(uid)
    estimator.reset()
    context_log.reset()
    return {"status": "demo_stopped", "stopped": sims}


@router.post("/demo/tap/{user_id}")
async def demo_tap(user_id: str, tapper_id: str | None = None):
    """Trigger a collar tap in demo mode. Works for both sim and real devices."""
    from delightfulos.os.types import Signal

    # Try simulator first
    if await simulator.tap_collar(user_id):
        return {"status": "tapped", "user_id": user_id, "source": "simulator"}

    # For non-sim users, emit signal directly
    devices = registry.get_user_devices(user_id)
    device_id = devices[0].device_id if devices else f"collar_{user_id}"
    value = {}
    if tapper_id:
        value["tapper_id"] = tapper_id
    await bus.emit_signal(Signal(
        source_device=device_id,
        source_user=user_id,
        signal_type="collar_tap",
        confidence=1.0,
        value=value,
    ))
    return {"status": "tapped", "user_id": user_id, "source": "direct"}


@router.post("/demo/signals/{user_id}/{state}")
async def demo_signals_toggle(user_id: str, state: str):
    """Toggle simulated signal generation: 'on' to emit signals, 'off' for quiet baseline."""
    paused = state != "on"
    found = simulator.set_paused(user_id, paused)
    if not found:
        raise HTTPException(status_code=404, detail=f"No simulator for {user_id}")
    return {"user_id": user_id, "signals": state, "paused": paused}


@router.delete("/demo/user/{user_id}")
async def demo_remove_user(user_id: str):
    """Remove a single user from the demo — stops their simulator and clears state."""
    # Stop simulator if running
    await simulator.stop_simulator(user_id)
    # Remove all their devices from registry
    for d in registry.get_user_devices(user_id):
        registry.unregister(d.device_id)
    # Clear their state from estimator
    estimator._states.pop(user_id, None)
    return {"status": "removed", "user_id": user_id}
