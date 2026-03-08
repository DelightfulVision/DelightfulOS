"""Policy Engine — decides what actions to take given estimated user state.

Three layers:
  1. Rule-based policies (fast, deterministic, no LLM call)
  2. Turn-taking resolution (who speaks next when multiple users want to)
  3. Mode filtering (suppress actions based on user's current mode)

Plus signal-reactive policies for immediate event-driven responses
(collar taps, gestures, etc.) that shouldn't wait for the 200ms batch window.
"""
from __future__ import annotations

from delightfulos.os.types import Signal, Action
from delightfulos.os.state import BodyState, UserMode


def evaluate_rules(states: dict[str, BodyState]) -> list[Action]:
    """Fast rule-based policy evaluation. No LLM calls.

    Returns mode-filtered actions ready for routing.
    """
    actions = []

    for user_id, state in states.items():
        other_users = {uid: s for uid, s in states.items() if uid != user_id}

        # Skip users in calibration mode
        if state.mode == UserMode.CALIBRATION:
            continue

        # --- Overload protection (fires in all modes) ---
        if state.overloaded:
            actions.append(Action(
                target_user=user_id,
                target_type="glasses",
                action_type="suppress",
                payload={"reason": "overloaded", "reduce_to": "minimal"},
            ))

        # --- Turn-taking (social mode only) ---
        if state.mode == UserMode.SOCIAL:
            _turn_taking(user_id, state, other_users, actions)

        # --- Engagement nudge (social + minimal) ---
        if state.mode in (UserMode.SOCIAL, UserMode.MINIMAL):
            if state.engagement < 0.3:
                for other_id, other_state in other_users.items():
                    if other_state.speech_active:
                        actions.append(Action(
                            target_user=user_id,
                            target_type="collar",
                            action_type="haptic",
                            payload={
                                "direction": "front",
                                "pattern": "pulse",
                                "intensity": 0.3,
                                "reason": "re_engage",
                            },
                        ))
                        break

        # --- Stress reduction (all modes except calibration) ---
        if state.stress_level > 0.6:
            actions.append(Action(
                target_user=user_id,
                action_type="config",
                payload={"haptic_intensity_scale": 0.5, "reason": "stress_reduction"},
            ))

        # --- Breathing guide (social + minimal) ---
        if state.mode in (UserMode.SOCIAL, UserMode.MINIMAL):
            if state.breathing_phase == "rapid" and state.arousal > 0.7:
                actions.append(Action(
                    target_user=user_id,
                    target_type="collar",
                    action_type="haptic",
                    payload={
                        "direction": "front",
                        "pattern": "slow_pulse",
                        "intensity": 0.4,
                        "reason": "breathing_guide",
                    },
                ))

    return actions


def _turn_taking(
    user_id: str,
    state: BodyState,
    other_users: dict[str, BodyState],
    actions: list[Action],
):
    """Resolve who gets the 'about to speak' highlight when multiple users compete.

    Rules:
      - If someone is already speaking, don't highlight another about-to-speaker
        (wait for the current speaker to finish)
      - If multiple users are about to speak, highlight the one with higher intent
        and give the other a gentle 'yield' haptic
      - If only one user is about to speak, highlight normally
    """
    if not (state.speech_intent > 0.7 and not state.speech_active):
        return

    # Is anyone already speaking?
    anyone_speaking = any(s.speech_active for s in other_users.values())
    if anyone_speaking:
        # Don't highlight about-to-speak while someone is talking
        # Instead, give a subtle "wait" signal
        actions.append(Action(
            target_user=user_id,
            target_type="collar",
            action_type="haptic",
            payload={
                "direction": "front",
                "pattern": "pulse",
                "intensity": 0.15,
                "reason": "wait_turn",
            },
        ))
        return

    # Are other users also about to speak?
    competing = [
        (uid, s) for uid, s in other_users.items()
        if s.speech_intent > 0.7 and not s.speech_active and s.mode == UserMode.SOCIAL
    ]

    if competing:
        # Multiple users want to speak — who has priority?
        # Priority: higher speech_intent, tiebreak by earlier last_speech_time
        # (person who spoke least recently gets priority)
        my_priority = (state.speech_intent, -state.last_speech_time)
        for other_id, other_state in competing:
            their_priority = (other_state.speech_intent, -other_state.last_speech_time)
            if their_priority >= my_priority:
                # Other user has priority — yield
                actions.append(Action(
                    target_user=user_id,
                    target_type="collar",
                    action_type="haptic",
                    payload={
                        "direction": "front",
                        "pattern": "pulse",
                        "intensity": 0.2,
                        "reason": "yield_turn",
                    },
                ))
                return

    # This user gets to speak — highlight for everyone else
    for other_id, other_state in other_users.items():
        if other_state.mode == UserMode.FOCUS:
            continue  # don't send social highlights to focus-mode users
        actions.append(Action(
            target_user=other_id,
            target_type="glasses",
            action_type="highlight",
            payload={
                "target": user_id,
                "type": "halo",
                "color": "#FFD700",
                "reason": "about_to_speak",
            },
        ))


# ------------------------------------------------------------------ #
#  Signal-reactive policies (immediate, not batched)                  #
# ------------------------------------------------------------------ #

# Signal types that trigger immediate actions
_REACTIVE_SIGNALS = {"collar_tap"}


def evaluate_signal(signal: Signal, all_states: dict[str, BodyState]) -> list[Action]:
    """Immediate signal-reactive policy evaluation.

    Unlike evaluate_rules() which runs on batched state, this fires per-signal
    for event-driven interactions (taps, gestures) that need low latency.
    """
    if signal.signal_type not in _REACTIVE_SIGNALS:
        return []

    if signal.signal_type == "collar_tap":
        return _handle_collar_tap(signal, all_states)

    return []


def _handle_collar_tap(signal: Signal, all_states: dict[str, BodyState]) -> list[Action]:
    """Collar tap: toggles AR overlay visibility over the tapped person.

    The collar is a physical interface that others can interact with.
    Tapping someone's collar controls what AR overlays appear over that person.

    On first tap: cube over tapped_user is HIDDEN for all other viewers.
    On second tap: cube is SHOWN again (toggle).

    The signal value may include tapper_id (who physically did the tap).
    Broadcast payload includes: tapped_user, tapper_id, enabled (0/1).
    """
    tapped_user = signal.source_user
    tapper_id = signal.value.get("tapper_id")
    actions = []

    for other_id, other_state in all_states.items():
        if other_id == tapped_user:
            continue
        if other_state.mode == UserMode.CALIBRATION:
            continue

        # Toggle: if currently hidden -> show (enable=1), else hide (enable=0)
        if tapped_user in other_state.hidden_overlays:
            other_state.hidden_overlays.discard(tapped_user)
            enabled = 1
            action_type = "show_overlay"
        else:
            other_state.hidden_overlays.add(tapped_user)
            enabled = 0
            action_type = "remove_overlay"

        actions.append(Action(
            target_user=other_id,
            target_type="glasses",
            action_type=action_type,
            payload={
                "target": tapped_user,
                "tapper_id": tapper_id or "unknown",
                "type": "cube",
                "enabled": enabled,
                "reason": "collar_tap",
            },
        ))

    return actions
