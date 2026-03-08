"""Comprehensive OS pipeline tests — exercises the full signal chain.

Tests the complete flow:
  Signal -> Bus -> StateEstimator -> PolicyEngine -> OutputRouter -> Action
  Including signal-reactive policies (collar tap -> remove overlay).

No API keys or network needed — pure in-memory computation.
Run: cd server && uv run python -m tests.test_os_pipeline
"""
import asyncio
import json
import time

from delightfulos.os.types import Signal, Action, DeviceInfo, DeviceType, Capability
from delightfulos.os.bus import bus
from delightfulos.os.state import estimator, BodyState, UserMode
from delightfulos.os.registry import registry
from delightfulos.runtime.policy import evaluate_rules, evaluate_signal
from delightfulos.runtime.output import route_action


def reset_all():
    """Reset all singletons between tests."""
    bus.reset()
    estimator.reset()
    registry.reset()


# ================================================================
# 1. Types and Registry
# ================================================================

def test_device_registry():
    print("=== 1. Device Registry ===")
    reset_all()

    collar = DeviceInfo(
        device_id="collar_alice",
        device_type=DeviceType.COLLAR,
        user_id="alice",
        capabilities=[Capability.SENSE_VIBRATION, Capability.SENSE_AUDIO, Capability.OUTPUT_HAPTIC],
    )
    registry.register(collar)

    glasses = DeviceInfo(
        device_id="spectacles_alice",
        device_type=DeviceType.GLASSES,
        user_id="alice",
        capabilities=[Capability.OUTPUT_VISUAL_AR, Capability.SENSE_CAMERA],
    )
    registry.register(glasses)

    assert registry.get("collar_alice") is collar
    assert registry.get("nonexistent") is None
    assert len(registry.get_user_devices("alice")) == 2
    assert len(registry.get_user_devices("bob")) == 0
    assert len(registry.get_by_type(DeviceType.COLLAR)) == 1
    assert len(registry.get_by_capability(Capability.OUTPUT_VISUAL_AR)) == 1
    assert "alice" in registry.all_users()

    # Touch and snapshot
    registry.touch("collar_alice")
    snap = registry.snapshot()
    assert len(snap) == 2
    assert snap[0]["device_id"] in ("collar_alice", "spectacles_alice")

    # Unregister
    registry.unregister("collar_alice")
    assert registry.get("collar_alice") is None
    assert len(registry.get_user_devices("alice")) == 1

    print("  All registry tests passed")


# ================================================================
# 2. Signal Bus
# ================================================================

def test_signal_bus():
    print("\n=== 2. Signal Bus ===")
    reset_all()

    received_signals = []
    received_actions = []

    async def on_signal(sig):
        received_signals.append(sig)

    async def on_speaking(sig):
        received_signals.append(("speaking_only", sig))

    async def on_action(act):
        received_actions.append(act)

    bus.subscribe_signal(on_signal)
    bus.subscribe_signal(on_speaking, signal_type="speaking")
    bus.subscribe_action(on_action)

    async def run():
        sig = Signal(source_device="collar_a", source_user="alice", signal_type="about_to_speak", confidence=0.8)
        await bus.emit_signal(sig)
        assert len(received_signals) == 1, f"Expected 1 signal, got {len(received_signals)}"

        sig2 = Signal(source_device="collar_a", source_user="alice", signal_type="speaking", confidence=0.95)
        await bus.emit_signal(sig2)
        assert len(received_signals) == 3, f"Expected 3 (1 wildcard + 1 wildcard + 1 typed), got {len(received_signals)}"

        act = Action(target_user="bob", action_type="haptic", payload={"intensity": 0.5})
        await bus.emit_action(act)
        assert len(received_actions) == 1

        # Recent signals log
        recent = bus.recent_signals(limit=10)
        assert len(recent) == 2
        recent_alice = bus.recent_signals(user_id="alice", limit=10)
        assert len(recent_alice) == 2
        recent_bob = bus.recent_signals(user_id="bob", limit=10)
        assert len(recent_bob) == 0

    asyncio.run(run())
    print("  All bus tests passed")


# ================================================================
# 3. State Estimator
# ================================================================

def test_state_estimator():
    print("\n=== 3. State Estimator ===")
    reset_all()

    state = estimator.get("alice")
    assert state.user_id == "alice"
    assert state.mode == UserMode.SOCIAL
    assert state.speech_active is False
    assert state.speech_intent == 0.0

    # About to speak
    estimator.update(Signal(
        source_device="collar_a", source_user="alice",
        signal_type="about_to_speak", confidence=0.75,
    ))
    state = estimator.get("alice")
    assert state.speech_intent >= 0.75, f"Speech intent should be >= 0.75, got {state.speech_intent}"
    assert state.interaction_ready is True
    assert state.signal_count == 1

    # Speaking
    estimator.update(Signal(
        source_device="collar_a", source_user="alice",
        signal_type="speaking", confidence=0.95,
    ))
    state = estimator.get("alice")
    assert state.speech_active is True
    assert state.speech_intent == 1.0

    # Speech ended
    estimator.update(Signal(
        source_device="collar_a", source_user="alice",
        signal_type="speech_ended", confidence=0.8,
    ))
    state = estimator.get("alice")
    assert state.speech_active is False

    # Mode change
    estimator.update(Signal(
        source_device="collar_a", source_user="alice",
        signal_type="mode_change", value={"mode": "focus"},
    ))
    state = estimator.get("alice")
    assert state.mode == UserMode.FOCUS

    # Invalid mode change (should not crash)
    estimator.update(Signal(
        source_device="collar_a", source_user="alice",
        signal_type="mode_change", value={"mode": "spectacles_leader"},
    ))
    state = estimator.get("alice")
    assert state.mode == UserMode.FOCUS, "Invalid mode should not change state"

    # Mode change back
    estimator.set_mode("alice", UserMode.SOCIAL)
    assert estimator.get("alice").mode == UserMode.SOCIAL

    # Stress
    estimator.update(Signal(
        source_device="collar_a", source_user="alice",
        signal_type="stress_high", confidence=0.8,
    ))
    state = estimator.get("alice")
    assert state.stress_level >= 0.8

    # Touch
    estimator.update(Signal(
        source_device="collar_a", source_user="alice",
        signal_type="touch", confidence=1.0,
    ))
    state = estimator.get("alice")
    assert state.interaction_ready is True

    # Multiple users
    estimator.update(Signal(
        source_device="collar_b", source_user="bob",
        signal_type="speaking", confidence=0.9,
    ))
    all_states = estimator.all_states()
    assert len(all_states) == 2
    bob = estimator.get("bob")
    assert bob.speech_active is True

    # to_dict
    d = state.to_dict()
    assert d["user_id"] == "alice"
    assert "mode" in d
    assert "speech_intent" in d

    print("  All state estimator tests passed")


# ================================================================
# 4. State Estimator — mode_change with Spectacles values
# ================================================================

def test_spectacles_mode_passthrough():
    """Spectacles send mode values like 'spectacles_leader' / 'pc_leader'
    which are NOT valid UserMode values. The estimator should handle
    this gracefully without crashing."""
    print("\n=== 4. Spectacles Mode Passthrough ===")
    reset_all()

    estimator.update(Signal(
        source_device="spectacles_a", source_user="alice",
        signal_type="mode_change", value={"mode": "spectacles_leader"},
    ))
    # Should not crash, and mode should remain default
    state = estimator.get("alice")
    assert state.mode == UserMode.SOCIAL, f"Mode should stay social, got {state.mode}"

    estimator.update(Signal(
        source_device="spectacles_a", source_user="alice",
        signal_type="mode_change", value={"mode": "pc_leader"},
    ))
    state = estimator.get("alice")
    assert state.mode == UserMode.SOCIAL, f"Mode should stay social, got {state.mode}"

    # Valid modes should still work
    estimator.update(Signal(
        source_device="spectacles_a", source_user="alice",
        signal_type="mode_change", value={"mode": "focus"},
    ))
    state = estimator.get("alice")
    assert state.mode == UserMode.FOCUS

    print("  Spectacles mode passthrough handled correctly")


# ================================================================
# 5. Policy Engine — Rule-based
# ================================================================

def test_policy_rules():
    print("\n=== 5. Policy Rules ===")
    reset_all()

    # Setup: alice speaking, bob about to speak
    alice = estimator.get("alice")
    alice.speech_active = True
    alice.speech_intent = 1.0
    alice.last_speech_time = time.time()

    bob = estimator.get("bob")
    bob.speech_intent = 0.8
    bob.speech_active = False

    states = {"alice": alice, "bob": bob}
    actions = evaluate_rules(states)

    # Bob should get a "wait_turn" haptic (alice is already speaking)
    wait_actions = [a for a in actions if a.payload.get("reason") == "wait_turn"]
    assert len(wait_actions) == 1, f"Expected 1 wait_turn, got {len(wait_actions)}"
    assert wait_actions[0].target_user == "bob"

    # No about_to_speak highlight while someone is talking
    highlight_actions = [a for a in actions if a.payload.get("reason") == "about_to_speak"]
    assert len(highlight_actions) == 0, "Should not highlight about_to_speak while someone is talking"

    # Overload protection
    alice.stress_level = 0.8
    alice.arousal = 0.7
    alice.overloaded = True
    actions = evaluate_rules(states)
    suppress = [a for a in actions if a.action_type == "suppress"]
    assert len(suppress) >= 1, "Should have suppress action for overloaded user"

    # Calibration mode skips rules
    alice.mode = UserMode.CALIBRATION
    alice.overloaded = True
    actions = evaluate_rules({"alice": alice})
    alice_actions = [a for a in actions if a.target_user == "alice"]
    assert len(alice_actions) == 0, "Calibration mode should skip all rules"

    print("  All policy rule tests passed")


# ================================================================
# 6. Signal-Reactive Policy — Collar Tap
# ================================================================

def test_collar_tap_policy():
    print("\n=== 6. Collar Tap Policy ===")
    reset_all()

    # Setup two users
    alice = estimator.get("alice")
    bob = estimator.get("bob")
    states = {"alice": alice, "bob": bob}

    # Alice's collar is tapped
    tap_signal = Signal(
        source_device="collar_alice",
        source_user="alice",
        signal_type="collar_tap",
        confidence=1.0,
    )

    actions = evaluate_signal(tap_signal, states)
    assert len(actions) == 1, f"Expected 1 action (remove_overlay for bob), got {len(actions)}"

    action = actions[0]
    assert action.target_user == "bob", f"Target should be bob, got {action.target_user}"
    assert action.action_type == "remove_overlay"
    assert action.payload["target"] == "alice"
    assert action.payload["type"] == "cube"
    assert action.payload["reason"] == "collar_tap"
    assert action.target_type == "glasses"

    # With 3 users: tap on alice -> actions for bob AND charlie
    charlie = estimator.get("charlie")
    states["charlie"] = charlie
    actions = evaluate_signal(tap_signal, states)
    assert len(actions) == 2, f"Expected 2 actions (bob + charlie), got {len(actions)}"
    targets = {a.target_user for a in actions}
    assert targets == {"bob", "charlie"}

    # Calibration user should be skipped
    charlie.mode = UserMode.CALIBRATION
    actions = evaluate_signal(tap_signal, states)
    assert len(actions) == 1
    assert actions[0].target_user == "bob"

    # Non-reactive signals should return empty
    non_tap = Signal(
        source_device="collar_alice", source_user="alice",
        signal_type="speaking", confidence=0.9,
    )
    actions = evaluate_signal(non_tap, states)
    assert len(actions) == 0, "Non-reactive signals should not produce actions"

    print("  All collar tap policy tests passed")


# ================================================================
# 7. Output Router
# ================================================================

def test_output_router():
    print("\n=== 7. Output Router ===")
    reset_all()

    sent_messages = []

    class FakeTransport:
        async def send_text(self, text):
            sent_messages.append(json.loads(text))

    transport = FakeTransport()

    # Register devices
    registry.register(DeviceInfo(
        device_id="collar_alice",
        device_type=DeviceType.COLLAR,
        user_id="alice",
        capabilities=[Capability.OUTPUT_HAPTIC],
        transport=transport,
    ))
    registry.register(DeviceInfo(
        device_id="glasses_alice",
        device_type=DeviceType.GLASSES,
        user_id="alice",
        capabilities=[Capability.OUTPUT_VISUAL_AR],
        transport=transport,
    ))

    async def run():
        # Route by target_type
        await route_action(Action(
            target_user="alice",
            target_type="collar",
            action_type="haptic",
            payload={"intensity": 0.5},
        ))
        assert len(sent_messages) == 1
        assert sent_messages[-1]["action"] == "haptic"

        # Route by capability
        await route_action(Action(
            target_user="alice",
            action_type="highlight",
            payload={"target": "bob", "type": "halo"},
        ))
        assert len(sent_messages) == 2
        assert sent_messages[-1]["action"] == "highlight"

        # Route to specific device
        await route_action(Action(
            target_user="alice",
            target_device="glasses_alice",
            action_type="remove_overlay",
            payload={"target": "bob", "type": "cube"},
        ))
        assert len(sent_messages) == 3

        # Unknown user — no crash, just no delivery
        await route_action(Action(
            target_user="nonexistent",
            action_type="haptic",
            payload={},
        ))
        assert len(sent_messages) == 3  # no new message

    asyncio.run(run())
    print("  All output router tests passed")


# ================================================================
# 8. Output Router — Supabase devices (transport=None)
# ================================================================

def test_supabase_device_routing():
    """Spectacles registered via Supabase have transport=None.
    The output router can't reach them directly — actions are
    forwarded via the bus.subscribe_action -> supabase broadcast path."""
    print("\n=== 8. Supabase Device Routing ===")
    reset_all()

    # Register a Supabase device (no transport)
    registry.register(DeviceInfo(
        device_id="spectacles_bob",
        device_type=DeviceType.GLASSES,
        user_id="bob",
        capabilities=[Capability.OUTPUT_VISUAL_AR],
        transport=None,  # Supabase — no direct transport
    ))

    bus_actions = []

    async def capture_action(act):
        bus_actions.append(act)

    bus.subscribe_action(capture_action)

    async def run():
        action = Action(
            target_user="bob",
            target_type="glasses",
            action_type="remove_overlay",
            payload={"target": "alice", "type": "cube"},
        )
        # route_action will fail silently (no transport)
        await route_action(action)
        # But bus.emit_action ensures supabase bridge gets it
        await bus.emit_action(action)
        assert len(bus_actions) == 1
        assert bus_actions[0].action_type == "remove_overlay"

    asyncio.run(run())
    print("  Supabase device routing: actions forwarded via bus (OK)")


# ================================================================
# 9. Full Pipeline — Collar Tap End-to-End
# ================================================================

def test_full_collar_tap_pipeline():
    """Simulate the complete collar tap -> remove overlay pipeline."""
    print("\n=== 9. Full Pipeline: Collar Tap -> Remove Overlay ===")
    reset_all()

    sent_to_glasses = []
    bus_actions = []

    class FakeTransport:
        async def send_text(self, text):
            sent_to_glasses.append(json.loads(text))

    async def capture_bus_action(act):
        bus_actions.append(act)

    transport = FakeTransport()

    # Register alice's collar (direct WebSocket)
    registry.register(DeviceInfo(
        device_id="collar_alice",
        device_type=DeviceType.COLLAR,
        user_id="alice",
        capabilities=[Capability.SENSE_VIBRATION, Capability.OUTPUT_HAPTIC],
        transport=transport,
    ))

    # Register bob's glasses (direct WebSocket for this test)
    registry.register(DeviceInfo(
        device_id="glasses_bob",
        device_type=DeviceType.GLASSES,
        user_id="bob",
        capabilities=[Capability.OUTPUT_VISUAL_AR],
        transport=transport,
    ))

    # Also register bob's Supabase glasses (no transport)
    registry.register(DeviceInfo(
        device_id="spectacles_bob_supabase",
        device_type=DeviceType.GLASSES,
        user_id="bob",
        capabilities=[Capability.OUTPUT_VISUAL_AR],
        transport=None,
    ))

    bus.subscribe_action(capture_bus_action)

    async def run():
        # Initialize both users' state
        estimator.get("alice")
        estimator.get("bob")

        # Simulate: collar sends tap signal
        tap = Signal(
            source_device="collar_alice",
            source_user="alice",
            signal_type="collar_tap",
            confidence=1.0,
        )

        # Step 1: Estimator update (what managers._on_signal does)
        estimator.update(tap)

        # Step 2: Signal-reactive policy (what managers._on_signal does)
        all_states = {s.user_id: s for s in estimator.all_states()}
        reactive_actions = evaluate_signal(tap, all_states)

        assert len(reactive_actions) == 1, f"Expected 1 action, got {len(reactive_actions)}"

        for action in reactive_actions:
            # Step 3: Route action
            await route_action(action)
            # Step 4: Emit on bus (for Supabase bridge)
            await bus.emit_action(action)

        # Verify: glasses_bob got the message (direct transport)
        assert len(sent_to_glasses) == 1, f"Expected 1 message to glasses, got {len(sent_to_glasses)}"
        msg = sent_to_glasses[0]
        assert msg["action"] == "remove_overlay"
        assert msg["payload"]["target"] == "alice"
        assert msg["payload"]["type"] == "cube"
        assert msg["payload"]["reason"] == "collar_tap"

        # Verify: bus captured the action (supabase bridge would forward it)
        assert len(bus_actions) == 1
        assert bus_actions[0].target_user == "bob"

    asyncio.run(run())
    print("  Full pipeline: collar_tap -> remove_overlay -> glasses: OK")


# ================================================================
# 10. XR Protocol — Serialization Roundtrip
# ================================================================

def test_xr_protocol():
    from delightfulos.xr.protocol import XRInputEvent, XROutputCommand, XRInputType, XROutputType

    print("\n=== 10. XR Protocol Serialization ===")

    # Input event roundtrip
    event = XRInputEvent(
        type=XRInputType.GESTURE,
        user_id="alice",
        timestamp=time.time(),
        payload={"gesture": "wave", "confidence": 0.9},
    )
    d = event.to_dict()
    assert d["type"] == "gesture"
    assert d["payload"]["gesture"] == "wave"

    restored = XRInputEvent.from_dict(d)
    assert restored.type == "gesture"
    assert restored.user_id == "alice"
    assert restored.payload["confidence"] == 0.9

    # Output command roundtrip
    cmd = XROutputCommand(
        type=XROutputType.REMOVE_OVERLAY,
        payload={"target": "alice", "type": "cube"},
        target_user="bob",
    )
    d = cmd.to_dict()
    assert d["type"] == "remove_overlay"
    assert d["target_user"] == "bob"

    restored = XROutputCommand.from_dict(d)
    assert restored.type == "remove_overlay"
    assert restored.target_user == "bob"

    # Hello event
    hello = XRInputEvent(
        type=XRInputType.HELLO,
        user_id="alice",
        payload={"platform": "spectacles", "capabilities": ["hand_tracking", "ar_overlay"]},
    )
    d = hello.to_dict()
    assert d["type"] == "hello"

    print("  All XR protocol tests passed")


# ================================================================
# 11. XR Types — Spatial Data
# ================================================================

def test_xr_types():
    from delightfulos.xr.types import Vec3, Quat, Pose, HandState, HandSide, GazeState, XRSceneState, TrackedUser

    print("\n=== 11. XR Types ===")

    # Vec3
    v = Vec3(1.0, 2.0, 3.0)
    assert v.to_list() == [1.0, 2.0, 3.0]
    v2 = Vec3.from_list([4.0, 5.0, 6.0])
    assert v2.x == 4.0

    # Quat
    q = Quat(0.0, 0.0, 0.0, 1.0)
    assert q.to_list() == [0.0, 0.0, 0.0, 1.0]

    # Pose roundtrip
    pose = Pose(position=Vec3(1, 2, 3), rotation=Quat(0, 0, 0, 1))
    d = pose.to_dict()
    restored = Pose.from_dict(d)
    assert restored.position.x == 1.0

    # HandState roundtrip
    hand = HandState(side=HandSide.LEFT, tracked=True, pinching=True, pinch_strength=0.8)
    d = hand.to_dict()
    restored = HandState.from_dict(d)
    assert restored.pinching is True
    assert restored.pinch_strength == 0.8

    # TrackedUser roundtrip
    user = TrackedUser(user_id="alice", distance=1.5, face_visible=True)
    d = user.to_dict()
    restored = TrackedUser.from_dict(d)
    assert restored.user_id == "alice"
    assert restored.distance == 1.5

    # XRSceneState roundtrip
    scene = XRSceneState(
        tracked_users=[user],
        hands=[hand],
        gaze=GazeState(gaze_confidence=0.9),
        ambient_light="bright",
    )
    d = scene.to_dict()
    restored = XRSceneState.from_dict(d)
    assert len(restored.tracked_users) == 1
    assert restored.ambient_light == "bright"

    print("  All XR types tests passed")


# ================================================================
# 12. Supabase Bridge — User ID Resolution
# ================================================================

def test_supabase_user_id_resolution():
    from delightfulos.networking.supabase_rt import SupabaseRealtimeBridge

    print("\n=== 12. Supabase User ID Resolution ===")

    bridge = SupabaseRealtimeBridge()

    # Spectacles prefix
    user_id, device_id = bridge._resolve_user_id("spectacles_a3b8x")
    assert user_id == "a3b8x", f"Expected 'a3b8x', got '{user_id}'"
    assert device_id == "spectacles_a3b8x"

    # PC prefix
    user_id, device_id = bridge._resolve_user_id("pc_web123")
    assert user_id == "web123", f"Expected 'web123', got '{user_id}'"
    assert device_id == "pc_web123"

    # No prefix
    user_id, device_id = bridge._resolve_user_id("raw_user")
    assert user_id == "raw_user"
    assert device_id == "spectacles_raw_user"

    # Server prefix (should not strip)
    user_id, device_id = bridge._resolve_user_id("server_delightfulos")
    assert user_id == "server_delightfulos"
    assert device_id == "spectacles_server_delightfulos"

    print("  All user ID resolution tests passed")


# ================================================================
# 13. Supabase Bridge — Channel Naming
# ================================================================

def test_supabase_channel_naming():
    from delightfulos.networking.supabase_rt import SupabaseRealtimeBridge

    print("\n=== 13. Supabase Channel Naming ===")

    bridge = SupabaseRealtimeBridge()
    bridge._channel = "spectacles"
    assert bridge._phoenix_topic() == "realtime:cursor-spectacles"

    bridge._channel = "hackathon"
    assert bridge._phoenix_topic() == "realtime:cursor-hackathon"

    print("  Channel naming matches Spectacles convention")


# ================================================================
# 14. Signal Processing
# ================================================================

def test_signal_processing():
    import math
    from delightfulos.ai.signal import extract_features, VoiceActivityDetector

    print("\n=== 14. Signal Processing ===")

    # Silence
    silence = [0.001 * (i % 2 * 2 - 1) for i in range(256)]
    f = extract_features(silence)
    assert f.rms < 0.01, f"Silence RMS should be near zero, got {f.rms}"

    # Speech-level signal
    speech = [0.4 * math.sin(2 * math.pi * 180 * i / 4000) for i in range(256)]
    f = extract_features(speech)
    assert f.rms > 0.2, f"Speech RMS should be high, got {f.rms}"

    # VAD sequence
    vad = VoiceActivityDetector()
    for _ in range(5):
        result = vad.detect(silence)
    assert not result.speech_detected

    for _ in range(3):
        result = vad.detect(speech)
    assert result.speech_detected, "VAD should detect speech"

    print("  Signal processing tests passed")


# ================================================================
# 15. HDL Layer
# ================================================================

def test_hdl():
    from delightfulos.hdl.grammar import WearableSpec, WearableSystem, BodySite, SignalType
    from delightfulos.hdl.library.devices import COLLAR_V1, SPECTACLES

    print("\n=== 15. HDL Layer ===")

    assert COLLAR_V1 is not None
    assert SPECTACLES is not None
    assert "collar" in COLLAR_V1.name.lower(), f"Expected collar in name, got {COLLAR_V1.name}"
    assert "spectacles" in SPECTACLES.name.lower(), f"Expected spectacles in name, got {SPECTACLES.name}"

    # Grammar types should be usable
    assert WearableSpec is not None
    assert WearableSystem is not None
    assert BodySite is not None
    assert SignalType is not None

    print("  HDL layer tests passed")


# ================================================================
# 16. Multiplayer State Broadcasting
# ================================================================

def test_multiplayer_state():
    """Ensure all_states returns correct data for multiplayer broadcasting."""
    print("\n=== 16. Multiplayer State ===")
    reset_all()

    # Setup 3 users
    for name in ("alice", "bob", "charlie"):
        estimator.get(name)

    estimator.update(Signal(
        source_device="collar_a", source_user="alice",
        signal_type="speaking", confidence=0.95,
    ))
    estimator.update(Signal(
        source_device="collar_b", source_user="bob",
        signal_type="about_to_speak", confidence=0.8,
    ))

    all_states = estimator.all_states()
    assert len(all_states) == 3

    alice_state = estimator.get("alice")
    bob_state = estimator.get("bob")
    charlie_state = estimator.get("charlie")

    assert alice_state.speech_active is True
    assert bob_state.speech_intent >= 0.8
    assert charlie_state.speech_active is False

    # Verify to_dict works for all
    for s in all_states:
        d = s.to_dict()
        assert "user_id" in d
        assert "mode" in d
        assert "speech_active" in d

    print("  Multiplayer state broadcasting OK")


# ================================================================
# Run all
# ================================================================

if __name__ == "__main__":
    test_device_registry()
    test_signal_bus()
    test_state_estimator()
    test_spectacles_mode_passthrough()
    test_policy_rules()
    test_collar_tap_policy()
    test_output_router()
    test_supabase_device_routing()
    test_full_collar_tap_pipeline()
    test_xr_protocol()
    test_xr_types()
    test_supabase_user_id_resolution()
    test_supabase_channel_naming()
    test_signal_processing()
    test_hdl()
    test_multiplayer_state()

    print("\n" + "=" * 50)
    print("ALL 16 TESTS PASSED")
    print("=" * 50)
