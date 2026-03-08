"""Spectacles Adapter — Snap Spectacles-specific protocol mappings.

Defines the capabilities of Snap Spectacles and provides helpers for
translating between the XR protocol and Spectacles-native concepts.

This is the SERVER-SIDE adapter. The Lens Studio client also needs a
matching TypeScript adapter (see docs/xr-client-guide.md or the
spectacles-protocol.json).

Spectacles-specific concepts:
  - Connected Lenses (Sync Kit) for multi-user sessions
  - Interaction Kit (SIK) for hand tracking + gestures
  - Supabase Realtime for cloud sync (optional)
  - BLE bridge via Spectacles Mobile Kit
  - ASR for voice-to-text on device

Mapping to XR protocol:
  - SIK hand events -> XRInputType.PINCH, GESTURE
  - Camera transform -> XRInputType.GAZE_SHIFT
  - Connected Lens session -> co-located multi-user
  - Overlay commands -> Lens Studio SceneObject manipulation
"""
from __future__ import annotations

from delightfulos.xr.types import XRPlatform, XRCapability


# What Snap Spectacles can do
SPECTACLES_CAPABILITIES = [
    XRCapability.HAND_TRACKING,
    XRCapability.HEAD_TRACKING,
    XRCapability.DEPTH_SENSING,
    XRCapability.AR_OVERLAY,
    XRCapability.SPATIAL_AUDIO,
    XRCapability.VOICE_INPUT,
    XRCapability.CO_LOCATION,
    XRCapability.SHARED_ANCHOR,
]

SPECTACLES_PLATFORM = XRPlatform.SPECTACLES

# Spectacles-specific gesture mappings
# Lens Studio SIK produces these events natively
SPECTACLES_GESTURES = {
    "pinch_down": "pinch_start",
    "pinch_up": "pinch_end",
    "pinch_hold": "pinch_hold",
    "poke": "tap",
}

# Overlay type mappings for Spectacles rendering
# The Lens client maps these to SceneObject configurations
SPECTACLES_OVERLAY_TYPES = {
    "halo": {
        "lens_prefab": "HaloOverlay",
        "description": "Glowing ring around a tracked user",
        "supports_color": True,
        "supports_animation": True,
    },
    "text": {
        "lens_prefab": "TextOverlay",
        "description": "Floating text near a user or world position",
        "supports_color": True,
        "supports_animation": True,
    },
    "icon": {
        "lens_prefab": "IconOverlay",
        "description": "Small icon badge (speech bubble, star, etc)",
        "supports_color": True,
        "supports_animation": True,
    },
    "arrow": {
        "lens_prefab": "ArrowOverlay",
        "description": "Directional arrow pointing at a user",
        "supports_color": True,
        "supports_animation": False,
    },
    "badge": {
        "lens_prefab": "BadgeOverlay",
        "description": "Status badge attached to a user (speaking, stressed)",
        "supports_color": True,
        "supports_animation": True,
    },
}


def spectacles_hello_payload() -> dict:
    """Generate the hello payload a Spectacles client should send.

    Use this as a reference for your Lens Studio TypeScript client.
    """
    return {
        "platform": SPECTACLES_PLATFORM.value,
        "capabilities": [c.value for c in SPECTACLES_CAPABILITIES],
        "metadata": {
            "sdk": "lens_studio",
            "sync_kit": True,
            "interaction_kit": True,
        },
    }
