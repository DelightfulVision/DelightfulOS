# DelightfulOS — Distributed Wearable Operating System for Embodied AI

## Quick Start

```bash
# Install the OS package (from project root)
uv venv && uv pip install -e ".[dev]"

# Set up the server
cd server
cp .env.example .env    # fill in PRIME_API_KEY and PRIME_TEAM_ID
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
    simulator.py        Software device simulator

  ai/                   <-- AI stack
    config.py           Settings (pydantic-settings, env vars)
    prime.py            Prime Intellect inference client
    mediator.py         AI social mediator (LLM-based policy)
    signal.py           Piezo signal processing (VAD, features)
    models.py           Pydantic request/response models

  hdl/                  <-- Hardware Description Language
    grammar.py          Five-dimensional wearable grammar
    codesign.py         AI-assisted hardware co-design
    library/devices.py  Pre-built device specs

server/                 <-- Thin FastAPI shell
  app/main.py           FastAPI app (imports from delightfulos)
  app/routers/          HTTP/WS route handlers
  tests/                Integration tests

collar/firmware/        <-- ESP32-S3 Arduino firmware
  contact_mic.ino       Piezo, haptics, WebSocket
```

### Layer Boundaries

- **OS** has zero dependencies on networking, AI, or FastAPI
- **Runtime** depends only on OS
- **Networking** depends on OS + AI (for signal processing)
- **AI** depends on OS types only (for models)
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
- `POST /system/simulate/{user_id}` — start device simulator
- `DELETE /system/simulate/{user_id}` — stop simulator

### Devices
- `WS /collar/ws/{user_id}` — collar event mode
- `WS /collar/ws/{user_id}/raw` — collar raw audio mode
- `WS /system/glasses/ws/{user_id}` — glasses connection

### AI
- `POST /ai/mediate` — LLM-based social mediation
- `POST /ai/chat` — direct LLM chat
- `GET /ai/models` — available models

### HDL
- `GET /hdl/devices` — device specs
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
