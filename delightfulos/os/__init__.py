"""OS Layer — core primitives for the wearable operating system.

Pure data types and in-process services with zero external dependencies.
Nothing here knows about HTTP, WebSockets, AI, or any specific device.
"""

from delightfulos.os.types import DeviceType, Capability, DeviceInfo, Signal, Action
from delightfulos.os.registry import DeviceRegistry, registry
from delightfulos.os.bus import SignalBus, bus
from delightfulos.os.state import BodyState, StateEstimator, estimator, UserMode

__all__ = [
    "DeviceType", "Capability", "DeviceInfo", "Signal", "Action",
    "DeviceRegistry", "registry",
    "SignalBus", "bus",
    "BodyState", "StateEstimator", "estimator", "UserMode",
]
