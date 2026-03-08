"""XR Layer — platform-agnostic abstractions for augmented/mixed reality devices.

This layer defines the universal protocol between DelightfulOS and any XR headset
(Snap Spectacles, Meta Quest, Apple Vision Pro, etc). Platform-specific adapters
live in submodules (e.g., xr.spectacles, xr.quest).

Architecture:
  OS types (Signal/Action) are platform-agnostic.
  The XR layer translates between:
    - Platform-specific input events -> OS Signals
    - OS Actions -> Platform-specific rendering commands

  ┌──────────────┐     ┌──────────────┐     ┌──────────────┐
  │  Spectacles   │     │   Quest 3     │     │  Vision Pro   │
  │  Lens Studio  │     │  Unity/Godot  │     │  RealityKit   │
  └──────┬───────┘     └──────┬───────┘     └──────┬───────┘
         │                     │                     │
    ┌────▼─────────────────────▼─────────────────────▼────┐
    │              XR Protocol (JSON over WS)              │
    ├─────────────────────────────────────────────────────┤
    │  xr.types    — Platform-agnostic XR data types       │
    │  xr.protocol — Message schema (input/output/sync)    │
    │  xr.session  — Session + user management             │
    │  xr.handler  — Base WebSocket handler                │
    ├─────────────────────────────────────────────────────┤
    │  xr.spectacles — Snap Spectacles adapter             │
    │  xr.quest      — Meta Quest adapter (future)         │
    └─────────────────────────────────────────────────────┘
"""

from delightfulos.xr.types import (
    XRPlatform,
    XRCapability,
    XRSceneState,
    XROverlay,
    XRSpatialAnchor,
    TrackedUser,
    HandSide,
    HandState,
    GazeState,
    Vec3,
    Quat,
    Pose,
    OverlayAnchor,
)
from delightfulos.xr.protocol import XRMessage, XRInputEvent, XROutputCommand
from delightfulos.xr.session import XRSession, XRSessionManager, session_manager

__all__ = [
    "XRPlatform", "XRCapability", "XRSceneState", "XROverlay", "XRSpatialAnchor",
    "TrackedUser", "HandState", "GazeState",
    "XRMessage", "XRInputEvent", "XROutputCommand",
    "XRSession", "XRSessionManager", "session_manager",
]
