"""Device and system specs — loaded from YAML data files.

This module provides backward-compatible top-level names (COLLAR_V1, SPECTACLES, etc.)
by loading from the library. New code should use `hdl.loader.library` directly.
"""
from delightfulos.hdl.loader import library

# Ensure YAML data is loaded
library.ensure_loaded()


def __getattr__(name: str):
    """Lazy access to devices and systems by conventional Python names."""
    _DEVICE_MAP = {
        "COLLAR_V1": "collar_v1",
        "SPECTACLES": "spectacles",
        "CHEST_BAND": "chest_band",
        "EARABLE": "earable",
        "SMART_RING": "smart_ring",
        "HAPTIC_GLOVE": "haptic_glove",
    }
    _SYSTEM_MAP = {
        "SOCIAL_RADAR": "social_radar",
        "FULL_BODY_STACK": "full_body",
        "INTIMATE_SYSTEM": "intimate",
        "FULL_TOUCH_SYSTEM": "full_touch",
    }

    if name in _DEVICE_MAP:
        library.ensure_loaded()
        key = _DEVICE_MAP[name]
        if key in library.devices:
            return library.devices[key]
        raise AttributeError(f"Device '{key}' not found in library")

    if name in _SYSTEM_MAP:
        library.ensure_loaded()
        key = _SYSTEM_MAP[name]
        if key in library.systems:
            return library.systems[key]
        raise AttributeError(f"System '{key}' not found in library")

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
