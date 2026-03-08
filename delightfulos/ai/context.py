"""Structured Context Log — converts raw signals into rich semantic events for AI.

Watches the signal bus and builds a rolling narrative of what's happening,
suitable for feeding to LLMs (Gemini Live, Prime Intellect mediator).

Raw signals are noisy and repetitive (5+ per second per device). This module
deduplicates, detects transitions, and produces human-readable structured
events like:

  {"event": "speech_start", "user": "alice", "t": 12.3,
   "detail": "alice started speaking (intent was rising for 2.1s)"}

  {"event": "collar_tap", "user": "bob", "t": 15.0,
   "detail": "someone tapped bob's collar, hiding bob's overlay for alice"}

  {"event": "stress_rising", "user": "alice", "t": 18.5,
   "detail": "alice's stress has been rising for 8s (now 0.72)"}

The context log is:
  1. Queryable (get recent events, get events for a user)
  2. Serializable to JSON (for LLM prompts)
  3. Testable (feed known signals, assert expected events)
"""
from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field

from delightfulos.os.types import Signal, Action
from delightfulos.os.bus import bus
from delightfulos.os.state import estimator, BodyState

log = logging.getLogger("delightfulos.context")


@dataclass
class ContextEvent:
    """A single structured event in the context log."""
    event: str          # e.g. "speech_start", "collar_tap", "stress_rising"
    user: str           # primary user this event is about
    t: float            # timestamp (time.time())
    detail: str         # human-readable description for LLM
    data: dict = field(default_factory=dict)  # structured payload

    def to_dict(self) -> dict:
        return {
            "event": self.event,
            "user": self.user,
            "t": round(self.t, 2),
            "age": round(time.time() - self.t, 1),
            "detail": self.detail,
            "data": self.data,
        }


class ContextLog:
    """Converts raw signals into structured semantic events.

    Subscribes to the signal bus and tracks per-user state transitions.
    Produces ContextEvents only when something meaningful changes.
    """

    MAX_EVENTS = 200

    def __init__(self):
        self._events: deque[ContextEvent] = deque(maxlen=self.MAX_EVENTS)
        self._subscribed = False

        # Per-user transition tracking
        self._was_speaking: dict[str, bool] = {}
        self._was_about_to_speak: dict[str, bool] = {}
        self._was_stressed: dict[str, bool] = {}
        self._was_overloaded: dict[str, bool] = {}
        self._stress_rise_start: dict[str, float] = {}  # when stress started rising
        self._speech_intent_rise_start: dict[str, float] = {}
        self._last_mode: dict[str, str] = {}

    def start(self):
        """Subscribe to the signal bus. Call once at startup."""
        if self._subscribed:
            return
        bus.subscribe_signal(self._on_signal)
        bus.subscribe_action(self._on_action)
        self._subscribed = True
        log.info("Context log started")

    def _emit(self, event: str, user: str, detail: str, data: dict | None = None):
        """Add a structured event to the log."""
        ev = ContextEvent(
            event=event,
            user=user,
            t=time.time(),
            detail=detail,
            data=data or {},
        )
        self._events.append(ev)
        log.debug("context: [%s] %s — %s", event, user, detail)

    # ------------------------------------------------------------------ #
    #  Signal handler — detect transitions                                #
    # ------------------------------------------------------------------ #

    async def _on_signal(self, signal: Signal):
        uid = signal.source_user
        t = signal.signal_type
        state = estimator.get(uid)

        # --- Speech transitions ---
        was = self._was_speaking.get(uid, False)
        now_speaking = state.speech_active

        if now_speaking and not was:
            # Speech started
            intent_dur = ""
            if uid in self._speech_intent_rise_start:
                dur = time.time() - self._speech_intent_rise_start[uid]
                intent_dur = f" (intent was rising for {dur:.1f}s)"
                del self._speech_intent_rise_start[uid]
            self._emit("speech_start", uid,
                       f"{uid} started speaking{intent_dur}",
                       {"speech_intent": round(state.speech_intent, 2)})
        elif was and not now_speaking:
            self._emit("speech_end", uid, f"{uid} stopped speaking")

        self._was_speaking[uid] = now_speaking

        # --- About-to-speak transitions ---
        was_intent = self._was_about_to_speak.get(uid, False)
        now_intent = state.speech_intent > 0.5 and not state.speech_active

        if now_intent and not was_intent:
            self._speech_intent_rise_start[uid] = time.time()
            self._emit("intent_rising", uid,
                       f"{uid} appears to be preparing to speak (intent={state.speech_intent:.2f})",
                       {"speech_intent": round(state.speech_intent, 2)})

        self._was_about_to_speak[uid] = now_intent

        # --- Stress transitions ---
        was_stressed = self._was_stressed.get(uid, False)
        now_stressed = state.stress_level > 0.4

        if now_stressed and not was_stressed:
            self._stress_rise_start[uid] = time.time()
            self._emit("stress_rising", uid,
                       f"{uid}'s stress is rising (now {state.stress_level:.2f})",
                       {"stress_level": round(state.stress_level, 2)})
        elif was_stressed and not now_stressed:
            dur = ""
            if uid in self._stress_rise_start:
                dur = f" (was elevated for {time.time() - self._stress_rise_start[uid]:.1f}s)"
                del self._stress_rise_start[uid]
            self._emit("stress_resolved", uid,
                       f"{uid}'s stress returned to normal{dur}",
                       {"stress_level": round(state.stress_level, 2)})

        # High stress sustained warning
        if state.stress_level > 0.7 and uid in self._stress_rise_start:
            dur = time.time() - self._stress_rise_start[uid]
            if dur > 5 and int(dur) % 5 == 0:  # every 5s
                self._emit("stress_sustained", uid,
                           f"{uid} has been highly stressed for {dur:.0f}s (level={state.stress_level:.2f})",
                           {"stress_level": round(state.stress_level, 2), "duration_s": round(dur, 1)})

        self._was_stressed[uid] = now_stressed

        # --- Overload transitions ---
        was_overloaded = self._was_overloaded.get(uid, False)
        if state.overloaded and not was_overloaded:
            self._emit("overloaded", uid,
                       f"{uid} is overloaded (stress={state.stress_level:.2f}, arousal={state.arousal:.2f})",
                       {"stress_level": round(state.stress_level, 2), "arousal": round(state.arousal, 2)})
        elif was_overloaded and not state.overloaded:
            self._emit("overload_resolved", uid, f"{uid} is no longer overloaded")
        self._was_overloaded[uid] = state.overloaded

        # --- Mode changes ---
        last_mode = self._last_mode.get(uid)
        if last_mode and state.mode.value != last_mode:
            self._emit("mode_change", uid,
                       f"{uid} switched from {last_mode} to {state.mode.value} mode",
                       {"from": last_mode, "to": state.mode.value})
        self._last_mode[uid] = state.mode.value

        # --- Collar tap (immediate event, not a transition) ---
        if t == "collar_tap":
            tapper = signal.value.get("tapper_id", "someone")
            self._emit("collar_tap", uid,
                       f"{tapper} tapped {uid}'s collar",
                       {"tapper_id": tapper})

        # --- Engagement drop ---
        if t == "engagement_drop":
            self._emit("engagement_drop", uid,
                       f"{uid}'s engagement dropped (now {state.engagement:.2f})",
                       {"engagement": round(state.engagement, 2)})

        # --- Attention shift ---
        if t == "orientation_shift":
            direction = signal.value.get("direction", "unknown")
            self._emit("attention_shift", uid,
                       f"{uid} shifted attention {direction}",
                       {"direction": direction})

    # ------------------------------------------------------------------ #
    #  Action handler — log what the OS decided to do                     #
    # ------------------------------------------------------------------ #

    async def _on_action(self, action: Action):
        if action.action_type in ("show_overlay", "remove_overlay"):
            target = action.payload.get("target", "unknown")
            reason = action.payload.get("reason", "")
            enabled = action.payload.get("enabled")
            verb = "shown" if enabled else "hidden"
            self._emit("overlay_toggle", action.target_user,
                       f"{target}'s overlay {verb} for {action.target_user} ({reason})",
                       {"target": target, "enabled": enabled, "reason": reason})
        elif action.action_type == "haptic":
            reason = action.payload.get("reason", "")
            pattern = action.payload.get("pattern", "")
            self._emit("haptic_sent", action.target_user,
                       f"haptic '{pattern}' sent to {action.target_user} ({reason})",
                       {"pattern": pattern, "reason": reason,
                        "intensity": action.payload.get("intensity")})
        elif action.action_type == "suppress":
            self._emit("suppress", action.target_user,
                       f"UI suppressed for {action.target_user} (overloaded)",
                       {"reason": action.payload.get("reason", "")})
        elif action.action_type == "highlight":
            target = action.payload.get("target", "")
            self._emit("highlight", action.target_user,
                       f"highlighting {target} for {action.target_user} (about to speak)",
                       {"target": target})

    # ------------------------------------------------------------------ #
    #  Query API                                                          #
    # ------------------------------------------------------------------ #

    def recent(self, limit: int = 30, user: str | None = None) -> list[dict]:
        """Get recent events as dicts, optionally filtered by user."""
        events = list(self._events)
        if user:
            events = [e for e in events if e.user == user]
        return [e.to_dict() for e in events[-limit:]]

    def narrative(self, limit: int = 20, user: str | None = None) -> str:
        """Get a plain-text narrative of recent events for LLM context.

        Returns a compact summary like:
          [2.1s ago] alice started speaking (intent was rising for 1.5s)
          [0.3s ago] someone tapped bob's collar
        """
        events = self.recent(limit=limit, user=user)
        if not events:
            return "No significant events yet."
        lines = []
        for e in events:
            lines.append(f"[{e['age']}s ago] {e['detail']}")
        return "\n".join(lines)

    def for_llm(self, limit: int = 20) -> dict:
        """Build a structured context dict ready for LLM consumption.

        Combines current user states with the event narrative.
        """
        states = estimator.all_states()
        now = time.time()
        return {
            "timestamp": now,
            "users": {
                s.user_id: {
                    "mode": s.mode.value,
                    "speech_active": s.speech_active,
                    "speech_intent": round(s.speech_intent, 2),
                    "stress_level": round(s.stress_level, 2),
                    "engagement": round(s.engagement, 2),
                    "arousal": round(s.arousal, 2),
                    "attention_direction": s.attention_direction,
                    "overloaded": s.overloaded,
                    "hidden_overlays": sorted(s.hidden_overlays),
                }
                for s in states
            },
            "num_users": len(states),
            "recent_events": self.recent(limit=limit),
            "narrative": self.narrative(limit=limit),
        }

    def reset(self):
        """Clear all events and tracking state. For tests."""
        self._events.clear()
        self._was_speaking.clear()
        self._was_about_to_speak.clear()
        self._was_stressed.clear()
        self._was_overloaded.clear()
        self._stress_rise_start.clear()
        self._speech_intent_rise_start.clear()
        self._last_mode.clear()


# Singleton
context_log = ContextLog()
