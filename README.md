# DelightfulOS

A distributed operating system for real-time interactions between wearable devices under an Internet of Bodies framework. Connects body-worn sensors, AR glasses, and AI into a unified signal bus where your body state drives shared perception.

Built by [Delightful.vision](https://delightful.vision). Currently integrated with Snap Spectacles and a custom piezo collar, with a platform-agnostic XR layer supporting Quest, Vision Pro, and WebXR.

## What It Does

DelightfulOS proposes that the most meaningful AI interfaces are not screens or speakers, but the body itself — sensed, augmented, and shared.

A piezo contact microphone on your throat detects speech intent ~200ms before you make a sound. AR overlays on Spectacles show others your body state in real time. Tapping someone's collar changes what you see over them. The collar is a physical interface that others use to shape their experience of you.

**Core capabilities:**
- Real-time body state estimation from piezo contact microphone signals
- Bidirectional audio AI via Gemini Live (listen, transcribe, respond, summarize)
- AR overlays and social cues pushed to Snap Spectacles via Supabase Realtime
- Rule-based and LLM-powered social mediation (turn-taking, stress, interruptions)
- Signal-reactive policies for low-latency physical interactions (collar tap -> AR)
- Modular Hardware Description Language for wearable co-design with AI
- Multi-user, multi-device — every user gets independent state tracking

See [docs/VISION.md](docs/VISION.md) for the full conceptual and technical position.

## Architecture

Layered monorepo inspired by ROS (typed pub/sub topics) and MentraOS (manager-based composition):

```
delightfulos/              Installable Python package
  os/                      Core OS primitives (zero external deps)
    types.py                 Signal, Action, DeviceInfo, DeviceType, Capability
    registry.py              Device registry (what's connected)
    bus.py                   Signal bus (pub/sub, ROS-style topics)
    state.py                 State estimator (per-user body state)
  runtime/                 Orchestration layer
    managers.py              Runtime, DeviceManager, PolicyManager
    policy.py                Rule-based policy engine
    output.py                Output router (action -> device)
  ai/                      AI stack
    config.py                Settings (pydantic-settings, env vars)
    prime.py                 Prime Intellect inference client (OpenAI-compatible)
    mediator.py              AI social mediator (LLM-based policy)
    gemini_live.py           Gemini Live bidirectional audio sessions
    signal.py                Piezo signal processing (VAD, features)
    transcribe.py            Audio transcription via Gemini
    models.py                Pydantic request/response models
  xr/                      Platform-agnostic XR layer
    types.py                 XR message types and enums
    protocol.py              XR protocol codec
    handler.py               Universal XR WebSocket handler
    session.py               XR session manager
    adapters/spectacles.py   Snap Spectacles adapter
  networking/              Transport layer
    collar.py                ESP32-S3 collar WebSocket handler
    glasses.py               Snap Spectacles WebSocket handler
    supabase_rt.py           Supabase Realtime bridge (Spectacles broadcast)
    simulator.py             Software device simulator
  hdl/                     Hardware Description Language
    grammar.py               Five-dimensional wearable grammar
    codesign.py              AI-assisted hardware co-design
    library/devices.py       Pre-built device specs (collar, spectacles)

server/                    Thin FastAPI shell
  app/main.py                FastAPI app with lifespan management
  app/routers/               HTTP/WS route handlers (ai, collar, hdl, system)
  static/dashboard.html      Live OS dashboard
  tests/                     Integration tests

collar/                    ESP32-S3 Arduino firmware
  firmware/contact_mic.ino   Piezo sensor, haptics, WebSocket client
  WIRING.md                  Hardware wiring guide

scripts/
  demo.sh                   Launch server + 2 simulators + dashboard
  tunnel.sh                 ngrok tunnel for public access

docs/
  spectacles-protocol.json  XR protocol spec (all message types)
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
                                       |
                              LLM Mediator (complex situations)
```

## Quick Start

```bash
# Install the OS package (from project root)
uv venv && uv pip install -e ".[dev]"

# Set up the server
cd server
cp .env.example .env    # fill in API keys (see below)
uv venv && uv pip install -e ".[dev]" && uv pip install -e ..

# Run
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Or use the demo script to start the server with simulated users:
```bash
bash scripts/demo.sh
```

**Dashboard:** http://localhost:8000/dashboard
**API docs:** http://localhost:8000/docs
**Public access (hackathon):** `ngrok http 8000`

### Environment Variables

Create `server/.env` from `.env.example`:

| Variable | Required | Description |
|---|---|---|
| `PRIME_API_KEY` | Yes | [Prime Intellect](https://app.primeintellect.ai/dashboard/tokens) inference API key |
| `PRIME_TEAM_ID` | Yes | Prime Intellect team ID |
| `GEMINI_API_KEY` | For audio | [Google AI Studio](https://aistudio.google.com/apikey) key for Gemini Live |
| `SUPABASE_URL` | For Spectacles | Supabase project URL (snapcloud.dev for Snap-hosted) |
| `SUPABASE_ANON_KEY` | For Spectacles | Supabase anonymous/public key |
| `SUPABASE_CHANNEL` | For Spectacles | Realtime broadcast channel name (default: `spectacles`) |

## API Endpoints

### System / OS
| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Health check |
| `GET` | `/system/devices` | All connected devices |
| `GET` | `/system/devices/{user_id}` | Devices for a user |
| `GET` | `/system/state` | All user body states |
| `GET` | `/system/state/{user_id}` | Single user state |
| `GET` | `/system/signals` | Recent signal log |
| `GET` | `/system/transcriptions` | Recent transcriptions |
| `GET` | `/system/modes` | Available modes and user assignments |
| `POST` | `/system/mode/{user_id}/{mode}` | Switch user mode (social/focus/minimal/calibration) |
| `POST` | `/system/simulate/{user_id}` | Start device simulator |
| `DELETE` | `/system/simulate/{user_id}` | Stop simulator |

### XR / Spectacles
| Method | Path | Description |
|---|---|---|
| `WS` | `/system/xr/ws/{user_id}` | Universal XR WebSocket (all platforms) |
| `WS` | `/system/glasses/ws/{user_id}` | Legacy glasses endpoint (same protocol) |
| `GET` | `/system/xr/sessions` | Active XR sessions |
| `WS` | `/system/dashboard/ws` | Live dashboard feed (500ms updates) |

### Supabase Realtime (Snap Spectacles)
| Method | Path | Description |
|---|---|---|
| `GET` | `/system/supabase/status` | Bridge connection status |
| `POST` | `/system/supabase/connect` | Connect bridge (uses env config) |
| `POST` | `/system/supabase/disconnect` | Disconnect bridge |
| `POST` | `/system/supabase/broadcast/{event}` | Send broadcast event to Spectacles |

### Collar
| Method | Path | Description |
|---|---|---|
| `WS` | `/collar/ws/{user_id}` | Collar event mode (JSON signals) |
| `WS` | `/collar/ws/{user_id}/raw` | Collar raw audio mode (PCM stream) |
| `GET` | `/collar/connected` | Connected collars with status |
| `POST` | `/collar/calibrate/{user_id}` | Trigger collar calibration |
| `POST` | `/collar/tap/{user_id}` | Trigger collar tap (physical or simulated) |

### AI
| Method | Path | Description |
|---|---|---|
| `POST` | `/ai/chat` | Direct LLM chat |
| `POST` | `/ai/mediate` | Social mediation from body state |
| `GET` | `/ai/models` | Available models |
| `GET` | `/ai/live/status` | Gemini Live session status |
| `POST` | `/ai/live/connect/{user_id}` | Open Gemini Live audio session |
| `POST` | `/ai/live/disconnect/{user_id}` | Close audio session |
| `POST` | `/ai/live/artifact/{user_id}` | Generate summary/notes/action_items from transcripts |
| `WS` | `/ai/live/ws/{user_id}` | Bidirectional audio WebSocket (base64 PCM) |

### HDL (Hardware Description Language)
| Method | Path | Description |
|---|---|---|
| `GET` | `/hdl/devices` | Device specs (collar, spectacles) |
| `GET` | `/hdl/systems` | System specs (social_radar, full_body) |
| `GET` | `/hdl/systems/{name}/coverage` | System coverage analysis |
| `POST` | `/hdl/design` | AI co-design from natural language description |
| `POST` | `/hdl/analyze` | System gap analysis |

## Supabase Realtime Protocol

The Supabase bridge connects DelightfulOS to Snap Spectacles via broadcast channels on the `spectacles` channel (no database writes needed — pure WebSocket pub/sub).

**Spectacles -> Server:**
| Event | Payload | OS Signal |
|---|---|---|
| `cursor-move` | `{user_id, x, y, color}` | `gaze_position` |
| `control-mode` | `{mode: "follow"\|"free"\|"anchor"}` | `mode_change` |
| `cursor-enter` | `{user_id, user_name, color}` | `presence` |
| `cursor-leave` | `{user_id, user_name, color}` | `absence` |

**Server -> Spectacles:**
| Event | Payload | Source |
|---|---|---|
| `os-state` | `{user_id, speech_active, stress_level, engagement, ...}` | State estimator (every 500ms) |
| `os-action` | `{action_type, target_user, payload}` | Policy engine |
| `live-transcript` | `{user_id, text, source: "input"\|"output"}` | Gemini Live |
| `ar-overlay` | `{target_user, type, color, ...}` | Output router |

## Gemini Live Audio

Bidirectional real-time audio via Google's native audio API. The collar streams 16kHz PCM audio to the server, which pipes it to Gemini Live and streams 24kHz audio responses back.

- Input/output transcription via Gemini's built-in transcription
- Context window compression for unlimited session duration
- Session resumption across reconnects
- Artifact generation (summaries, meeting notes, action items) from accumulated transcripts
- Transcriptions are automatically forwarded to Spectacles via the Supabase bridge

## XR Protocol

The XR WebSocket protocol (`/system/xr/ws/{user_id}`) is platform-agnostic. See `docs/spectacles-protocol.json` for the full spec.

**Client -> Server:** `scene_update`, `gesture`, `pinch`, `gaze_shift`, `voice_command`, `heartbeat`
**Server -> Client:** `show_overlay`, `remove_overlay`, `highlight_user`, `toast`, `social_cue`, `haptic`, `mode_change`, `state_update`

Supported platforms: Spectacles (active), Quest/Vision Pro/WebXR (protocol-ready).

## Testing

```bash
cd server

# Unit tests (no API keys needed)
uv run python -m tests.test_signal

# API integration tests (needs .env with PRIME_API_KEY)
uv run python -m tests.test_prime_api

# Server integration tests (needs running server)
uv run python -m tests.test_server
```

## Hardware

The collar is an ESP32-S3 with a piezo contact microphone and haptic motor. See `collar/WIRING.md` for the wiring guide and `collar/firmware/contact_mic.ino` for the Arduino firmware.

## Tech Stack

- **Server:** Python 3.12+, FastAPI, uvicorn, pydantic
- **AI inference:** [Prime Intellect](https://www.primeintellect.ai/) (OpenAI-compatible, 100+ models), Google Gemini Live
- **XR transport:** Supabase Realtime (Phoenix WebSocket protocol via snapcloud.dev)
- **XR client:** Snap Spectacles via Lens Studio
- **Hardware:** ESP32-S3, piezo contact mic, haptic motor
- **Package management:** uv
