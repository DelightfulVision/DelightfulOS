# DelightfulOS

A wearable operating system for augmented reality — social awareness, AI mediation, and XR integration. Currently integrated with Snap Spectacles, with a platform-agnostic XR layer designed to support additional devices in the future.

## Architecture

```
delightfulos/          — Core OS: signal bus, state estimator, device registry, AI mediator
  os/                  — Bus, state, registry, output routing
  ai/                  — LLM integration (chat, mediation, transcription)
  xr/                  — Platform-agnostic XR layer + per-platform adapters
  networking/          — Device transports (collar, glasses, simulator)
  runtime/             — Background task managers, lifecycle
server/                — FastAPI server, REST + WebSocket endpoints, dashboard
docs/                  — Protocol specs, integration guides
```

## Quick Start

```bash
cd server
uv sync
cp .env.example .env   # fill in your API keys
uv run uvicorn app.main:app --reload
```

Dashboard: `http://localhost:8000/dashboard`
