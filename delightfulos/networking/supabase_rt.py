"""Supabase Realtime bridge — connects DelightfulOS to Snap Spectacles.

Snap Spectacles use Supabase Realtime (via Snap's hosted Supabase on snapcloud.dev)
for bidirectional communication. This module bridges the OS signal bus to Supabase
broadcast channels, enabling:

  - Spectacles → OS: cursor positions, control mode changes, user presence
  - OS → Spectacles: state updates, AI actions, haptic commands, AR overlays

Protocol (matches Spectacles-Sample/Snap Cloud/RealtimeCursor.ts):
  Channel naming: Spectacles join `cursor-{channelName}`, so our Phoenix topic
  must be `realtime:cursor-{channelName}` to match.

  User ID conventions from the Spectacles samples:
    - Spectacles clients: "spectacles_" + random suffix
    - Web/PC clients:     "pc_" + random suffix
    - Server:             "server_delightfulos"

  Spectacles → Server:
    cursor-move:   {channel_name, user_id, user_name, x, y, color, timestamp}
    control-mode:  {mode: "spectacles_leader"|"pc_leader", user_id, timestamp}
    cursor-enter:  {user_id, user_name, color, timestamp}
    cursor-leave:  {user_id, user_name, color, timestamp}

  Server → Spectacles:
    os-state:          {user_id, speech_active, stress_level, engagement, ...}
    all-users-state:   {users: [...], cursors: {...}, count, timestamp}
    os-action:         {action_type, target_user, payload}
    live-transcript:   {user_id, text, source: "input"|"output"}
    ar-overlay:        {target_user, type, color, ...}
"""
from __future__ import annotations

import asyncio
import json
import logging
import time

import websockets

from delightfulos.os.types import Signal, DeviceInfo, DeviceType, Capability
from delightfulos.os.bus import bus
from delightfulos.os.state import estimator
from delightfulos.os.registry import registry

log = logging.getLogger("delightfulos.supabase_rt")

# Max reconnect attempts before giving up
MAX_RECONNECT_ATTEMPTS = 10
RECONNECT_BASE_DELAY = 1.0  # seconds, doubles each attempt


class SupabaseRealtimeBridge:
    """Bridges DelightfulOS signals to/from Supabase Realtime channels."""

    def __init__(self):
        self._ws = None
        self._connected = False
        self._channel: str | None = None
        self._url: str | None = None
        self._token: str | None = None
        self._ref_counter = 0
        self._receive_task: asyncio.Task | None = None
        self._heartbeat_task: asyncio.Task | None = None
        self._state_push_task: asyncio.Task | None = None
        self._reconnect_task: asyncio.Task | None = None
        self._shutting_down = False
        self._subscribed = False  # bus subscription guard (only subscribe once)
        # Track latest cursor positions for each user (for multiplayer state)
        self._cursor_positions: dict[str, dict] = {}

    @property
    def connected(self) -> bool:
        return self._connected

    def _next_ref(self) -> str:
        self._ref_counter += 1
        return str(self._ref_counter)

    def _phoenix_topic(self) -> str:
        """Build the Phoenix topic name matching Spectacles convention.

        Spectacles RealtimeCursor.ts joins: `cursor-${channelName}`
        Phoenix wire format is: `realtime:cursor-${channelName}`
        """
        return f"realtime:cursor-{self._channel}"

    async def connect(self, supabase_url: str, supabase_token: str, channel_name: str):
        """Connect to Supabase Realtime and join a broadcast channel."""
        self._url = supabase_url
        self._token = supabase_token
        self._channel = channel_name
        self._shutting_down = False

        # Build WebSocket URL
        # snapcloud.dev uses /realtime/v1/websocket
        base = supabase_url.rstrip("/")
        ws_base = base.replace("https://", "wss://").replace("http://", "ws://")
        ws_url = f"{ws_base}/realtime/v1/websocket?apikey={supabase_token}&vsn=1.0.0"

        log.info("Connecting to Supabase Realtime at %s", base)
        self._ws = await websockets.connect(ws_url)

        topic = self._phoenix_topic()

        # Join the channel with broadcast + presence
        join_msg = {
            "topic": topic,
            "event": "phx_join",
            "payload": {
                "config": {
                    "broadcast": {"self": False},
                    "presence": {"key": "delightfulos_server"},
                }
            },
            "ref": self._next_ref(),
        }
        await self._ws.send(json.dumps(join_msg))

        # Wait for join confirmation
        resp = json.loads(await asyncio.wait_for(self._ws.recv(), timeout=10))
        if resp.get("payload", {}).get("status") != "ok":
            raise RuntimeError(f"Failed to join channel: {resp}")

        self._connected = True
        log.info("Joined Supabase channel 'cursor-%s' (topic=%s)", channel_name, topic)

        # Start background tasks
        self._receive_task = asyncio.create_task(self._receive_loop())
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        self._state_push_task = asyncio.create_task(self._state_push_loop())

        # Subscribe to OS actions for forwarding (only once)
        if not self._subscribed:
            bus.subscribe_action(self._on_os_action)
            bus.subscribe_signal(self._on_transcription, signal_type="live_input_transcription")
            bus.subscribe_signal(self._on_transcription, signal_type="live_output_transcription")
            self._subscribed = True

    async def disconnect(self):
        """Disconnect from Supabase Realtime."""
        self._shutting_down = True
        self._connected = False

        for task in (self._receive_task, self._heartbeat_task,
                     self._state_push_task, self._reconnect_task):
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None

        log.info("Disconnected from Supabase Realtime")

    async def broadcast(self, event: str, payload: dict):
        """Send a broadcast event to the channel."""
        if not self._connected or not self._ws:
            return

        msg = {
            "topic": self._phoenix_topic(),
            "event": "broadcast",
            "payload": {
                "type": "broadcast",
                "event": event,
                "payload": payload,
            },
            "ref": self._next_ref(),
        }

        try:
            await self._ws.send(json.dumps(msg))
        except Exception:
            log.warning("Failed to send broadcast event '%s'", event)
            self._connected = False

    # ------------------------------------------------------------------ #
    #  Receive loop                                                       #
    # ------------------------------------------------------------------ #

    async def _receive_loop(self):
        """Receive messages from Supabase and emit signals on the OS bus."""
        try:
            while self._connected and self._ws:
                try:
                    raw = await asyncio.wait_for(self._ws.recv(), timeout=30)
                except asyncio.TimeoutError:
                    continue

                msg = json.loads(raw)
                event = msg.get("event")
                payload = msg.get("payload", {})

                # Skip heartbeat replies and system messages
                if event in ("phx_reply", "presence_state", "presence_diff"):
                    continue

                # Handle broadcast events from Spectacles / web clients
                if event == "broadcast":
                    inner_event = payload.get("event", "")
                    inner_payload = payload.get("payload", {})
                    await self._handle_spectacles_event(inner_event, inner_payload)

        except asyncio.CancelledError:
            return
        except websockets.exceptions.ConnectionClosed:
            log.warning("Supabase WebSocket closed")
            self._connected = False
            self._schedule_reconnect()
        except Exception:
            log.exception("Supabase receive error")
            self._connected = False
            self._schedule_reconnect()

    # ------------------------------------------------------------------ #
    #  Event handling                                                      #
    # ------------------------------------------------------------------ #

    def _resolve_user_id(self, raw_user_id: str) -> tuple[str, str]:
        """Resolve user_id and device_id from a raw broadcast user_id.

        Spectacles samples prefix user_id with 'spectacles_' or 'pc_'.
        We strip the prefix for the OS user_id and use the raw value
        for the device_id to avoid double-prefixing.

        Returns: (user_id, device_id)
        """
        if raw_user_id.startswith("spectacles_"):
            # e.g. "spectacles_a3b8x" -> user_id="a3b8x", device_id="spectacles_a3b8x"
            return raw_user_id.removeprefix("spectacles_"), raw_user_id
        elif raw_user_id.startswith("pc_"):
            return raw_user_id.removeprefix("pc_"), raw_user_id
        else:
            # Unknown prefix — use as-is
            return raw_user_id, f"spectacles_{raw_user_id}"

    async def _handle_spectacles_event(self, event: str, payload: dict):
        """Convert Spectacles broadcast events into OS signals."""
        raw_user_id = payload.get("user_id", "unknown")
        user_id, device_id = self._resolve_user_id(raw_user_id)

        if event == "cursor-move":
            # Touch the device so it stays alive in the registry
            registry.touch(device_id)

            # Cache cursor position for multiplayer state broadcasts
            self._cursor_positions[user_id] = {
                "x": payload.get("x", 0),
                "y": payload.get("y", 0),
                "color": payload.get("color"),
                "user_name": payload.get("user_name"),
                "timestamp": payload.get("timestamp", time.time()),
            }

            await bus.emit_signal(Signal(
                source_device=device_id,
                source_user=user_id,
                signal_type="gaze_position",
                confidence=1.0,
                value={
                    "x": payload.get("x", 0),
                    "y": payload.get("y", 0),
                    "color": payload.get("color"),
                },
            ))

        elif event == "control-mode":
            # Spectacles samples send "spectacles_leader" / "pc_leader"
            mode = payload.get("mode", "free")
            await bus.emit_signal(Signal(
                source_device=device_id,
                source_user=user_id,
                signal_type="mode_change",
                confidence=1.0,
                value={"mode": mode},
            ))

        elif event == "cursor-enter":
            # Register Spectacles as a device so the output router can find them
            registry.register(DeviceInfo(
                device_id=device_id,
                device_type=DeviceType.GLASSES,
                user_id=user_id,
                capabilities=[
                    Capability.OUTPUT_VISUAL_AR,
                    Capability.SENSE_CAMERA,
                    Capability.SENSE_IMU,
                ],
                transport=None,  # no direct WS — actions routed via Supabase broadcast
                metadata={
                    "connection": "supabase_realtime",
                    "user_name": payload.get("user_name"),
                    "color": payload.get("color"),
                },
            ))
            await bus.emit_signal(Signal(
                source_device=device_id,
                source_user=user_id,
                signal_type="presence",
                confidence=1.0,
                value={
                    "user_name": payload.get("user_name"),
                    "color": payload.get("color"),
                },
            ))
            log.info("Spectacles joined: %s (%s) device=%s",
                     payload.get("user_name", user_id), user_id, device_id)

        elif event == "cursor-leave":
            registry.unregister(device_id)
            self._cursor_positions.pop(user_id, None)
            await bus.emit_signal(Signal(
                source_device=device_id,
                source_user=user_id,
                signal_type="absence",
                confidence=1.0,
                value={
                    "user_name": payload.get("user_name"),
                    "color": payload.get("color"),
                },
            ))
            log.info("Spectacles left: %s (%s)", payload.get("user_name", user_id), user_id)

    # ------------------------------------------------------------------ #
    #  Bus subscribers (OS -> Spectacles)                                  #
    # ------------------------------------------------------------------ #

    async def _on_transcription(self, signal: Signal):
        """Forward live transcription signals to Spectacles."""
        if not self._connected:
            return
        source = "input" if signal.signal_type == "live_input_transcription" else "output"
        await self.push_transcription(
            user_id=signal.source_user,
            text=signal.value.get("text", ""),
            source=source,
        )

    async def _on_os_action(self, action):
        """Forward OS actions to Spectacles via broadcast.

        Only forwards actions that target glasses/AR — no point sending
        collar haptic commands to Spectacles.
        """
        if not self._connected:
            return

        # Skip actions that target non-glasses devices
        if action.target_type and action.target_type not in ("glasses", None):
            return

        await self.broadcast("os-action", {
            "action_type": action.action_type,
            "target_user": action.target_user,
            "target_type": action.target_type,
            "payload": action.payload,
            "timestamp": action.timestamp,
        })

    # ------------------------------------------------------------------ #
    #  Background loops                                                    #
    # ------------------------------------------------------------------ #

    async def _heartbeat_loop(self):
        """Send Phoenix heartbeats to keep the connection alive."""
        try:
            while self._connected and self._ws:
                await asyncio.sleep(25)
                heartbeat = {
                    "topic": "phoenix",
                    "event": "heartbeat",
                    "payload": {},
                    "ref": self._next_ref(),
                }
                try:
                    await self._ws.send(json.dumps(heartbeat))
                except Exception:
                    self._connected = False
                    self._schedule_reconnect()
                    return
        except asyncio.CancelledError:
            return

    async def _state_push_loop(self):
        """Periodically push user states to Spectacles (every 500ms).

        Sends two event types:
          - 'all-users-state': all users + cursor positions in one message
          - 'os-state': per-user state (for simple single-user clients)
        """
        try:
            while self._connected:
                await asyncio.sleep(0.5)

                states = estimator.all_states()
                if not states:
                    continue

                now = time.time()

                # Build per-user state and collect for bulk message
                all_users = []
                for state in states:
                    user_data = {
                        "user_id": state.user_id,
                        "speech_active": state.speech_active,
                        "speech_intent": round(state.speech_intent, 2),
                        "stress_level": round(state.stress_level, 2),
                        "engagement": round(state.engagement, 2),
                        "attention_direction": state.attention_direction,
                        "overloaded": state.overloaded,
                        "mode": state.mode.value,
                        "hidden_overlays": sorted(state.hidden_overlays),
                    }
                    all_users.append(user_data)
                    # Per-user event for simple clients
                    await self.broadcast("os-state", {
                        **user_data,
                        "timestamp": now,
                    })

                # Multiplayer: all users + cursor positions in one broadcast
                # so Spectacles can render overlays for everyone in one frame
                await self.broadcast("all-users-state", {
                    "users": all_users,
                    "cursors": self._cursor_positions,
                    "count": len(all_users),
                    "timestamp": now,
                })

        except asyncio.CancelledError:
            return

    # ------------------------------------------------------------------ #
    #  Auto-reconnect                                                      #
    # ------------------------------------------------------------------ #

    def _schedule_reconnect(self):
        """Schedule a reconnection attempt if not shutting down."""
        if self._shutting_down:
            return
        if self._reconnect_task and not self._reconnect_task.done():
            return  # already reconnecting
        self._reconnect_task = asyncio.create_task(self._reconnect_loop())

    async def _reconnect_loop(self):
        """Attempt to reconnect with exponential backoff."""
        delay = RECONNECT_BASE_DELAY
        for attempt in range(1, MAX_RECONNECT_ATTEMPTS + 1):
            if self._shutting_down:
                return
            log.info("Supabase reconnect attempt %d/%d in %.1fs...",
                     attempt, MAX_RECONNECT_ATTEMPTS, delay)
            await asyncio.sleep(delay)
            try:
                # Cancel stale background tasks before reconnecting
                for task in (self._receive_task, self._heartbeat_task,
                             self._state_push_task):
                    if task and not task.done():
                        task.cancel()
                        try:
                            await task
                        except asyncio.CancelledError:
                            pass
                if self._ws:
                    try:
                        await self._ws.close()
                    except Exception:
                        pass
                    self._ws = None

                await self.connect(self._url, self._token, self._channel)
                log.info("Supabase reconnected successfully")
                return
            except Exception:
                log.warning("Supabase reconnect attempt %d failed", attempt, exc_info=True)
                delay = min(delay * 2, 30.0)  # cap at 30s

        log.error("Supabase reconnection failed after %d attempts", MAX_RECONNECT_ATTEMPTS)

    # ------------------------------------------------------------------ #
    #  Public push helpers                                                 #
    # ------------------------------------------------------------------ #

    async def push_transcription(self, user_id: str, text: str, source: str = "input"):
        """Push a live transcription to Spectacles for AR display."""
        await self.broadcast("live-transcript", {
            "user_id": user_id,
            "text": text,
            "source": source,
            "timestamp": time.time(),
        })

    async def push_ar_overlay(self, target_user: str, overlay: dict):
        """Push an AR overlay command to Spectacles."""
        await self.broadcast("ar-overlay", {
            "target_user": target_user,
            **overlay,
            "timestamp": time.time(),
        })


# Singleton
supabase_bridge = SupabaseRealtimeBridge()
