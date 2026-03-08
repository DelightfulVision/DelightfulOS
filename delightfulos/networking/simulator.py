"""Device Simulator — software simulation of wearable sensors for testing.

Generates realistic synthetic signals so the full pipeline can be tested
without any physical hardware connected.
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

    def __init__(self, user_id: str):
        self.user_id = user_id
        self.device_id = f"sim_collar_{user_id}"
        self._running = False
        self._task: asyncio.Task | None = None
        self._time = 0.0

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
            metadata={"simulated": True},
        ))
        self._running = True
        self._task = asyncio.create_task(self._run())
        log.info("Simulator started for %s (%s)", self.user_id, self.device_id)

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
        """Simulate a collar tap event (as if another person tapped this collar)."""
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


async def start_simulator(user_id: str) -> str:
    if user_id in _simulators:
        return _simulators[user_id].device_id
    sim = CollarSimulator(user_id)
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


async def stop_all():
    """Stop all running simulators. Called on shutdown."""
    for uid in list(_simulators):
        await stop_simulator(uid)


def list_simulators() -> list[str]:
    return list(_simulators.keys())
