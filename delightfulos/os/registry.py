"""Device Registry — tracks connected devices and their capabilities.

The single source of truth for "what hardware is available right now."
"""
from __future__ import annotations

import logging
import time

from delightfulos.os.types import DeviceInfo, DeviceType, Capability

log = logging.getLogger("delightfulos.registry")


class DeviceRegistry:

    def __init__(self):
        self._devices: dict[str, DeviceInfo] = {}

    def register(self, info: DeviceInfo) -> None:
        self._devices[info.device_id] = info
        log.info("Device registered: %s (%s) for user %s",
                 info.device_id, info.device_type.value, info.user_id)

    def unregister(self, device_id: str) -> None:
        removed = self._devices.pop(device_id, None)
        if removed:
            log.info("Device unregistered: %s (user %s)", device_id, removed.user_id)

    def get(self, device_id: str) -> DeviceInfo | None:
        return self._devices.get(device_id)

    def get_user_devices(self, user_id: str) -> list[DeviceInfo]:
        return [d for d in self._devices.values() if d.user_id == user_id]

    def get_by_type(self, device_type: DeviceType) -> list[DeviceInfo]:
        return [d for d in self._devices.values() if d.device_type == device_type]

    def get_by_capability(self, cap: Capability) -> list[DeviceInfo]:
        return [d for d in self._devices.values() if cap in d.capabilities]

    def all_users(self) -> set[str]:
        return {d.user_id for d in self._devices.values()}

    def all_devices(self) -> list[DeviceInfo]:
        return list(self._devices.values())

    def touch(self, device_id: str) -> None:
        if device_id in self._devices:
            self._devices[device_id].last_seen = time.time()

    def snapshot(self) -> list[dict]:
        return [
            {
                "device_id": d.device_id,
                "device_type": d.device_type.value,
                "user_id": d.user_id,
                "capabilities": [c.value for c in d.capabilities],
                "connected_at": d.connected_at,
                "last_seen": d.last_seen,
            }
            for d in self._devices.values()
        ]

    def reset(self):
        """Clear all devices. For tests only."""
        self._devices.clear()


# Singleton
registry = DeviceRegistry()
