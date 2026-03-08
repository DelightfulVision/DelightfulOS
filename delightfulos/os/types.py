"""Core types for the wearable OS — shared across all layers.

No imports from any other delightfulos module. This is the foundation.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# === Device Classification ===

class DeviceType(str, Enum):
    COLLAR = "collar"
    GLASSES = "glasses"
    WATCH = "watch"
    EARABLE = "earable"
    RING = "ring"
    CHEST_BAND = "chest_band"
    PHONE = "phone"
    SIMULATOR = "simulator"


class Capability(str, Enum):
    # Sensing
    SENSE_VIBRATION = "sense_vibration"
    SENSE_AUDIO = "sense_audio"
    SENSE_IMU = "sense_imu"
    SENSE_DEPTH = "sense_depth"
    SENSE_CAMERA = "sense_camera"
    SENSE_RESPIRATION = "sense_respiration"
    SENSE_HEART_RATE = "sense_heart_rate"
    SENSE_EDA = "sense_eda"
    SENSE_TEMPERATURE = "sense_temperature"
    SENSE_PROXIMITY = "sense_proximity"
    SENSE_GPS = "sense_gps"
    SENSE_GESTURE = "sense_gesture"
    # Output
    OUTPUT_HAPTIC = "output_haptic"
    OUTPUT_VISUAL_AR = "output_visual_ar"
    OUTPUT_AUDIO = "output_audio"
    OUTPUT_LED = "output_led"
    OUTPUT_DISPLAY = "output_display"
    # Compute
    COMPUTE_EDGE = "compute_edge"
    COMPUTE_BRIDGE = "compute_bridge"


# === Device Info ===

@dataclass
class DeviceInfo:
    device_id: str
    device_type: DeviceType
    user_id: str
    capabilities: list[Capability] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    transport: Any = None  # WebSocket, BLE handle, etc. — opaque to OS layer
    connected_at: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)


# === Signal & Action (the two message types on the bus) ===

@dataclass
class Signal:
    """A signal event from any device in the stack."""
    source_device: str
    source_user: str
    signal_type: str
    confidence: float = 1.0
    value: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


@dataclass
class Action:
    """An output action routed to a specific device or user."""
    target_user: str
    target_device: str | None = None
    target_type: str | None = None
    action_type: str = "none"
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
