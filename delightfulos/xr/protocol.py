"""XR Protocol — the JSON message schema between server and XR clients.

This defines the wire format that ALL XR platforms use to communicate
with DelightfulOS. Platform adapters on the client side translate
between this protocol and their native APIs.

Message flow:
  Client -> Server: XRInputEvent (scene state, gestures, voice, etc.)
  Server -> Client: XROutputCommand (overlays, haptics, mode changes, etc.)

All messages are JSON over WebSocket. The protocol is versioned so
old clients can still connect during upgrades.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

PROTOCOL_VERSION = 1


# === Input Events (Client -> Server) ===

class XRInputType(str, Enum):
    """Types of input events the XR client can send."""
    # Connection lifecycle
    HELLO = "hello"                  # first message: declare platform + capabilities
    HEARTBEAT = "heartbeat"          # keep-alive

    # Scene perception
    SCENE_UPDATE = "scene_update"    # full scene state snapshot
    USER_DETECTED = "user_detected"  # new person entered FOV
    USER_LOST = "user_lost"          # person left FOV

    # Spatial input
    GESTURE = "gesture"              # hand gesture recognized
    GAZE_SHIFT = "gaze_shift"        # gaze target changed
    PINCH = "pinch"                  # pinch start/end
    HEAD_NOD = "head_nod"            # affirmative head movement
    HEAD_SHAKE = "head_shake"        # negative head movement

    # Voice
    VOICE_COMMAND = "voice_command"   # ASR transcript from device
    VOICE_ACTIVITY = "voice_activity" # VAD from device mic

    # Spatial
    ANCHOR_CREATED = "anchor_created"
    ANCHOR_UPDATED = "anchor_updated"

    # Platform-specific passthrough
    PLATFORM_EVENT = "platform_event"


@dataclass
class XRInputEvent:
    """A message from the XR client to the server."""
    type: str                                   # XRInputType value
    user_id: str = ""
    timestamp: float = 0.0
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "v": PROTOCOL_VERSION,
            "type": self.type,
            "user_id": self.user_id,
            "ts": self.timestamp,
            "payload": self.payload,
        }

    @classmethod
    def from_dict(cls, d: dict) -> XRInputEvent:
        return cls(
            type=d.get("type", ""),
            user_id=d.get("user_id", ""),
            timestamp=d.get("ts", d.get("timestamp", 0.0)),
            payload=d.get("payload", {}),
        )


# === Output Commands (Server -> Client) ===

class XROutputType(str, Enum):
    """Types of output commands the server can send to XR clients."""
    # Overlays
    SHOW_OVERLAY = "show_overlay"       # create or update an overlay
    REMOVE_OVERLAY = "remove_overlay"   # remove a specific overlay
    CLEAR_OVERLAYS = "clear_overlays"   # remove all overlays

    # Highlights (sugar for common overlay patterns)
    HIGHLIGHT_USER = "highlight_user"   # glow/ring around a tracked user
    UNHIGHLIGHT_USER = "unhighlight_user"

    # Notifications
    TOAST = "toast"                     # brief text notification (head-locked)
    SOCIAL_CUE = "social_cue"          # contextual cue near a user

    # Haptics
    HAPTIC = "haptic"                   # trigger device haptic

    # Mode
    MODE_CHANGE = "mode_change"         # OS mode changed, adjust UI

    # State sync
    STATE_UPDATE = "state_update"       # push user body-state to client
    USER_STATES = "user_states"         # all users' states (for multi-user)

    # Spatial
    PLACE_ANCHOR = "place_anchor"
    REMOVE_ANCHOR = "remove_anchor"

    # Platform-specific passthrough
    PLATFORM_COMMAND = "platform_command"


@dataclass
class XROutputCommand:
    """A message from the server to the XR client."""
    type: str                                   # XROutputType value
    payload: dict[str, Any] = field(default_factory=dict)
    target_user: str | None = None              # specific user, or None for broadcast

    def to_dict(self) -> dict:
        d: dict[str, Any] = {
            "v": PROTOCOL_VERSION,
            "type": self.type,
            "payload": self.payload,
        }
        if self.target_user:
            d["target_user"] = self.target_user
        return d

    @classmethod
    def from_dict(cls, d: dict) -> XROutputCommand:
        return cls(
            type=d.get("type", ""),
            payload=d.get("payload", {}),
            target_user=d.get("target_user"),
        )


# === Combined message wrapper ===

@dataclass
class XRMessage:
    """Top-level message envelope. Either an input event or output command."""
    version: int = PROTOCOL_VERSION
    input: XRInputEvent | None = None
    output: XROutputCommand | None = None

    def to_dict(self) -> dict:
        if self.input:
            return self.input.to_dict()
        if self.output:
            return self.output.to_dict()
        return {"v": self.version}

    @classmethod
    def from_client_dict(cls, d: dict) -> XRMessage:
        return cls(
            version=d.get("v", PROTOCOL_VERSION),
            input=XRInputEvent.from_dict(d),
        )
