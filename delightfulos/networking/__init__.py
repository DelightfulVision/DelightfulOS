"""Networking Layer — transport protocols and device connection handlers.

Handles all WebSocket, BLE, and future transport connections.
Device handlers translate raw device protocols into OS-level Signals.
"""

from delightfulos.networking import collar, glasses, simulator

__all__ = ["collar", "glasses", "simulator"]
