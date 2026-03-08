"""State Estimator — fuses signals into per-user body-state estimates.

Continuously updated model of each user's embodied state.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum

from delightfulos.os.types import Signal

log = logging.getLogger("delightfulos.state")


class UserMode(str, Enum):
    SOCIAL = "social"           # full mediation (default)
    FOCUS = "focus"             # suppress social cues, only critical alerts
    MINIMAL = "minimal"         # haptic-only, no AR overlays
    CALIBRATION = "calibration" # learning baseline


@dataclass
class BodyState:
    user_id: str

    # Mode
    mode: UserMode = UserMode.SOCIAL

    # Speech / communication
    speech_intent: float = 0.0
    speech_active: bool = False
    last_speech_time: float = 0.0

    # Arousal / stress
    stress_level: float = 0.0
    arousal: float = 0.5

    # Engagement
    engagement: float = 0.5
    attention_direction: str = "forward"

    # Physical
    posture_quality: float = 0.5
    breathing_rate: float = 0.0
    breathing_phase: str = "unknown"

    # Composite
    interaction_ready: bool = False
    overloaded: bool = False

    # Metadata
    last_updated: float = field(default_factory=time.time)
    signal_count: int = 0

    def to_dict(self) -> dict:
        return {
            "user_id": self.user_id,
            "mode": self.mode.value,
            "speech_intent": round(self.speech_intent, 2),
            "speech_active": self.speech_active,
            "stress_level": round(self.stress_level, 2),
            "arousal": round(self.arousal, 2),
            "engagement": round(self.engagement, 2),
            "attention_direction": self.attention_direction,
            "posture_quality": round(self.posture_quality, 2),
            "breathing_rate": round(self.breathing_rate, 1),
            "breathing_phase": self.breathing_phase,
            "interaction_ready": self.interaction_ready,
            "overloaded": self.overloaded,
            "last_updated": self.last_updated,
            "signal_count": self.signal_count,
        }


class StateEstimator:

    def __init__(self, decay: float = 0.92):
        self._states: dict[str, BodyState] = {}
        self._decay = decay

    def get(self, user_id: str) -> BodyState:
        if user_id not in self._states:
            self._states[user_id] = BodyState(user_id=user_id)
        return self._states[user_id]

    def all_states(self) -> list[BodyState]:
        return list(self._states.values())

    def set_mode(self, user_id: str, mode: UserMode):
        state = self.get(user_id)
        old_mode = state.mode
        state.mode = mode
        log.info("Mode change: %s %s -> %s", user_id, old_mode.value, mode.value)

    def update(self, signal: Signal):
        state = self.get(signal.source_user)

        # Decay based on time since PREVIOUS update (not current one)
        prev_updated = state.last_updated
        state.last_updated = time.time()
        state.signal_count += 1

        t = signal.signal_type
        c = signal.confidence

        # Mode toggle via touch (double-tap cycles modes)
        if t == "mode_change":
            mode_str = signal.value.get("mode", "social")
            try:
                state.mode = UserMode(mode_str)
                log.info("Mode change via signal: %s -> %s", signal.source_user, mode_str)
            except ValueError:
                log.warning("Invalid mode in signal: %s", mode_str)
            return

        if t == "about_to_speak":
            state.speech_intent = max(state.speech_intent, c)
            state.interaction_ready = True
        elif t == "speaking":
            state.speech_active = True
            state.speech_intent = 1.0
            state.last_speech_time = signal.timestamp
        elif t == "speaking_confirmed":
            state.speech_active = True
            state.speech_intent = 1.0
            state.last_speech_time = signal.timestamp
        elif t == "speech_ended":
            state.speech_active = False
            state.speech_intent *= self._decay
        elif t == "stress_high":
            state.stress_level = max(state.stress_level, c)
            state.overloaded = state.stress_level > 0.7 and state.arousal > 0.6
        elif t == "stress_low":
            state.stress_level *= self._decay
        elif t == "engagement_drop":
            state.engagement = min(state.engagement, 1.0 - c)
        elif t == "engagement_rise":
            state.engagement = max(state.engagement, c)
        elif t == "orientation_shift":
            state.attention_direction = signal.value.get("direction", "forward")
        elif t == "breathing_change":
            pattern = signal.value.get("pattern", "unknown")
            state.breathing_phase = pattern
            if pattern == "rapid":
                state.arousal = min(1.0, state.arousal + 0.1)
            elif pattern == "deep":
                state.arousal = max(0.0, state.arousal - 0.1)
            rate = signal.value.get("rate")
            if rate is not None:
                state.breathing_rate = rate
        elif t == "touch":
            state.interaction_ready = True
        elif t == "posture":
            state.posture_quality = signal.value.get("quality", 0.5)

        self._apply_decay(state, prev_updated)

    def _apply_decay(self, state: BodyState, prev_updated: float):
        """Decay stale values based on time since previous signal."""
        age = time.time() - prev_updated
        if age > 2.0:
            state.speech_intent *= self._decay
            if state.speech_intent < 0.05:
                state.speech_intent = 0.0
                state.interaction_ready = False
            state.stress_level *= self._decay
            state.engagement = 0.5 + (state.engagement - 0.5) * self._decay
            state.overloaded = state.stress_level > 0.7 and state.arousal > 0.6

    def reset(self):
        """Clear all states. For tests only."""
        self._states.clear()


# Singleton
estimator = StateEstimator()
