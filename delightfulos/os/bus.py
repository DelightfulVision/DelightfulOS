"""Signal Bus — central pub/sub event routing for the distributed wearable stack.

All device signals and output actions flow through the bus.
Inspired by ROS topics: typed messages, multiple subscribers, decoupled producers.
"""
from __future__ import annotations

import asyncio
import logging
from collections import deque
from typing import Callable, Awaitable

from delightfulos.os.types import Signal, Action

log = logging.getLogger("delightfulos.bus")

SignalHandler = Callable[[Signal], Awaitable[None]]
ActionHandler = Callable[[Action], Awaitable[None]]


class SignalBus:

    def __init__(self, max_log: int = 1000):
        self._signal_handlers: list[tuple[str | None, SignalHandler]] = []
        self._action_handlers: list[tuple[str | None, ActionHandler]] = []
        self._signal_log: deque[Signal] = deque(maxlen=max_log)

    # --- Subscribe ---

    def on_signal(self, signal_type: str | None = None) -> Callable:
        """Decorator to subscribe to signals."""
        def decorator(fn: SignalHandler):
            self._signal_handlers.append((signal_type, fn))
            return fn
        return decorator

    def on_action(self, action_type: str | None = None) -> Callable:
        """Decorator to subscribe to actions."""
        def decorator(fn: ActionHandler):
            self._action_handlers.append((action_type, fn))
            return fn
        return decorator

    def subscribe_signal(self, handler: SignalHandler, signal_type: str | None = None):
        self._signal_handlers.append((signal_type, handler))

    def subscribe_action(self, handler: ActionHandler, action_type: str | None = None):
        self._action_handlers.append((action_type, handler))

    def unsubscribe_signal(self, handler: SignalHandler):
        self._signal_handlers = [
            (t, h) for t, h in self._signal_handlers if h is not handler
        ]

    def unsubscribe_action(self, handler: ActionHandler):
        self._action_handlers = [
            (t, h) for t, h in self._action_handlers if h is not handler
        ]

    # --- Emit ---

    async def emit_signal(self, signal: Signal):
        self._signal_log.append(signal)
        log.debug("signal: %s from %s/%s (conf=%.2f)",
                  signal.signal_type, signal.source_user, signal.source_device, signal.confidence)

        tasks = []
        for filter_type, handler in self._signal_handlers:
            if filter_type is None or filter_type == signal.signal_type:
                tasks.append(handler(signal))
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in results:
                if isinstance(result, Exception):
                    log.error("Signal handler failed: %s", result, exc_info=result)

    async def emit_action(self, action: Action):
        log.debug("action: %s -> %s", action.action_type, action.target_user)
        tasks = []
        for filter_type, handler in self._action_handlers:
            if filter_type is None or filter_type == action.action_type:
                tasks.append(handler(action))
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in results:
                if isinstance(result, Exception):
                    log.error("Action handler failed: %s", result, exc_info=result)

    # --- Query ---

    def recent_signals(self, user_id: str | None = None, limit: int = 50) -> list[Signal]:
        signals: list[Signal] = list(self._signal_log)
        if user_id:
            signals = [s for s in signals if s.source_user == user_id]
        return signals[-limit:]

    # --- Test support ---

    def reset(self):
        """Clear all handlers and signal log. For tests only."""
        self._signal_handlers.clear()
        self._action_handlers.clear()
        self._signal_log.clear()


# Singleton
bus = SignalBus()
