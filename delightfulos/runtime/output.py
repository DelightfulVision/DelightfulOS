"""Output Router — delivers actions to the correct device.

Routes by: specific device > device type > capability match > any user device.
Transport-agnostic: uses the `transport` field on DeviceInfo (WebSocket, BLE, etc).
"""
from __future__ import annotations

import json
import logging

from delightfulos.os.types import Action, Capability, DeviceType
from delightfulos.os.registry import registry

log = logging.getLogger("delightfulos.output")

_CAPABILITY_MAP = {
    "haptic": Capability.OUTPUT_HAPTIC,
    "highlight": Capability.OUTPUT_VISUAL_AR,
    "suppress": Capability.OUTPUT_VISUAL_AR,
    "fade": Capability.OUTPUT_VISUAL_AR,
    "narrate": Capability.OUTPUT_AUDIO,
}


async def route_action(action: Action):
    """Route an action to the appropriate connected device."""

    # Specific device targeted
    if action.target_device:
        device = registry.get(action.target_device)
        if device and device.transport:
            await _send(device.transport, action)
            return
        log.debug("Target device %s not found or has no transport", action.target_device)

    # Route by device type
    if action.target_type:
        try:
            target_type = DeviceType(action.target_type)
        except ValueError:
            log.warning("Unknown target_type '%s' in action %s", action.target_type, action.action_type)
            return
        for device in registry.get_user_devices(action.target_user):
            if device.device_type == target_type and device.transport:
                await _send(device.transport, action)
                return

    # Route by capability
    needed_cap = _CAPABILITY_MAP.get(action.action_type)
    if needed_cap:
        for device in registry.get_user_devices(action.target_user):
            if needed_cap in device.capabilities and device.transport:
                await _send(device.transport, action)
                return

    # Fallback: any connected device for this user
    for device in registry.get_user_devices(action.target_user):
        if device.transport:
            await _send(device.transport, action)
            return

    log.debug("No device available for action %s -> user %s", action.action_type, action.target_user)


async def _send(transport, action: Action):
    """Send an action over a WebSocket transport."""
    try:
        await transport.send_text(json.dumps({
            "action": action.action_type,
            "target_user": action.target_user,
            "payload": action.payload,
            "timestamp": action.timestamp,
        }))
    except Exception:
        log.warning("Failed to send action '%s' to user '%s' — transport broken, removing device",
                    action.action_type, action.target_user)
        # Find and unregister the device with this broken transport
        for device in registry.all_devices():
            if device.transport is transport:
                registry.unregister(device.device_id)
                break
