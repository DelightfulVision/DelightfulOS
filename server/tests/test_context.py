"""Context Log tests — verifies structured event generation from raw signals.

Tests that the ContextLog correctly:
  1. Detects speech start/end transitions
  2. Detects intent rising
  3. Detects stress rising/resolved
  4. Detects collar taps
  5. Detects overload transitions
  6. Detects mode changes
  7. Produces correct narrative output
  8. Produces correct for_llm() structure

No API keys or network needed — pure in-memory computation.
Run: cd server && uv run python -m tests.test_context
"""
import asyncio
import time

from delightfulos.os.types import Signal, Action
from delightfulos.os.bus import bus
from delightfulos.os.state import estimator, BodyState, UserMode
from delightfulos.os.registry import registry
from delightfulos.ai.context import ContextLog


def reset_all():
    bus.reset()
    estimator.reset()
    registry.reset()


def make_signal(user: str, stype: str, confidence: float = 0.9, value: dict | None = None) -> Signal:
    return Signal(
        source_device=f"test_{user}",
        source_user=user,
        signal_type=stype,
        confidence=confidence,
        value=value or {},
    )


# ================================================================
# 1. Speech transitions
# ================================================================

def test_speech_transitions():
    print("=== 1. Speech start/end transitions ===")
    reset_all()
    ctx = ContextLog()

    # Manually set user state to speaking
    state = estimator.get("alice")
    state.speech_active = True
    sig = make_signal("alice", "speaking")

    asyncio.get_event_loop().run_until_complete(ctx._on_signal(sig))
    events = ctx.recent()
    speech_starts = [e for e in events if e["event"] == "speech_start"]
    assert len(speech_starts) == 1, f"Expected 1 speech_start, got {len(speech_starts)}"
    assert speech_starts[0]["user"] == "alice"
    print(f"  speech_start: {speech_starts[0]['detail']}")

    # Now stop speaking
    state.speech_active = False
    sig2 = make_signal("alice", "idle")
    asyncio.get_event_loop().run_until_complete(ctx._on_signal(sig2))
    events = ctx.recent()
    speech_ends = [e for e in events if e["event"] == "speech_end"]
    assert len(speech_ends) == 1, f"Expected 1 speech_end, got {len(speech_ends)}"
    print(f"  speech_end: {speech_ends[0]['detail']}")
    print("  PASS\n")


# ================================================================
# 2. Intent rising
# ================================================================

def test_intent_rising():
    print("=== 2. Intent rising ===")
    reset_all()
    ctx = ContextLog()

    state = estimator.get("bob")
    state.speech_intent = 0.6
    state.speech_active = False
    sig = make_signal("bob", "about_to_speak")

    asyncio.get_event_loop().run_until_complete(ctx._on_signal(sig))
    events = ctx.recent()
    intents = [e for e in events if e["event"] == "intent_rising"]
    assert len(intents) == 1, f"Expected 1 intent_rising, got {len(intents)}"
    assert intents[0]["user"] == "bob"
    print(f"  intent_rising: {intents[0]['detail']}")
    print("  PASS\n")


# ================================================================
# 3. Stress transitions
# ================================================================

def test_stress_transitions():
    print("=== 3. Stress rising/resolved ===")
    reset_all()
    ctx = ContextLog()

    state = estimator.get("alice")
    state.stress_level = 0.5
    sig = make_signal("alice", "stress_high")
    asyncio.get_event_loop().run_until_complete(ctx._on_signal(sig))

    events = ctx.recent()
    rising = [e for e in events if e["event"] == "stress_rising"]
    assert len(rising) == 1, f"Expected 1 stress_rising, got {len(rising)}"
    print(f"  stress_rising: {rising[0]['detail']}")

    # Resolve stress
    state.stress_level = 0.2
    sig2 = make_signal("alice", "idle")
    asyncio.get_event_loop().run_until_complete(ctx._on_signal(sig2))

    events = ctx.recent()
    resolved = [e for e in events if e["event"] == "stress_resolved"]
    assert len(resolved) == 1, f"Expected 1 stress_resolved, got {len(resolved)}"
    print(f"  stress_resolved: {resolved[0]['detail']}")
    print("  PASS\n")


# ================================================================
# 4. Collar tap
# ================================================================

def test_collar_tap():
    print("=== 4. Collar tap ===")
    reset_all()
    ctx = ContextLog()

    sig = make_signal("alice", "collar_tap", value={"tapper_id": "bob"})
    asyncio.get_event_loop().run_until_complete(ctx._on_signal(sig))

    events = ctx.recent()
    taps = [e for e in events if e["event"] == "collar_tap"]
    assert len(taps) == 1, f"Expected 1 collar_tap, got {len(taps)}"
    assert taps[0]["data"]["tapper_id"] == "bob"
    print(f"  collar_tap: {taps[0]['detail']}")
    print("  PASS\n")


# ================================================================
# 5. Overload transitions
# ================================================================

def test_overload():
    print("=== 5. Overload transitions ===")
    reset_all()
    ctx = ContextLog()

    state = estimator.get("bob")
    state.overloaded = True
    state.stress_level = 0.8
    state.arousal = 0.9
    sig = make_signal("bob", "stress_high")
    asyncio.get_event_loop().run_until_complete(ctx._on_signal(sig))

    events = ctx.recent()
    overloads = [e for e in events if e["event"] == "overloaded"]
    assert len(overloads) == 1, f"Expected 1 overloaded, got {len(overloads)}"
    print(f"  overloaded: {overloads[0]['detail']}")

    # Resolve
    state.overloaded = False
    state.stress_level = 0.3
    sig2 = make_signal("bob", "idle")
    asyncio.get_event_loop().run_until_complete(ctx._on_signal(sig2))

    events = ctx.recent()
    resolved = [e for e in events if e["event"] == "overload_resolved"]
    assert len(resolved) == 1
    print(f"  overload_resolved: {resolved[0]['detail']}")
    print("  PASS\n")


# ================================================================
# 6. Mode changes
# ================================================================

def test_mode_change():
    print("=== 6. Mode changes ===")
    reset_all()
    ctx = ContextLog()

    state = estimator.get("alice")
    state.mode = UserMode.SOCIAL

    # First signal sets the initial mode (no event yet)
    sig = make_signal("alice", "idle")
    asyncio.get_event_loop().run_until_complete(ctx._on_signal(sig))
    events = ctx.recent()
    mode_changes = [e for e in events if e["event"] == "mode_change"]
    assert len(mode_changes) == 0, "No mode_change on first signal"

    # Change mode
    state.mode = UserMode.FOCUS
    sig2 = make_signal("alice", "idle")
    asyncio.get_event_loop().run_until_complete(ctx._on_signal(sig2))
    events = ctx.recent()
    mode_changes = [e for e in events if e["event"] == "mode_change"]
    assert len(mode_changes) == 1
    assert mode_changes[0]["data"]["from"] == "social"
    assert mode_changes[0]["data"]["to"] == "focus"
    print(f"  mode_change: {mode_changes[0]['detail']}")
    print("  PASS\n")


# ================================================================
# 7. Action handler (overlay toggle)
# ================================================================

def test_action_handler():
    print("=== 7. Action handler (overlay toggle) ===")
    reset_all()
    ctx = ContextLog()

    action = Action(
        target_user="alice",
        action_type="show_overlay",
        payload={"target": "bob", "reason": "about to speak", "enabled": True},
    )
    asyncio.get_event_loop().run_until_complete(ctx._on_action(action))

    events = ctx.recent()
    toggles = [e for e in events if e["event"] == "overlay_toggle"]
    assert len(toggles) == 1
    assert toggles[0]["data"]["target"] == "bob"
    assert toggles[0]["data"]["enabled"] == True
    print(f"  overlay_toggle: {toggles[0]['detail']}")

    # Haptic action
    action2 = Action(
        target_user="bob",
        action_type="haptic",
        payload={"pattern": "pulse", "reason": "attention", "intensity": 0.5},
    )
    asyncio.get_event_loop().run_until_complete(ctx._on_action(action2))
    events = ctx.recent()
    haptics = [e for e in events if e["event"] == "haptic_sent"]
    assert len(haptics) == 1
    print(f"  haptic_sent: {haptics[0]['detail']}")
    print("  PASS\n")


# ================================================================
# 8. Narrative output
# ================================================================

def test_narrative():
    print("=== 8. Narrative output ===")
    reset_all()
    ctx = ContextLog()

    # Generate a few events
    state = estimator.get("alice")
    state.speech_active = True
    asyncio.get_event_loop().run_until_complete(
        ctx._on_signal(make_signal("alice", "speaking")))

    state.speech_active = False
    asyncio.get_event_loop().run_until_complete(
        ctx._on_signal(make_signal("alice", "idle")))

    narrative = ctx.narrative()
    assert "alice started speaking" in narrative
    assert "alice stopped speaking" in narrative
    print(f"  Narrative:\n    {narrative.replace(chr(10), chr(10) + '    ')}")

    # Filtered narrative
    filtered = ctx.narrative(user="bob")
    assert filtered == "No significant events yet."
    print("  Filtered (bob): correctly empty")
    print("  PASS\n")


# ================================================================
# 9. for_llm() structure
# ================================================================

def test_for_llm():
    print("=== 9. for_llm() structure ===")
    reset_all()
    ctx = ContextLog()

    state = estimator.get("alice")
    state.mode = UserMode.SOCIAL
    state.speech_active = True
    state.speech_intent = 0.8

    asyncio.get_event_loop().run_until_complete(
        ctx._on_signal(make_signal("alice", "speaking")))

    llm_ctx = ctx.for_llm()
    assert "timestamp" in llm_ctx
    assert "users" in llm_ctx
    assert "alice" in llm_ctx["users"]
    assert "recent_events" in llm_ctx
    assert "narrative" in llm_ctx
    assert llm_ctx["num_users"] >= 1

    alice_state = llm_ctx["users"]["alice"]
    assert alice_state["speech_active"] == True
    assert alice_state["mode"] == "social"
    print(f"  LLM context keys: {list(llm_ctx.keys())}")
    print(f"  Alice state: speech_active={alice_state['speech_active']}, mode={alice_state['mode']}")
    print(f"  Events: {len(llm_ctx['recent_events'])}")
    print("  PASS\n")


# ================================================================
# 10. No duplicate events on repeated signals
# ================================================================

def test_no_duplicates():
    print("=== 10. No duplicate events on repeated signals ===")
    reset_all()
    ctx = ContextLog()

    state = estimator.get("alice")
    state.speech_active = True

    # Send the same signal 5 times — should only get 1 speech_start
    for _ in range(5):
        asyncio.get_event_loop().run_until_complete(
            ctx._on_signal(make_signal("alice", "speaking")))

    events = ctx.recent()
    speech_starts = [e for e in events if e["event"] == "speech_start"]
    assert len(speech_starts) == 1, f"Expected 1 speech_start, got {len(speech_starts)} (dedup failed)"
    print(f"  5 signals -> {len(speech_starts)} speech_start event (correct)")
    print("  PASS\n")


# ================================================================
# 11. Reset clears everything
# ================================================================

def test_reset():
    print("=== 11. Reset ===")
    reset_all()
    ctx = ContextLog()

    state = estimator.get("alice")
    state.speech_active = True
    asyncio.get_event_loop().run_until_complete(
        ctx._on_signal(make_signal("alice", "speaking")))
    assert len(ctx.recent()) > 0

    ctx.reset()
    assert len(ctx.recent()) == 0
    print("  Reset cleared all events")
    print("  PASS\n")


# ================================================================
# Run all
# ================================================================

if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("  Context Log Tests")
    print("=" * 60 + "\n")

    test_speech_transitions()
    test_intent_rising()
    test_stress_transitions()
    test_collar_tap()
    test_overload()
    test_mode_change()
    test_action_handler()
    test_narrative()
    test_for_llm()
    test_no_duplicates()
    test_reset()

    print("=" * 60)
    print("  ALL 11 CONTEXT LOG TESTS PASSED")
    print("=" * 60)
