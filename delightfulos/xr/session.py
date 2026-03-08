"""XR Session Management — tracks connected XR devices and their capabilities.

Each XR device that connects sends a 'hello' message declaring its platform
and capabilities. The session manager tracks all active sessions and provides
lookup for routing output commands to the right devices.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from delightfulos.xr.types import XRPlatform, XRCapability

log = logging.getLogger("delightfulos.xr.session")


@dataclass
class XRSession:
    """An active XR device connection."""
    session_id: str
    user_id: str
    platform: XRPlatform
    capabilities: list[XRCapability] = field(default_factory=list)
    transport: Any = None           # WebSocket or other transport handle
    connected_at: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def alive(self) -> bool:
        return (time.time() - self.last_seen) < 15.0

    def has_capability(self, cap: XRCapability) -> bool:
        return cap in self.capabilities

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "platform": self.platform.value,
            "capabilities": [c.value for c in self.capabilities],
            "alive": self.alive,
            "connected_at": self.connected_at,
            "last_seen": self.last_seen,
        }


class XRSessionManager:
    """Manages all active XR sessions across all platforms."""

    def __init__(self):
        self._sessions: dict[str, XRSession] = {}

    def register(self, session: XRSession) -> None:
        self._sessions[session.session_id] = session
        log.info("XR session registered: %s (%s) for user %s",
                 session.session_id, session.platform.value, session.user_id)

    def unregister(self, session_id: str) -> None:
        removed = self._sessions.pop(session_id, None)
        if removed:
            log.info("XR session ended: %s (user %s)", session_id, removed.user_id)

    def get(self, session_id: str) -> XRSession | None:
        return self._sessions.get(session_id)

    def get_user_sessions(self, user_id: str) -> list[XRSession]:
        return [s for s in self._sessions.values() if s.user_id == user_id]

    def get_by_platform(self, platform: XRPlatform) -> list[XRSession]:
        return [s for s in self._sessions.values() if s.platform == platform]

    def get_with_capability(self, cap: XRCapability) -> list[XRSession]:
        return [s for s in self._sessions.values() if s.has_capability(cap)]

    def all_sessions(self) -> list[XRSession]:
        return list(self._sessions.values())

    def touch(self, session_id: str) -> None:
        if session_id in self._sessions:
            self._sessions[session_id].last_seen = time.time()

    def reset(self):
        self._sessions.clear()


# Singleton
session_manager = XRSessionManager()
