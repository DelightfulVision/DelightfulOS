"""Device Simulator — software simulation of wearable sensors for testing.

Generates realistic synthetic signals so the full pipeline can be tested
without any physical hardware connected.

Supports a "paused" mode where the device stays registered but no signals
are emitted — useful for testing with a clean/quiet baseline that you
manually disturb (e.g. with tap events).
"""
from __future__ import annotations

import asyncio
import logging
import math
import random

from delightfulos.os.types import Signal, DeviceInfo, DeviceType, Capability
from delightfulos.os.bus import bus
from delightfulos.os.registry import registry

log = logging.getLogger("delightfulos.simulator")


class CollarSimulator:

    def __init__(self, user_id: str, paused: bool = True):
        self.user_id = user_id
        self.device_id = f"sim_collar_{user_id}"
        self._running = False
        self._paused = paused  # when True, no auto-signals (clean baseline)
        self._task: asyncio.Task | None = None
        self._time = 0.0

    @property
    def paused(self) -> bool:
        return self._paused

    def set_paused(self, paused: bool):
        self._paused = paused
        if paused:
            # Reset user state to clean baseline so values don't freeze
            from delightfulos.os.state import estimator, BodyState
            state = estimator.get(self.user_id)
            state.speech_intent = 0.0
            state.speech_active = False
            state.stress_level = 0.0
            state.arousal = 0.5
            state.engagement = 0.5
            state.interaction_ready = False
            state.overloaded = False
            state.breathing_phase = "unknown"
        log.info("Simulator %s: signals %s", self.user_id, "paused" if paused else "resumed")

    async def start(self):
        registry.register(DeviceInfo(
            device_id=self.device_id,
            device_type=DeviceType.SIMULATOR,
            user_id=self.user_id,
            capabilities=[
                Capability.SENSE_VIBRATION,
                Capability.SENSE_AUDIO,
                Capability.OUTPUT_HAPTIC,
            ],
            metadata={"simulated": True, "paused": self._paused},
        ))
        self._running = True
        self._task = asyncio.create_task(self._run())
        log.info("Simulator started for %s (%s) paused=%s", self.user_id, self.device_id, self._paused)

    async def stop(self):
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        registry.unregister(self.device_id)
        log.info("Simulator stopped for %s", self.user_id)

    async def _run(self):
        while self._running:
            self._time += 0.2

            # Keep device alive even when paused
            registry.touch(self.device_id)

            if self._paused:
                await asyncio.sleep(0.2)
                continue

            cycle = math.sin(self._time * 0.3)

            if cycle > 0.6:
                await bus.emit_signal(Signal(
                    source_device=self.device_id,
                    source_user=self.user_id,
                    signal_type="speaking",
                    confidence=min(1.0, 0.7 + random.random() * 0.3),
                ))
            elif cycle > 0.3:
                await bus.emit_signal(Signal(
                    source_device=self.device_id,
                    source_user=self.user_id,
                    signal_type="about_to_speak",
                    confidence=0.5 + random.random() * 0.4,
                ))

            if random.random() < 0.02:
                await bus.emit_signal(Signal(
                    source_device=self.device_id,
                    source_user=self.user_id,
                    signal_type="stress_high",
                    confidence=0.6 + random.random() * 0.3,
                ))

            if random.random() < 0.05:
                await bus.emit_signal(Signal(
                    source_device=self.device_id,
                    source_user=self.user_id,
                    signal_type="orientation_shift",
                    confidence=0.7,
                    value={"direction": random.choice(["left", "right", "forward"])},
                ))

            breath_cycle = math.sin(self._time * 0.8)
            if abs(breath_cycle) > 0.8:
                await bus.emit_signal(Signal(
                    source_device=self.device_id,
                    source_user=self.user_id,
                    signal_type="breathing_change",
                    confidence=0.7,
                    value={
                        "phase": "inhale" if breath_cycle > 0 else "exhale",
                        "rate": 15 + random.random() * 5,
                    },
                ))

            await asyncio.sleep(0.2)

    async def tap(self):
        """Simulate a collar tap event (works even when paused)."""
        if not self._running:
            return
        await bus.emit_signal(Signal(
            source_device=self.device_id,
            source_user=self.user_id,
            signal_type="collar_tap",
            confidence=1.0,
        ))
        log.info("Simulated collar tap on %s", self.user_id)


# Active simulators
_simulators: dict[str, CollarSimulator] = {}


async def start_simulator(user_id: str, paused: bool = True) -> str:
    if user_id in _simulators:
        return _simulators[user_id].device_id
    sim = CollarSimulator(user_id, paused=paused)
    _simulators[user_id] = sim
    await sim.start()
    return sim.device_id


async def stop_simulator(user_id: str):
    sim = _simulators.pop(user_id, None)
    if sim:
        await sim.stop()


async def tap_collar(user_id: str) -> bool:
    """Simulate a tap on a user's collar. Returns True if simulator exists."""
    sim = _simulators.get(user_id)
    if sim:
        await sim.tap()
        return True
    return False


def set_paused(user_id: str, paused: bool) -> bool:
    """Pause or resume signal generation for a simulator. Returns True if found."""
    sim = _simulators.get(user_id)
    if sim:
        sim.set_paused(paused)
        return True
    return False


def is_paused(user_id: str) -> bool | None:
    """Check if a simulator is paused. Returns None if not found."""
    sim = _simulators.get(user_id)
    return sim.paused if sim else None


async def stop_all():
    """Stop all running simulators. Called on shutdown."""
    for uid in list(_simulators):
        await stop_simulator(uid)


def list_simulators() -> list[str]:
    return list(_simulators.keys())
