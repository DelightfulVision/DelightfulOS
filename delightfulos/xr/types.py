"""XR Types — platform-agnostic data types for augmented/mixed reality.

These types represent the universal concepts that ALL XR platforms share.
Platform-specific adapters translate their native data into these types.

Design principles:
  - No platform-specific imports (no Lens Studio, no Unity, no ARKit)
  - Serializable to JSON (for WebSocket transport)
  - Extensible via metadata dicts for platform-specific extras
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# === Platform Identity ===

class XRPlatform(str, Enum):
    """Supported XR platforms. Each gets its own adapter."""
    SPECTACLES = "spectacles"      # Snap Spectacles (Lens Studio)
    QUEST = "quest"                # Meta Quest 2/3/Pro (Unity/Godot)
    VISION_PRO = "vision_pro"      # Apple Vision Pro (RealityKit)
    HOLOLENS = "hololens"          # Microsoft HoloLens (MRTK)
    WEBXR = "webxr"                # Browser-based WebXR
    SIMULATOR = "xr_simulator"     # Software simulator for testing


class XRCapability(str, Enum):
    """What a specific XR device can do. Queried at connect time."""
    # Sensing
    HAND_TRACKING = "hand_tracking"
    EYE_TRACKING = "eye_tracking"
    HEAD_TRACKING = "head_tracking"
    SPATIAL_MESH = "spatial_mesh"
    DEPTH_SENSING = "depth_sensing"
    PLANE_DETECTION = "plane_detection"
    IMAGE_TRACKING = "image_tracking"
    FACE_TRACKING = "face_tracking"
    VOICE_INPUT = "voice_input"
    CONTROLLER_INPUT = "controller_input"
    # Output
    AR_OVERLAY = "ar_overlay"
    SPATIAL_AUDIO = "spatial_audio"
    HAPTIC_OUTPUT = "haptic_output"
    PASSTHROUGH = "passthrough"
    # Multi-user
    SHARED_ANCHOR = "shared_anchor"
    CO_LOCATION = "co_location"


# === Spatial Types ===

@dataclass
class Vec3:
    """3D vector — position, direction, or scale."""
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0

    def to_list(self) -> list[float]:
        return [self.x, self.y, self.z]

    @classmethod
    def from_list(cls, v: list[float]) -> Vec3:
        return cls(x=v[0], y=v[1], z=v[2]) if len(v) >= 3 else cls()


@dataclass
class Quat:
    """Quaternion rotation."""
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    w: float = 1.0

    def to_list(self) -> list[float]:
        return [self.x, self.y, self.z, self.w]

    @classmethod
    def from_list(cls, v: list[float]) -> Quat:
        return cls(x=v[0], y=v[1], z=v[2], w=v[3]) if len(v) >= 4 else cls()


@dataclass
class Pose:
    """Position + rotation in 3D space."""
    position: Vec3 = field(default_factory=Vec3)
    rotation: Quat = field(default_factory=Quat)

    def to_dict(self) -> dict:
        return {
            "position": self.position.to_list(),
            "rotation": self.rotation.to_list(),
        }

    @classmethod
    def from_dict(cls, d: dict) -> Pose:
        return cls(
            position=Vec3.from_list(d.get("position", [0, 0, 0])),
            rotation=Quat.from_list(d.get("rotation", [0, 0, 0, 1])),
        )


# === Hand Tracking ===

class HandSide(str, Enum):
    LEFT = "left"
    RIGHT = "right"


@dataclass
class HandState:
    """Tracked hand state — platform-agnostic representation."""
    side: HandSide
    tracked: bool = False
    palm_position: Vec3 = field(default_factory=Vec3)
    palm_normal: Vec3 = field(default_factory=Vec3)
    index_tip: Vec3 = field(default_factory=Vec3)
    thumb_tip: Vec3 = field(default_factory=Vec3)
    pinching: bool = False
    pinch_strength: float = 0.0
    grip_strength: float = 0.0

    def to_dict(self) -> dict:
        return {
            "side": self.side.value,
            "tracked": self.tracked,
            "palm_position": self.palm_position.to_list(),
            "palm_normal": self.palm_normal.to_list(),
            "index_tip": self.index_tip.to_list(),
            "thumb_tip": self.thumb_tip.to_list(),
            "pinching": self.pinching,
            "pinch_strength": round(self.pinch_strength, 3),
            "grip_strength": round(self.grip_strength, 3),
        }

    @classmethod
    def from_dict(cls, d: dict) -> HandState:
        return cls(
            side=HandSide(d.get("side", "left")),
            tracked=d.get("tracked", False),
            palm_position=Vec3.from_list(d.get("palm_position", [0, 0, 0])),
            palm_normal=Vec3.from_list(d.get("palm_normal", [0, 0, 0])),
            index_tip=Vec3.from_list(d.get("index_tip", [0, 0, 0])),
            thumb_tip=Vec3.from_list(d.get("thumb_tip", [0, 0, 0])),
            pinching=d.get("pinching", False),
            pinch_strength=d.get("pinch_strength", 0.0),
            grip_strength=d.get("grip_strength", 0.0),
        )


# === Gaze / Head Pose ===

@dataclass
class GazeState:
    """Head pose and gaze direction."""
    head_pose: Pose = field(default_factory=Pose)
    gaze_direction: Vec3 = field(default_factory=Vec3)
    gaze_target_user: str | None = None  # user_id if looking at someone
    gaze_confidence: float = 0.0

    def to_dict(self) -> dict:
        return {
            "head_pose": self.head_pose.to_dict(),
            "gaze_direction": self.gaze_direction.to_list(),
            "gaze_target_user": self.gaze_target_user,
            "gaze_confidence": round(self.gaze_confidence, 3),
        }

    @classmethod
    def from_dict(cls, d: dict) -> GazeState:
        return cls(
            head_pose=Pose.from_dict(d.get("head_pose", {})),
            gaze_direction=Vec3.from_list(d.get("gaze_direction", [0, 0, -1])),
            gaze_target_user=d.get("gaze_target_user"),
            gaze_confidence=d.get("gaze_confidence", 0.0),
        )


# === Tracked Users (what the XR device sees) ===

@dataclass
class TrackedUser:
    """A person detected in the XR device's field of view."""
    user_id: str | None = None      # resolved user_id, or None if unknown
    display_name: str | None = None
    world_position: Vec3 = field(default_factory=Vec3)
    distance: float = 0.0           # meters from wearer
    is_speaking: bool = False
    face_visible: bool = False
    body_pose: Pose | None = None

    def to_dict(self) -> dict:
        d: dict[str, Any] = {
            "user_id": self.user_id,
            "display_name": self.display_name,
            "world_position": self.world_position.to_list(),
            "distance": round(self.distance, 2),
            "is_speaking": self.is_speaking,
            "face_visible": self.face_visible,
        }
        if self.body_pose:
            d["body_pose"] = self.body_pose.to_dict()
        return d

    @classmethod
    def from_dict(cls, d: dict) -> TrackedUser:
        return cls(
            user_id=d.get("user_id"),
            display_name=d.get("display_name"),
            world_position=Vec3.from_list(d.get("world_position", [0, 0, 0])),
            distance=d.get("distance", 0.0),
            is_speaking=d.get("is_speaking", False),
            face_visible=d.get("face_visible", False),
            body_pose=Pose.from_dict(d["body_pose"]) if d.get("body_pose") else None,
        )


# === Scene State ===

@dataclass
class XRSceneState:
    """Snapshot of what the XR device currently perceives."""
    tracked_users: list[TrackedUser] = field(default_factory=list)
    hands: list[HandState] = field(default_factory=list)
    gaze: GazeState = field(default_factory=GazeState)
    ambient_light: str = "unknown"   # bright, dim, dark, outdoor
    tracked_planes: int = 0
    spatial_mesh_available: bool = False
    platform_extras: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "tracked_users": [u.to_dict() for u in self.tracked_users],
            "hands": [h.to_dict() for h in self.hands],
            "gaze": self.gaze.to_dict(),
            "ambient_light": self.ambient_light,
            "tracked_planes": self.tracked_planes,
            "spatial_mesh_available": self.spatial_mesh_available,
            "platform_extras": self.platform_extras,
        }

    @classmethod
    def from_dict(cls, d: dict) -> XRSceneState:
        return cls(
            tracked_users=[TrackedUser.from_dict(u) for u in d.get("tracked_users", [])],
            hands=[HandState.from_dict(h) for h in d.get("hands", [])],
            gaze=GazeState.from_dict(d.get("gaze", {})),
            ambient_light=d.get("ambient_light", "unknown"),
            tracked_planes=d.get("tracked_planes", 0),
            spatial_mesh_available=d.get("spatial_mesh_available", False),
            platform_extras=d.get("platform_extras", {}),
        )


# === Output Primitives (what the OS can ask XR to render) ===

class OverlayAnchor(str, Enum):
    """Where an overlay is positioned."""
    WORLD = "world"            # locked to a world position
    USER = "user"              # attached to a tracked user
    HEAD = "head"              # head-locked HUD
    HAND = "hand"              # attached to a hand


@dataclass
class XROverlay:
    """A visual overlay the OS asks the XR device to render."""
    overlay_id: str                          # unique ID for update/remove
    anchor: OverlayAnchor = OverlayAnchor.WORLD
    anchor_target: str | None = None         # user_id or anchor ID
    position_offset: Vec3 = field(default_factory=Vec3)
    # Visual
    overlay_type: str = "text"               # text, icon, halo, arrow, badge
    text: str = ""
    icon: str = ""
    color: list[int] = field(default_factory=lambda: [255, 255, 255])
    intensity: float = 1.0
    scale: float = 1.0
    # Lifecycle
    duration_ms: int = 0                     # 0 = persistent until removed
    fade_in_ms: int = 200
    fade_out_ms: int = 200

    def to_dict(self) -> dict:
        return {
            "overlay_id": self.overlay_id,
            "anchor": self.anchor.value,
            "anchor_target": self.anchor_target,
            "position_offset": self.position_offset.to_list(),
            "overlay_type": self.overlay_type,
            "text": self.text,
            "icon": self.icon,
            "color": self.color,
            "intensity": round(self.intensity, 2),
            "scale": round(self.scale, 2),
            "duration_ms": self.duration_ms,
            "fade_in_ms": self.fade_in_ms,
            "fade_out_ms": self.fade_out_ms,
        }


@dataclass
class XRSpatialAnchor:
    """A shared spatial anchor for co-located experiences."""
    anchor_id: str
    pose: Pose = field(default_factory=Pose)
    owner_user: str | None = None
    shared: bool = False

    def to_dict(self) -> dict:
        return {
            "anchor_id": self.anchor_id,
            "pose": self.pose.to_dict(),
            "owner_user": self.owner_user,
            "shared": self.shared,
        }
