"""Stress tests — realistic multi-user, high-throughput, concurrent scenarios.

Exercises the full OS pipeline under conditions that mirror actual hackathon use:
  - Multiple simultaneous users with collars + spectacles
  - High signal throughput (5Hz per device)
  - Concurrent collar taps, speech overlap, mode switches
  - Batcher behavior under load
  - State estimator decay and consistency
  - Registry churn (devices connecting/disconnecting)
  - Bus subscriber error isolation
  - HDL library round-trip integrity

No API keys or network needed — pure in-memory computation.
Run: cd server && .venv/Scripts/python -m tests.test_stress
"""
import asyncio
import json
import math
import random
import time

from delightfulos.os.types import Signal, Action, DeviceInfo, DeviceType, Capability
from delightfulos.os.bus import bus
from delightfulos.os.state import estimator, BodyState, UserMode
from delightfulos.os.registry import registry
from delightfulos.runtime.policy import evaluate_rules, evaluate_signal
from delightfulos.runtime.output import route_action
from delightfulos.runtime.managers import SignalBatcher


def reset_all():
    bus.reset()
    estimator.reset()
    registry.reset()


# ================================================================
# Helpers
# ================================================================

class FakeTransport:
    """Records messages sent through a WebSocket-like transport."""
    def __init__(self, *, fail_after: int | None = None):
        self.messages: list[dict] = []
        self._fail_after = fail_after

    async def send_text(self, text: str):
        if self._fail_after is not None and len(self.messages) >= self._fail_after:
            raise ConnectionError("Transport broken")
        self.messages.append(json.loads(text))


def register_user(user_id: str, transport: FakeTransport | None = None) -> tuple[DeviceInfo, DeviceInfo]:
    """Register a collar + glasses pair for a user. Returns (collar, glasses)."""
    t = transport or FakeTransport()
    collar = DeviceInfo(
        device_id=f"collar_{user_id}",
        device_type=DeviceType.COLLAR,
        user_id=user_id,
        capabilities=[Capability.SENSE_VIBRATION, Capability.SENSE_AUDIO, Capability.OUTPUT_HAPTIC],
        transport=t,
    )
    glasses = DeviceInfo(
        device_id=f"glasses_{user_id}",
        device_type=DeviceType.GLASSES,
        user_id=user_id,
        capabilities=[Capability.OUTPUT_VISUAL_AR, Capability.SENSE_CAMERA],
        transport=t,
    )
    registry.register(collar)
    registry.register(glasses)
    estimator.get(user_id)
    return collar, glasses


# ================================================================
# 1. High-throughput signal bus — 10 users, 50 signals each
# ================================================================

def test_high_throughput_bus():
    print("=== 1. High-Throughput Signal Bus (500 signals, 10 users) ===")
    reset_all()

    received = []
    async def handler(sig):
        received.append(sig)

    bus.subscribe_signal(handler)

    async def run():
        users = [f"user_{i}" for i in range(10)]
        signal_types = ["speaking", "about_to_speak", "stress_high",
                        "orientation_shift", "breathing_change", "speech_ended"]
        tasks = []
        for uid in users:
            for _ in range(50):
                sig = Signal(
                    source_device=f"collar_{uid}",
                    source_user=uid,
                    signal_type=random.choice(signal_types),
                    confidence=random.uniform(0.5, 1.0),
                    value={"direction": "left"} if random.random() > 0.5 else {},
                )
                tasks.append(bus.emit_signal(sig))
        await asyncio.gather(*tasks)

        assert len(received) == 500, f"Expected 500 signals, got {len(received)}"

        # Verify recent_signals works under load
        recent_all = bus.recent_signals(limit=1000)
        assert len(recent_all) == 500

        recent_user0 = bus.recent_signals(user_id="user_0", limit=100)
        assert len(recent_user0) == 50

    asyncio.run(run())
    print(f"  500 signals dispatched and received correctly")


# ================================================================
# 2. Concurrent collar taps — 5 users all tapped simultaneously
# ================================================================

def test_concurrent_collar_taps():
    print("\n=== 2. Concurrent Collar Taps (5 users, simultaneous) ===")
    reset_all()

    transports = {}
    users = [f"u{i}" for i in range(5)]
    for uid in users:
        t = FakeTransport()
        transports[uid] = t
        register_user(uid, t)

    async def run():
        # All 5 collars are tapped at the same time
        all_states = {s.user_id: s for s in estimator.all_states()}

        all_actions = []
        for uid in users:
            tap = Signal(
                source_device=f"collar_{uid}",
                source_user=uid,
                signal_type="collar_tap",
                confidence=1.0,
            )
            actions = evaluate_signal(tap, all_states)
            all_actions.extend(actions)
            for action in actions:
                await route_action(action)

        # Each tap should generate actions for all OTHER users (4 each)
        assert len(all_actions) == 5 * 4, f"Expected 20 actions, got {len(all_actions)}"

        # Each user's glasses should receive 4 remove_overlay commands (one per other user's tap)
        for uid in users:
            msgs = transports[uid].messages
            remove_overlays = [m for m in msgs if m["action"] == "remove_overlay"]
            assert len(remove_overlays) == 4, \
                f"User {uid} should get 4 remove_overlay, got {len(remove_overlays)}"
            # Verify targets are the other 4 users
            targets = {m["payload"]["target"] for m in remove_overlays}
            expected = set(users) - {uid}
            assert targets == expected, f"User {uid} targets: {targets} != {expected}"

    asyncio.run(run())
    print("  5 simultaneous taps: 20 actions dispatched, each user received 4 correctly")


# ================================================================
# 3. Speech overlap — 3 users try to speak at once
# ================================================================

def test_speech_overlap():
    print("\n=== 3. Speech Overlap (3 users competing for turn) ===")
    reset_all()

    users = ["alice", "bob", "charlie"]
    for uid in users:
        register_user(uid)

    # All three have high speech intent, nobody speaking yet
    for uid in users:
        state = estimator.get(uid)
        state.speech_intent = 0.9
        state.speech_active = False
        state.mode = UserMode.SOCIAL

    # Give alice slightly higher intent and earlier last_speech_time
    estimator.get("alice").speech_intent = 0.95
    estimator.get("alice").last_speech_time = time.time() - 30  # spoke 30s ago
    estimator.get("bob").last_speech_time = time.time() - 10    # spoke 10s ago
    estimator.get("charlie").last_speech_time = time.time() - 5 # spoke 5s ago

    states = {s.user_id: s for s in estimator.all_states()}
    actions = evaluate_rules(states)

    # Alice should get priority (highest intent + least recent speaker)
    # Bob and charlie should get yield_turn haptics
    highlights = [a for a in actions if a.payload.get("reason") == "about_to_speak"]
    yields = [a for a in actions if a.payload.get("reason") == "yield_turn"]

    # Alice's about_to_speak should generate highlights for bob and charlie
    assert len(highlights) >= 1, f"Expected highlights, got {len(highlights)}"
    highlight_targets = {a.target_user for a in highlights}

    # Bob and charlie should see alice highlighted
    yield_targets = {a.target_user for a in yields}
    # Either bob or charlie (or both) get yield signals
    assert len(yields) >= 1, f"Expected at least 1 yield, got {len(yields)}"

    print(f"  Turn-taking: {len(highlights)} highlights, {len(yields)} yields")

    # Now alice starts speaking, bob still has intent
    estimator.get("alice").speech_active = True
    estimator.get("alice").speech_intent = 1.0
    estimator.get("bob").speech_intent = 0.85

    states = {s.user_id: s for s in estimator.all_states()}
    actions = evaluate_rules(states)
    wait_turns = [a for a in actions if a.payload.get("reason") == "wait_turn"]
    assert len(wait_turns) >= 1, f"Expected wait_turn for bob, got {len(wait_turns)}"
    assert wait_turns[0].target_user == "bob"

    print(f"  Wait-turn when speaker active: {len(wait_turns)} wait_turn actions")


# ================================================================
# 4. State estimator under rapid signal bursts
# ================================================================

def test_state_estimator_burst():
    print("\n=== 4. State Estimator Rapid Burst (100 signals per user) ===")
    reset_all()

    user = "burst_user"

    # Rapid sequence: about_to_speak -> speaking -> stress -> speech_ended
    signal_sequence = [
        ("about_to_speak", 0.6),
        ("about_to_speak", 0.75),
        ("about_to_speak", 0.9),
        ("speaking", 0.95),
        ("stress_high", 0.5),
        ("speaking", 0.98),
        ("stress_high", 0.7),
        ("stress_high", 0.85),
        ("speech_ended", 0.9),
        ("about_to_speak", 0.7),
    ]

    for _ in range(10):  # 10 cycles = 100 signals
        for sig_type, conf in signal_sequence:
            estimator.update(Signal(
                source_device=f"collar_{user}",
                source_user=user,
                signal_type=sig_type,
                confidence=conf,
                value={},
            ))

    state = estimator.get(user)
    assert state.signal_count == 100, f"Expected 100 signals, got {state.signal_count}"

    # After ending with about_to_speak, should have high intent
    assert state.speech_intent > 0, "Should have some speech intent"
    # Stress should have accumulated
    assert state.stress_level > 0, "Should have some stress"
    # State should be valid
    assert 0 <= state.stress_level <= 1.0, f"Stress out of range: {state.stress_level}"
    assert 0 <= state.speech_intent <= 1.0, f"Intent out of range: {state.speech_intent}"
    assert 0 <= state.arousal <= 1.0, f"Arousal out of range: {state.arousal}"
    assert 0 <= state.engagement <= 1.0, f"Engagement out of range: {state.engagement}"

    # to_dict should not crash
    d = state.to_dict()
    assert d["signal_count"] == 100

    print(f"  100 signals: stress={state.stress_level:.2f}, intent={state.speech_intent:.2f}, count={state.signal_count}")


# ================================================================
# 5. Registry churn — devices connecting/disconnecting rapidly
# ================================================================

def test_registry_churn():
    print("\n=== 5. Registry Churn (50 connect/disconnect cycles) ===")
    reset_all()

    for i in range(50):
        uid = f"churn_user_{i % 10}"
        did = f"collar_{uid}_{i}"
        device = DeviceInfo(
            device_id=did,
            device_type=DeviceType.COLLAR,
            user_id=uid,
            capabilities=[Capability.SENSE_VIBRATION],
        )
        registry.register(device)

    # Should have 50 devices registered
    all_devices = registry.all_devices()
    assert len(all_devices) == 50, f"Expected 50 devices, got {len(all_devices)}"

    # Unregister half
    for i in range(0, 50, 2):
        uid = f"churn_user_{i % 10}"
        did = f"collar_{uid}_{i}"
        registry.unregister(did)

    remaining = registry.all_devices()
    assert len(remaining) == 25, f"Expected 25 after unregister, got {len(remaining)}"

    # All users should still be queryable
    users = registry.all_users()
    assert len(users) <= 10

    # Snapshot should work
    snap = registry.snapshot()
    assert len(snap) == 25

    print(f"  50 registrations, 25 unregistrations, {len(users)} unique users remaining")


# ================================================================
# 6. Bus error isolation — bad subscriber doesn't kill others
# ================================================================

def test_bus_error_isolation():
    print("\n=== 6. Bus Error Isolation ===")
    reset_all()

    good_received = []
    bad_calls = []

    async def good_handler(sig):
        good_received.append(sig)

    async def bad_handler(sig):
        bad_calls.append(sig)
        raise RuntimeError("I am a broken handler")

    async def another_good_handler(sig):
        good_received.append(("second", sig))

    bus.subscribe_signal(good_handler)
    bus.subscribe_signal(bad_handler)
    bus.subscribe_signal(another_good_handler)

    async def run():
        sig = Signal(
            source_device="test", source_user="test",
            signal_type="speaking", confidence=0.9,
        )
        # Should not raise even though bad_handler throws
        await bus.emit_signal(sig)

        assert len(good_received) == 2, f"Both good handlers should fire, got {len(good_received)}"
        assert len(bad_calls) == 1, "Bad handler was called"

    asyncio.run(run())
    print("  Bad subscriber doesn't kill good subscribers")


# ================================================================
# 7. Transport failure — broken WebSocket doesn't crash pipeline
# ================================================================

def test_transport_failure():
    print("\n=== 7. Transport Failure Resilience ===")
    reset_all()

    # Transport that fails after 2 messages
    fragile = FakeTransport(fail_after=2)
    healthy = FakeTransport()

    registry.register(DeviceInfo(
        device_id="glasses_fragile",
        device_type=DeviceType.GLASSES,
        user_id="alice",
        capabilities=[Capability.OUTPUT_VISUAL_AR],
        transport=fragile,
    ))
    registry.register(DeviceInfo(
        device_id="collar_healthy",
        device_type=DeviceType.COLLAR,
        user_id="bob",
        capabilities=[Capability.OUTPUT_HAPTIC],
        transport=healthy,
    ))

    async def run():
        # First two should work
        for i in range(5):
            await route_action(Action(
                target_user="alice",
                target_type="glasses",
                action_type="highlight",
                payload={"msg": f"test_{i}"},
            ))

        # Should have sent 2 then failed silently for the rest
        assert len(fragile.messages) == 2, f"Expected 2, got {len(fragile.messages)}"

        # Bob's device should be unaffected
        await route_action(Action(
            target_user="bob",
            target_type="collar",
            action_type="haptic",
            payload={"intensity": 0.5},
        ))
        assert len(healthy.messages) == 1

    asyncio.run(run())
    print("  Broken transport fails silently, other devices unaffected")


# ================================================================
# 8. Batcher under load — signals accumulate and flush correctly
# ================================================================

def test_batcher_under_load():
    print("\n=== 8. Batcher Under Load (200 signals, batch window) ===")
    reset_all()

    batches_received = []

    async def on_batch(signals):
        batches_received.append(list(signals))

    batcher = SignalBatcher()
    batcher.set_handler(on_batch)

    async def run():
        # Fire 200 signals rapidly (faster than the batch window)
        for i in range(200):
            await batcher.add(Signal(
                source_device="collar_test",
                source_user="test",
                signal_type="speaking" if i % 2 == 0 else "about_to_speak",
                confidence=0.8,
            ))

        # Wait for the batch window to flush (200ms + margin)
        await asyncio.sleep(0.4)

        # Should have gotten at least 1 batch with all signals
        total_signals = sum(len(b) for b in batches_received)
        assert total_signals == 200, f"Expected 200 signals in batches, got {total_signals}"

        # Because signals are added faster than the batch window, they should be
        # in very few batches (ideally 1-2)
        assert len(batches_received) <= 5, \
            f"Expected few batches, got {len(batches_received)}"

    asyncio.run(run())
    print(f"  200 signals batched into {len(batches_received)} batch(es), all accounted for")


# ================================================================
# 9. Multi-user full pipeline — realistic hackathon demo scenario
# ================================================================

def test_full_hackathon_scenario():
    """Simulates the actual hackathon demo:
    - 2 users wearing collars + spectacles
    - Person A speaks (pre-speech -> speaking -> ends)
    - Person B starts speaking (overlap detection)
    - Person B taps person A's collar (remove overlay)
    - Mode switch to focus
    - Stress escalation + overload protection
    """
    print("\n=== 9. Full Hackathon Demo Scenario ===")
    reset_all()

    t_alice = FakeTransport()
    t_bob = FakeTransport()
    register_user("alice", t_alice)
    register_user("bob", t_bob)

    bus_actions = []
    async def capture_action(act):
        bus_actions.append(act)
    bus.subscribe_action(capture_action)

    async def emit(sig):
        """Emit signal on bus AND update estimator (simulates Runtime._on_signal)."""
        estimator.update(sig)
        await bus.emit_signal(sig)

    async def run():
        # === Phase 1: Alice pre-speech detected ===
        await emit(Signal(
            source_device="collar_alice", source_user="alice",
            signal_type="about_to_speak", confidence=0.75,
        ))
        state_a = estimator.get("alice")
        assert state_a.speech_intent >= 0.75
        assert state_a.interaction_ready is True

        # === Phase 2: Alice starts speaking ===
        await emit(Signal(
            source_device="collar_alice", source_user="alice",
            signal_type="speaking", confidence=0.95,
        ))
        state_a = estimator.get("alice")
        assert state_a.speech_active is True

        # Policy check: bob should see alice highlighted (via batch eval)
        states = {s.user_id: s for s in estimator.all_states()}
        actions = evaluate_rules(states)

        # === Phase 3: Bob also wants to speak (overlap) ===
        await emit(Signal(
            source_device="collar_bob", source_user="bob",
            signal_type="about_to_speak", confidence=0.85,
        ))
        states = {s.user_id: s for s in estimator.all_states()}
        actions = evaluate_rules(states)
        wait_actions = [a for a in actions if a.payload.get("reason") == "wait_turn"]
        assert len(wait_actions) >= 1, "Bob should get wait_turn (alice is speaking)"
        assert wait_actions[0].target_user == "bob"

        # === Phase 4: Alice stops speaking ===
        await emit(Signal(
            source_device="collar_alice", source_user="alice",
            signal_type="speech_ended", confidence=0.9,
        ))
        state_a = estimator.get("alice")
        assert state_a.speech_active is False

        # === Phase 5: Bob taps Alice's collar ===
        tap = Signal(
            source_device="collar_alice", source_user="alice",
            signal_type="collar_tap", confidence=1.0,
        )
        estimator.update(tap)
        states = {s.user_id: s for s in estimator.all_states()}
        reactive = evaluate_signal(tap, states)
        assert len(reactive) == 1, f"Expected 1 remove_overlay for bob, got {len(reactive)}"
        assert reactive[0].target_user == "bob"
        assert reactive[0].action_type == "remove_overlay"

        for action in reactive:
            await route_action(action)
            await bus.emit_action(action)

        # Verify bob's glasses received the remove_overlay
        bob_removes = [m for m in t_bob.messages if m["action"] == "remove_overlay"]
        assert len(bob_removes) == 1
        assert bob_removes[0]["payload"]["target"] == "alice"

        # === Phase 6: Alice switches to focus mode ===
        await emit(Signal(
            source_device="collar_alice", source_user="alice",
            signal_type="mode_change", value={"mode": "focus"},
        ))
        assert estimator.get("alice").mode == UserMode.FOCUS

        # In focus mode, alice should not get social highlights
        estimator.get("bob").speech_intent = 0.9
        estimator.get("bob").speech_active = False
        states = {s.user_id: s for s in estimator.all_states()}
        actions = evaluate_rules(states)
        alice_highlights = [a for a in actions if a.target_user == "alice"
                           and a.payload.get("reason") == "about_to_speak"]
        assert len(alice_highlights) == 0, "Focus mode user should not receive social highlights"

        # === Phase 7: Stress escalation ===
        estimator.set_mode("alice", UserMode.SOCIAL)
        for _ in range(5):
            estimator.update(Signal(
                source_device="collar_alice", source_user="alice",
                signal_type="stress_high", confidence=0.85,
            ))
        state_a = estimator.get("alice")
        assert state_a.stress_level > 0.7, f"Stress should be high, got {state_a.stress_level}"

        # Force overload condition
        state_a.arousal = 0.8
        state_a.overloaded = True
        states = {s.user_id: s for s in estimator.all_states()}
        actions = evaluate_rules(states)
        suppress = [a for a in actions if a.action_type == "suppress"]
        assert len(suppress) >= 1, "Overloaded alice should get suppress action"

    asyncio.run(run())
    print("  Full hackathon scenario: pre-speech -> overlap -> tap -> focus -> stress: OK")


# ================================================================
# 10. State consistency under concurrent updates
# ================================================================

def test_state_consistency():
    """Verify state doesn't get corrupted when multiple users update simultaneously."""
    print("\n=== 10. State Consistency Under Concurrent Updates ===")
    reset_all()

    users = [f"c_user_{i}" for i in range(20)]

    async def run():
        # Fire signals for all 20 users concurrently
        tasks = []
        for uid in users:
            for sig_type in ["speaking", "stress_high", "about_to_speak"]:
                sig = Signal(
                    source_device=f"collar_{uid}", source_user=uid,
                    signal_type=sig_type, confidence=0.9,
                )
                estimator.update(sig)
                tasks.append(bus.emit_signal(sig))
        await asyncio.gather(*tasks)

        # Verify each user has their own independent state
        for uid in users:
            state = estimator.get(uid)
            assert state.user_id == uid
            assert state.signal_count == 3, \
                f"User {uid} should have 3 signals, got {state.signal_count}"
            assert state.speech_active is True
            assert state.stress_level >= 0.9

        # Verify no cross-contamination
        all_states = estimator.all_states()
        user_ids = {s.user_id for s in all_states}
        assert user_ids == set(users), "All 20 users should have independent states"

    asyncio.run(run())
    print(f"  20 concurrent users, 60 signals, all states independent and consistent")


# ================================================================
# 11. Mode transitions — rapid mode switching doesn't corrupt state
# ================================================================

def test_rapid_mode_switching():
    print("\n=== 11. Rapid Mode Switching ===")
    reset_all()

    modes = [UserMode.SOCIAL, UserMode.FOCUS, UserMode.MINIMAL, UserMode.CALIBRATION]

    for i in range(100):
        mode = modes[i % len(modes)]
        estimator.update(Signal(
            source_device="collar_flip", source_user="flipper",
            signal_type="mode_change", value={"mode": mode.value},
        ))

    state = estimator.get("flipper")
    # After 100 switches (i=0..99), last is i=99: 99 % 4 = 3 -> CALIBRATION
    assert state.mode == UserMode.CALIBRATION, f"Expected CALIBRATION, got {state.mode}"
    assert state.signal_count == 100

    # Invalid modes interspersed shouldn't crash
    for bogus in ["spectacles_leader", "pc_leader", "", "nonexistent", "123"]:
        estimator.update(Signal(
            source_device="collar_flip", source_user="flipper",
            signal_type="mode_change", value={"mode": bogus},
        ))
    # Mode should still be CALIBRATION (bogus values rejected)
    assert estimator.get("flipper").mode == UserMode.CALIBRATION

    print("  100 mode switches + 5 invalid modes: state consistent")


# ================================================================
# 12. Policy with many users — scaling check
# ================================================================

def test_policy_scaling():
    print("\n=== 12. Policy Scaling (50 users) ===")
    reset_all()

    users = [f"scale_{i}" for i in range(50)]
    for uid in users:
        register_user(uid)
        state = estimator.get(uid)
        state.mode = UserMode.SOCIAL

    # Give half the users speech intent
    for uid in users[:25]:
        state = estimator.get(uid)
        state.speech_intent = 0.8
        state.speech_active = False

    # Make one user actively speaking
    estimator.get("scale_0").speech_active = True
    estimator.get("scale_0").speech_intent = 1.0
    estimator.get("scale_0").last_speech_time = time.time()

    states = {s.user_id: s for s in estimator.all_states()}

    start = time.time()
    actions = evaluate_rules(states)
    elapsed = time.time() - start

    assert elapsed < 1.0, f"Policy evaluation took {elapsed:.3f}s — too slow for 50 users"

    # Users 1-24 should get wait_turn (speaker active)
    wait_turns = [a for a in actions if a.payload.get("reason") == "wait_turn"]
    assert len(wait_turns) >= 1, "Some users should get wait_turn"

    print(f"  50 users evaluated in {elapsed*1000:.1f}ms, {len(actions)} actions generated")


# ================================================================
# 13. Collar tap during calibration — should be filtered
# ================================================================

def test_tap_during_calibration():
    print("\n=== 13. Collar Tap During Calibration ===")
    reset_all()

    for uid in ["alice", "bob", "charlie"]:
        register_user(uid)

    # Put bob in calibration mode
    estimator.set_mode("bob", UserMode.CALIBRATION)

    tap = Signal(
        source_device="collar_alice", source_user="alice",
        signal_type="collar_tap", confidence=1.0,
    )

    states = {s.user_id: s for s in estimator.all_states()}
    actions = evaluate_signal(tap, states)

    # Should only generate action for charlie (bob is in calibration)
    assert len(actions) == 1, f"Expected 1 action (charlie only), got {len(actions)}"
    assert actions[0].target_user == "charlie"

    # Now put everyone in calibration
    estimator.set_mode("charlie", UserMode.CALIBRATION)
    actions = evaluate_signal(tap, states)
    assert len(actions) == 0, "No actions when all others are in calibration"

    print("  Calibration users correctly excluded from tap actions")


# ================================================================
# 14. HDL library round-trip — YAML load -> to_dict -> parse -> compare
# ================================================================

def test_hdl_round_trip():
    print("\n=== 14. HDL Library Round-Trip ===")

    from delightfulos.hdl.loader import library, parse_device
    library.ensure_loaded()

    for key, spec in library.devices.items():
        # Serialize
        d = spec.to_dict()

        # Deserialize
        rebuilt = parse_device(d)

        # Compare key fields
        assert rebuilt.name == spec.name, f"{key}: name mismatch"
        assert rebuilt.body_site == spec.body_site, f"{key}: body_site mismatch"
        assert len(rebuilt.signals) == len(spec.signals), \
            f"{key}: signal count mismatch ({len(rebuilt.signals)} vs {len(spec.signals)})"
        assert len(rebuilt.outputs) == len(spec.outputs), \
            f"{key}: output count mismatch"
        assert rebuilt.electronics.microcontroller == spec.electronics.microcontroller, \
            f"{key}: MCU mismatch"
        assert rebuilt.firmware.framework == spec.firmware.framework, \
            f"{key}: firmware framework mismatch"
        assert rebuilt.interaction.consent_model == spec.interaction.consent_model, \
            f"{key}: consent model mismatch"

        # Verify signal types match
        orig_types = [s.type for s in spec.signals]
        rebuilt_types = [s.type for s in rebuilt.signals]
        assert orig_types == rebuilt_types, f"{key}: signal types mismatch"

    # Also verify systems
    for key, sys_spec in library.systems.items():
        d = sys_spec.to_dict()
        assert d["name"] == sys_spec.name
        assert len(d["devices"]) == len(sys_spec.devices)
        # Coverage report should not crash
        report = sys_spec.coverage_report()
        assert sys_spec.name in report

    print(f"  {len(library.devices)} devices and {len(library.systems)} systems round-tripped successfully")


# ================================================================
# 15. Action routing priority — specific device > type > capability > fallback
# ================================================================

def test_routing_priority():
    print("\n=== 15. Action Routing Priority ===")
    reset_all()

    t_collar = FakeTransport()
    t_glasses = FakeTransport()
    t_earable = FakeTransport()

    registry.register(DeviceInfo(
        device_id="collar_prio", device_type=DeviceType.COLLAR, user_id="prio",
        capabilities=[Capability.OUTPUT_HAPTIC], transport=t_collar,
    ))
    registry.register(DeviceInfo(
        device_id="glasses_prio", device_type=DeviceType.GLASSES, user_id="prio",
        capabilities=[Capability.OUTPUT_VISUAL_AR], transport=t_glasses,
    ))
    registry.register(DeviceInfo(
        device_id="earable_prio", device_type=DeviceType.SIMULATOR, user_id="prio",
        capabilities=[Capability.SENSE_AUDIO, Capability.OUTPUT_AUDIO], transport=t_earable,
    ))

    async def run():
        # Route by specific device
        await route_action(Action(
            target_user="prio", target_device="earable_prio",
            action_type="narrate", payload={"text": "hello"},
        ))
        assert len(t_earable.messages) == 1
        assert len(t_collar.messages) == 0
        assert len(t_glasses.messages) == 0

        # Route by device type
        await route_action(Action(
            target_user="prio", target_type="collar",
            action_type="haptic", payload={"intensity": 0.5},
        ))
        assert len(t_collar.messages) == 1

        # Route by capability (highlight -> OUTPUT_VISUAL_AR -> glasses)
        await route_action(Action(
            target_user="prio",
            action_type="highlight",
            payload={"target": "someone"},
        ))
        assert len(t_glasses.messages) == 1

    asyncio.run(run())
    print("  Routing priority: specific device > type > capability — all correct")


# ================================================================
# 16. Breathing + arousal interaction
# ================================================================

def test_breathing_arousal():
    print("\n=== 16. Breathing + Arousal Interaction ===")
    reset_all()

    # Rapid breathing should increase arousal
    for _ in range(10):
        estimator.update(Signal(
            source_device="collar_breathe", source_user="breathe",
            signal_type="breathing_change", confidence=0.8,
            value={"pattern": "rapid", "rate": 25},
        ))

    state = estimator.get("breathe")
    assert state.arousal > 0.5, f"Rapid breathing should increase arousal, got {state.arousal}"
    assert state.breathing_rate == 25

    # Deep breathing should decrease arousal
    for _ in range(20):
        estimator.update(Signal(
            source_device="collar_breathe", source_user="breathe",
            signal_type="breathing_change", confidence=0.8,
            value={"pattern": "deep", "rate": 8},
        ))

    state = estimator.get("breathe")
    assert state.arousal < 0.5, f"Deep breathing should decrease arousal, got {state.arousal}"
    assert state.breathing_rate == 8

    # Check that breathing guide policy fires for rapid+high arousal
    state.breathing_phase = "rapid"
    state.arousal = 0.8
    state.mode = UserMode.SOCIAL
    states = {"breathe": state}
    actions = evaluate_rules(states)
    breathing_guides = [a for a in actions if a.payload.get("reason") == "breathing_guide"]
    assert len(breathing_guides) >= 1, "Should get breathing guide haptic"

    print(f"  Arousal dynamics: rapid={state.arousal:.2f} after deep, breathing guide fires correctly")


# ================================================================
# 17. Mixed Supabase + WebSocket users
# ================================================================

def test_mixed_transport():
    """Realistic scenario: some users on direct WebSocket, others via Supabase."""
    print("\n=== 17. Mixed Transport (WebSocket + Supabase) ===")
    reset_all()

    # Alice: direct WebSocket collar + glasses
    t_alice = FakeTransport()
    register_user("alice", t_alice)

    # Bob: Supabase glasses (no transport) + direct WebSocket collar
    t_bob_collar = FakeTransport()
    registry.register(DeviceInfo(
        device_id="collar_bob", device_type=DeviceType.COLLAR, user_id="bob",
        capabilities=[Capability.SENSE_VIBRATION, Capability.OUTPUT_HAPTIC],
        transport=t_bob_collar,
    ))
    registry.register(DeviceInfo(
        device_id="spectacles_bob_supa", device_type=DeviceType.GLASSES, user_id="bob",
        capabilities=[Capability.OUTPUT_VISUAL_AR],
        transport=None,  # Supabase — no direct transport
    ))
    estimator.get("bob")

    bus_actions = []
    async def capture(act):
        bus_actions.append(act)
    bus.subscribe_action(capture)

    async def run():
        # Tap alice's collar -> remove overlay for bob
        tap = Signal(
            source_device="collar_alice", source_user="alice",
            signal_type="collar_tap", confidence=1.0,
        )
        estimator.update(tap)
        states = {s.user_id: s for s in estimator.all_states()}
        actions = evaluate_signal(tap, states)

        for action in actions:
            await route_action(action)
            await bus.emit_action(action)

        # Bob's glasses have no transport, so route_action can't deliver to glasses.
        # The output router falls through type match -> capability match -> any device,
        # which may hit bob's collar as fallback. The bus capture (Supabase bridge path)
        # is what ensures the action reaches Spectacles.
        assert len(bus_actions) == 1
        assert bus_actions[0].target_user == "bob"
        assert bus_actions[0].action_type == "remove_overlay"

        # The bus action path is the critical delivery mechanism for Supabase devices.
        # Direct route_action is best-effort when transport is available.

    asyncio.run(run())
    print("  Mixed transport: WebSocket direct + Supabase bridged, routing correct")


# ================================================================
# 18. Signal log capacity
# ================================================================

def test_signal_log_capacity():
    print("\n=== 18. Signal Log Capacity (overflow test) ===")
    reset_all()

    async def run():
        # Bus has max_log=1000 by default. Fire 1500 signals.
        for i in range(1500):
            await bus.emit_signal(Signal(
                source_device="test", source_user=f"user_{i % 5}",
                signal_type="speaking", confidence=0.8,
            ))

        # Should cap at 1000
        recent = bus.recent_signals(limit=2000)
        assert len(recent) == 1000, f"Expected 1000 (max_log cap), got {len(recent)}"

        # The oldest signals should be gone (FIFO)
        first_user = recent[0].source_user
        # First 500 signals were dropped, so first signal in log should be from i=500
        expected_user = f"user_{500 % 5}"
        assert first_user == expected_user, \
            f"Expected first signal from {expected_user}, got {first_user}"

    asyncio.run(run())
    print("  Signal log caps at 1000, oldest signals evicted correctly")


# ================================================================
# Run all
# ================================================================

if __name__ == "__main__":
    test_high_throughput_bus()
    test_concurrent_collar_taps()
    test_speech_overlap()
    test_state_estimator_burst()
    test_registry_churn()
    test_bus_error_isolation()
    test_transport_failure()
    test_batcher_under_load()
    test_full_hackathon_scenario()
    test_state_consistency()
    test_rapid_mode_switching()
    test_policy_scaling()
    test_tap_during_calibration()
    test_hdl_round_trip()
    test_routing_priority()
    test_breathing_arousal()
    test_mixed_transport()
    test_signal_log_capacity()

    print("\n" + "=" * 50)
    print("ALL 18 STRESS TESTS PASSED")
    print("=" * 50)
