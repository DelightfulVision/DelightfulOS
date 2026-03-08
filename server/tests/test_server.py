"""Test server endpoints (requires server running on localhost:8000).

Run: cd server && .venv/Scripts/python -m tests.test_server
"""
import json
import time
import asyncio
import httpx
import websockets

BASE = "http://localhost:8000"


async def test_health():
    print("=== Health ===")
    async with httpx.AsyncClient() as c:
        r = await c.get(f"{BASE}/health")
        assert r.status_code == 200
        assert r.json()["healthy"] is True
        print("  OK")


async def test_mediate():
    print("\n=== Mediation ===")
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(f"{BASE}/ai/mediate", json={
            "user_id": "test_a",
            "timestamp": time.time(),
            "events": [{"type": "about_to_speak", "confidence": 0.85}],
            "shared_context": {"other_user_id": "test_b"},
        })
        assert r.status_code == 200
        data = r.json()
        assert "action" in data
        print(f"  action={data['action']} OK")


async def test_hdl():
    print("\n=== HDL ===")
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(f"{BASE}/hdl/devices")
        assert r.status_code == 200
        devices = r.json()
        assert "collar_v1" in devices
        print(f"  Devices: {list(devices.keys())} OK")

        r = await c.get(f"{BASE}/hdl/systems/social_radar/coverage")
        assert r.status_code == 200
        print(f"  Coverage: OK")


async def test_websocket():
    print("\n=== WebSocket ===")
    uri = f"ws://localhost:8000/collar/ws/test_ws"
    async with websockets.connect(uri) as ws:
        await ws.send(json.dumps({
            "timestamp": time.time(),
            "events": [{"type": "about_to_speak", "confidence": 0.9}],
        }))
        resp = json.loads(await ws.recv())
        assert "state" in resp
        print(f"  WS response: state received OK")


async def main():
    try:
        await test_health()
    except Exception as e:
        print(f"  Server not running? {e}")
        print("  Start with: cd server && .venv/Scripts/uvicorn app.main:app --port 8000")
        return

    await test_mediate()
    await test_hdl()
    await test_websocket()
    print("\nAll server tests passed.")


if __name__ == "__main__":
    asyncio.run(main())
