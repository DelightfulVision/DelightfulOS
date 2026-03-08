"""Collar device WebSocket routes."""
import time

from fastapi import APIRouter, HTTPException, WebSocket

from delightfulos.networking.collar import handle_events, handle_raw_audio
from delightfulos.os.registry import registry
from delightfulos.os.types import DeviceType

router = APIRouter(prefix="/collar", tags=["collar"])


@router.websocket("/ws/{user_id}")
async def collar_events(ws: WebSocket, user_id: str):
    await handle_events(ws, user_id)


@router.websocket("/ws/{user_id}/raw")
async def collar_raw(ws: WebSocket, user_id: str):
    await handle_raw_audio(ws, user_id)


@router.get("/connected")
async def get_connected():
    collars = registry.get_by_type(DeviceType.COLLAR)
    now = time.time()
    return {
        "devices": [
            {
                "device_id": d.device_id,
                "user_id": d.user_id,
                "connected_at": d.connected_at,
                "last_seen": d.last_seen,
                "alive": (now - d.last_seen) < 10,
                "wifi_rssi": d.metadata.get("wifi_rssi"),
                "uptime_s": d.metadata.get("uptime_s"),
                "speech_active": d.metadata.get("speech_active"),
                "calibration": d.metadata.get("calibration"),
            }
            for d in collars
        ]
    }


@router.post("/calibrate/{user_id}")
async def trigger_calibration(user_id: str):
    """Send calibration command to a connected collar."""
    devices = registry.get_user_devices(user_id)
    collars = [d for d in devices if d.device_type == DeviceType.COLLAR]
    if not collars:
        raise HTTPException(status_code=404, detail=f"No collar connected for user {user_id}")

    import json
    sent = 0
    for collar in collars:
        if collar.transport:
            try:
                await collar.transport.send_text(json.dumps({
                    "action": "calibrate",
                    "payload": {},
                }))
                sent += 1
            except Exception:
                pass

    return {"status": "calibration_started", "user_id": user_id, "devices": sent}
