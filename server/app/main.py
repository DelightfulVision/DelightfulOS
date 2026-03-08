"""DelightfulOS Server — thin FastAPI shell over the OS runtime."""
import logging
import sys
from contextlib import asynccontextmanager

# Configure logging for all delightfulos modules
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s  %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stderr,
)
# Quiet noisy libraries
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from delightfulos import __version__
from delightfulos.runtime.managers import runtime
from delightfulos.networking.simulator import stop_all as stop_all_simulators
from delightfulos.ai.gemini_live import gemini_live
from app.routers import ai, collar, hdl, system

log = logging.getLogger("delightfulos.server")


@asynccontextmanager
async def lifespan(app: FastAPI):
    runtime.start()
    runtime.start_background_tasks()
    log.info("DelightfulOS v%s started", __version__)
    yield
    await stop_all_simulators()
    await gemini_live.shutdown()
    await runtime.shutdown()


app = FastAPI(
    title="DelightfulOS",
    description="Distributed Wearable Operating System for Embodied AI — MIT Hardware Hack 2026",
    version=__version__,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ai.router)
app.include_router(collar.router)
app.include_router(hdl.router)
app.include_router(system.router)

static_dir = Path(__file__).resolve().parent.parent / "static"
if static_dir.is_dir():
    app.mount("/static", StaticFiles(directory=str(static_dir), html=True), name="static")


@app.get("/")
async def root():
    return {"status": "ok", "service": "DelightfulOS", "version": __version__}


@app.get("/dashboard")
async def dashboard():
    return RedirectResponse("/static/dashboard.html")


@app.get("/health")
async def health():
    from delightfulos.os.registry import registry
    return {
        "healthy": True,
        "connected_devices": len(registry.all_devices()),
        "active_users": len(registry.all_users()),
    }
