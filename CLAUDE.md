# DelightfulOS — Distributed Wearable Operating System for Embodied AI

## Quick Start

```bash
# Install the OS package (from project root)
uv venv && uv pip install -e ".[dev]"

# Set up the server
cd server
cp .env.example .env    # fill in API keys (see .env.example)
uv venv && uv pip install -e ".[dev]" && uv pip install -e ..

# Run
.venv/Scripts/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
# Or: run.bat / run.sh
```

For public access (hackathon demo): `ngrok http 8000`

## Architecture

Layered monorepo inspired by ROS (typed pub/sub topics) and MentraOS (manager-based composition):

```
delightfulos/           <-- installable Python package
  os/                   <-- Core OS primitives (zero external deps)
    types.py            Signal, Action, DeviceInfo, DeviceType, Capability
    registry.py         Device registry (what's connected)
    bus.py              Signal bus (pub/sub, ROS-style topics)
    state.py            State estimator (per-user body state)

  runtime/              <-- Orchestration layer
    managers.py         Runtime, DeviceManager, PolicyManager (MentraOS-style)
    policy.py           Rule-based policy engine
    output.py           Output router (action -> device)

  networking/           <-- Transport layer
    collar.py           ESP32-S3 collar WebSocket handler
    glasses.py          Snap Spectacles WebSocket handler
    supabase_rt.py      Supabase Realtime bridge (Spectacles broadcast)
    simulator.py        Software device simulator

  ai/                   <-- AI stack
    config.py           Settings (pydantic-settings, env vars)
    prime.py            Prime Intellect inference client
    mediator.py         AI social mediator (LLM-based policy)
    gemini_live.py      Gemini Live bidirectional audio sessions
    signal.py           Piezo signal processing (VAD, features)
    transcribe.py       Audio transcription via Gemini
    models.py           Pydantic request/response models

  xr/                   <-- Platform-agnostic XR layer
    types.py            XR message types and enums
    protocol.py         XR protocol codec
    handler.py          Universal XR WebSocket handler
    session.py          XR session manager
    adapters/           Per-platform adapters (spectacles.py)

  hdl/                  <-- Hardware Description Language
    grammar.py          Five-dimensional wearable grammar
    codesign.py         AI-assisted hardware co-design
    library/devices.py  Pre-built device specs

server/                 <-- Thin FastAPI shell
  app/main.py           FastAPI app (imports from delightfulos)
  app/routers/          HTTP/WS route handlers (ai, collar, hdl, system)
  static/               Dashboard UI
  tests/                Integration tests

collar/firmware/        <-- ESP32-S3 Arduino firmware
  contact_mic.ino       Piezo, haptics, WebSocket
```

### Layer Boundaries

- **OS** has zero dependencies on networking, AI, or FastAPI
- **Runtime** depends only on OS
- **Networking** depends on OS + AI (for signal processing)
- **AI** depends on OS types only (for models)
- **XR** depends on OS types only
- **Server** depends on all layers but is a thin orchestration shell

### Signal Flow

```
Device -> Bus -> StateEstimator -> PolicyManager -> OutputRouter -> Device
```

## Key Conventions

- Secrets in `.env` only, never in source
- Config via `delightfulos/ai/config.py` (pydantic-settings, env var overrides)
- `delightfulos` is an installable package — `pip install -e .` from project root
- All device communication via WebSocket through the signal bus
- Rule-based policies for fast responses, LLM for complex social situations
- DeviceInfo.transport field is transport-agnostic (WebSocket, BLE, etc.)

## API Endpoints

### OS Layer
- `GET /system/devices` — all connected devices
- `GET /system/state` — all user body states
- `GET /system/state/{user_id}` — single user state
- `GET /system/signals` — recent signal log
- `GET /system/transcriptions` — recent transcriptions
- `GET /system/modes` — available modes and user assignments
- `POST /system/mode/{user_id}/{mode}` — switch user mode
- `POST /system/simulate/{user_id}` — start device simulator
- `DELETE /system/simulate/{user_id}` — stop simulator

### XR / Spectacles
- `WS /system/xr/ws/{user_id}` — universal XR WebSocket (all platforms)
- `WS /system/glasses/ws/{user_id}` — legacy glasses endpoint
- `GET /system/xr/sessions` — active XR sessions
- `WS /system/dashboard/ws` — live dashboard feed

### Supabase Realtime
- `GET /system/supabase/status` — bridge connection status
- `POST /system/supabase/connect` — connect bridge
- `POST /system/supabase/disconnect` — disconnect bridge
- `POST /system/supabase/broadcast/{event}` — send broadcast to Spectacles

### Devices
- `WS /collar/ws/{user_id}` — collar event mode
- `WS /collar/ws/{user_id}/raw` — collar raw audio mode
- `GET /collar/connected` — connected collars with status
- `POST /collar/calibrate/{user_id}` — trigger collar calibration

### AI
- `POST /ai/chat` — direct LLM chat
- `POST /ai/mediate` — LLM-based social mediation
- `GET /ai/models` — available models
- `GET /ai/live/status` — Gemini Live session status
- `POST /ai/live/connect/{user_id}` — open Gemini Live audio session
- `POST /ai/live/disconnect/{user_id}` — close audio session
- `POST /ai/live/artifact/{user_id}` — generate summary/notes/action_items
- `WS /ai/live/ws/{user_id}` — bidirectional audio WebSocket

### HDL
- `GET /hdl/devices` — device specs
- `GET /hdl/systems` — system specs
- `GET /hdl/systems/{name}/coverage` — system coverage analysis
- `POST /hdl/design` — AI co-design from natural language
- `POST /hdl/analyze` — system gap analysis

## Testing

```bash
cd server
.venv/Scripts/python -m tests.test_signal      # local, no API
.venv/Scripts/python -m tests.test_prime_api    # needs .env
.venv/Scripts/python -m tests.test_server       # needs running server
```
