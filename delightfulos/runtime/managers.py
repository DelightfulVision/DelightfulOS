"""Runtime Managers — MentraOS-inspired manager-based composition.

The Runtime class owns managers that each handle a domain:
  - DeviceManager: device lifecycle, heartbeat, stale cleanup
  - PolicyManager: rule evaluation + AI mediation on a slower cadence
  - SignalBatcher: collects signals in a time window before evaluating

Signal flow:
  Device -> Bus -> Batcher -> StateEstimator -> PolicyManager -> Router -> Device
                                              +> AI Mediator (every 2s, async)
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field

from delightfulos.os.types import Signal, Action
from delightfulos.os.bus import bus
from delightfulos.os.state import estimator, UserMode
from delightfulos.os.registry import registry
from delightfulos.runtime.policy import evaluate_rules, evaluate_signal
from delightfulos.runtime.output import route_action
from delightfulos.ai.transcribe import transcriber

log = logging.getLogger("delightfulos.runtime")


# ============================================================
# Device Manager
# ============================================================

class DeviceManager:
    """Manages device lifecycle: heartbeat tracking and stale device cleanup."""

    STALE_TIMEOUT = 30.0  # seconds without heartbeat = stale

    def __init__(self):
        self._cleanup_task: asyncio.Task | None = None

    def on_signal(self, signal: Signal):
        registry.touch(signal.source_device)

    def start_cleanup_loop(self):
        if self._cleanup_task is None:
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    async def stop(self):
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None

    async def _cleanup_loop(self):
        """Periodically remove devices that haven't sent a heartbeat."""
        while True:
            await asyncio.sleep(15)
            now = time.time()
            stale = [
                d.device_id for d in registry.all_devices()
                if (now - d.last_seen) > self.STALE_TIMEOUT
            ]
            for device_id in stale:
                device = registry.get(device_id)
                if device:
                    log.info("Removing stale device: %s (no heartbeat for %.0fs)",
                             device_id, now - device.last_seen)
                registry.unregister(device_id)


# ============================================================
# Signal Batcher
# ============================================================

class SignalBatcher:
    """Collects signals in a time window before triggering policy evaluation.

    Instead of evaluating policies on every signal (5+/sec per device),
    batch signals over a 200ms window and evaluate once per batch.

    Safety note: _pending list swap in _flush() is safe because asyncio
    is cooperative and there is no await between the swap statements.
    """

    BATCH_WINDOW_MS = 200

    def __init__(self):
        self._pending: list[Signal] = []
        self._batch_task: asyncio.Task | None = None
        self._on_batch = None  # callback: async def(signals: list[Signal])

    def set_handler(self, handler):
        self._on_batch = handler

    async def add(self, signal: Signal):
        """Add a signal to the current batch."""
        self._pending.append(signal)

        # Start a batch timer if not already running
        if self._batch_task is None or self._batch_task.done():
            self._batch_task = asyncio.create_task(self._flush_after_window())

    async def _flush_after_window(self):
        """Wait for the batch window then flush all pending signals."""
        await asyncio.sleep(self.BATCH_WINDOW_MS / 1000.0)
        await self._flush()

    async def _flush(self):
        if not self._pending or not self._on_batch:
            return
        # Atomic swap — no await between these two lines
        batch = self._pending
        self._pending = []
        await self._on_batch(batch)


# ============================================================
# AI Mediator Manager
# ============================================================

class AIMediatorManager:
    """Calls the LLM mediator on a slower cadence (every 2s) for complex situations.

    The rule engine handles simple cases instantly. The AI mediator handles:
      - Ambiguous social situations the rules can't resolve
      - Narrative/contextual responses ("Alice wants to share something")
      - Multi-turn conversation awareness

    Only fires when there are active users in social mode with recent signals.
    Skips if no API key is configured.
    """

    MEDIATION_INTERVAL = 2.0  # seconds between LLM calls
    MIN_SIGNALS_FOR_MEDIATION = 3  # need at least this many recent signals

    def __init__(self):
        self._task: asyncio.Task | None = None
        self._enabled = False

    def start(self):
        from delightfulos.ai.config import settings
        if not settings.prime_api_key:
            log.info("AI mediator disabled (no PRIME_API_KEY)")
            return
        self._enabled = True
        self._task = asyncio.create_task(self._mediation_loop())
        log.info("AI mediator started (interval=%.1fs, model=%s)",
                 self.MEDIATION_INTERVAL, settings.model_mediator)

    async def stop(self):
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _mediation_loop(self):
        from delightfulos.ai.config import settings
        from delightfulos.ai.prime import chat
        from delightfulos.ai.mediator import SYSTEM_PROMPT, _extract_json

        while True:
            await asyncio.sleep(self.MEDIATION_INTERVAL)

            try:
                await self._evaluate_once(settings, chat, SYSTEM_PROMPT, _extract_json)
            except Exception:
                log.warning("AI mediator error", exc_info=True)

    async def _evaluate_once(self, settings, chat, system_prompt, extract_json):
        """Single mediation cycle: gather state, call LLM, route actions."""
        # Only mediate for users in social mode with recent activity
        active_states = {
            s.user_id: s for s in estimator.all_states()
            if s.mode == UserMode.SOCIAL and (time.time() - s.last_updated) < 10
        }
        if not active_states:
            return

        # Check if there are enough recent signals to warrant AI reasoning
        recent = bus.recent_signals(limit=20)
        if len(recent) < self.MIN_SIGNALS_FOR_MEDIATION:
            return

        # Build context for the LLM
        context = {
            "users": {
                uid: {
                    "speech_intent": round(s.speech_intent, 2),
                    "speech_active": s.speech_active,
                    "stress_level": round(s.stress_level, 2),
                    "engagement": round(s.engagement, 2),
                    "attention_direction": s.attention_direction,
                    "interaction_ready": s.interaction_ready,
                    "overloaded": s.overloaded,
                }
                for uid, s in active_states.items()
            },
            "recent_signals": [
                {
                    "user": sig.source_user,
                    "type": sig.signal_type,
                    "confidence": round(sig.confidence, 2),
                }
                for sig in recent[-10:]  # last 10 signals
            ],
            "num_users": len(active_states),
        }

        raw = await chat(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(context)},
            ],
            model=settings.model_mediator,
            max_tokens=256,
            temperature=0.3,
        )

        try:
            data = extract_json(raw)
        except Exception:
            return

        action_type = data.get("action", "none")
        if action_type == "none":
            return

        # Convert LLM response to Action
        target_user = data.get("target_user")
        if not target_user:
            # Default to the user the LLM was reasoning about
            if len(active_states) == 1:
                target_user = next(iter(active_states))
            else:
                return

        action = Action(
            target_user=target_user,
            action_type=action_type,
            payload={},
        )

        # Build payload from LLM response
        if data.get("haptic"):
            action.target_type = "collar"
            action.payload = data["haptic"]
        elif data.get("ar_overlay"):
            action.target_type = "glasses"
            action.payload = data["ar_overlay"]
        elif data.get("message"):
            action.target_type = "glasses"
            action.payload = {"message": data["message"]}

        log.info("AI mediator: action=%s target=%s", action_type, target_user)
        await route_action(action)
        await bus.emit_action(action)


# ============================================================
# Runtime
# ============================================================

class Runtime:
    """Top-level runtime — owns managers, wires the signal pipeline.

    Signal flow:
      Device -> Bus -> Batcher -> [State update + Rule policies] -> Router -> Device
                                -> [AI Mediator every 2s]        -> Router -> Device
    """

    def __init__(self):
        self.device_manager = DeviceManager()
        self.batcher = SignalBatcher()
        self.ai_mediator = AIMediatorManager()
        self._started = False

    def start(self):
        """Initialize the runtime pipeline. Call once at app startup."""
        if self._started:
            return

        # Wire the batcher to process batches
        self.batcher.set_handler(self._on_batch)

        # Subscribe to all signals — they go through the batcher
        bus.subscribe_signal(self._on_signal)

        self._started = True
        log.info("Runtime started")

    def start_background_tasks(self):
        """Start async background tasks (call from async context, e.g. lifespan)."""
        self.device_manager.start_cleanup_loop()
        self.ai_mediator.start()
        transcriber.start()

    async def shutdown(self):
        """Cancel all background tasks. Call on server shutdown."""
        log.info("Runtime shutting down...")
        await self.device_manager.stop()
        await self.ai_mediator.stop()
        self._started = False
        log.info("Runtime stopped")

    async def _on_signal(self, signal: Signal):
        """Per-signal handler: update device heartbeat, add to batch."""
        self.device_manager.on_signal(signal)

        # Always update state immediately (low cost)
        estimator.update(signal)

        # Signal-reactive policies fire immediately (no batching)
        # for low-latency event-driven interactions like collar taps
        all_states = {s.user_id: s for s in estimator.all_states()}
        reactive_actions = evaluate_signal(signal, all_states)
        for action in reactive_actions:
            await route_action(action)
            await bus.emit_action(action)

        # Add to batch for state-based policy evaluation
        await self.batcher.add(signal)

    async def _on_batch(self, signals: list[Signal]):
        """Batch handler: evaluate policies once per batch window."""
        if not signals:
            return

        # Evaluate rule-based policies
        all_states = {s.user_id: s for s in estimator.all_states()}
        actions = evaluate_rules(all_states)

        # Route actions
        for action in actions:
            await route_action(action)
            await bus.emit_action(action)


# Singleton
runtime = Runtime()
