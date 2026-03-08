"""Gemini Live — bidirectional realtime audio via Google's native audio API.

Provides:
  - Per-user Gemini Live sessions with persistent WebSocket connections
  - Realtime audio input (16kHz 16-bit PCM mono) → Gemini → audio output (24kHz)
  - Input + output transcription via Gemini's built-in transcription
  - Session resumption for long-running connections
  - Context window compression for unlimited session duration
  - Artifact generation (summaries, notes) from accumulated transcriptions

Architecture:
  Collar (PDM mic) → server → GeminiLiveSession → Gemini Live API
                                    ↓
                              Audio output (24kHz PCM) → Glasses/speaker
                              Input transcription → Signal bus
                              Output transcription → Signal bus
                              Artifacts → Signal bus

Audio specs:
  Input:  16-bit PCM, 16kHz, mono (little-endian)
  Output: 16-bit PCM, 24kHz, mono (little-endian)
  Chunk:  1024 bytes per frame

Session limits (without compression): 15min audio-only, 2min audio+video.
With context_window_compression enabled: unlimited.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

from google import genai
from google.genai import types

from delightfulos.os.types import Signal
from delightfulos.os.bus import bus
from delightfulos.ai.context import context_log

log = logging.getLogger("delightfulos.gemini_live")

INPUT_SAMPLE_RATE = 16000
OUTPUT_SAMPLE_RATE = 24000
CHUNK_SIZE = 1024

SYSTEM_INSTRUCTION = (
    "You are a wearable AI assistant integrated into AR glasses and a sensor collar. "
    "You hear the user's conversations in real time. Your role:\n"
    "1. Listen and understand what's being discussed\n"
    "2. When asked, provide brief helpful responses via audio\n"
    "3. Track conversation topics for later summarization\n"
    "4. You have access to body sensor context (stress, speech intent, engagement) — "
    "use it to understand the social dynamics\n"
    "Be concise. You're in someone's ear — don't ramble.\n\n"
    "CURRENT SENSOR CONTEXT:\n{context_narrative}"
)


@dataclass
class LiveSessionState:
    """Tracks state for a single user's Gemini Live session."""
    user_id: str
    session: object = None
    connected: bool = False
    created_at: float = field(default_factory=time.time)
    last_audio_in: float = 0.0
    last_audio_out: float = 0.0
    audio_out_bytes: int = 0
    input_transcripts: list[str] = field(default_factory=list)
    output_transcripts: list[str] = field(default_factory=list)
    resume_handle: str | None = None
    _receive_task: asyncio.Task | None = field(default=None, repr=False)
    _audio_out_queue: asyncio.Queue = field(default_factory=asyncio.Queue, repr=False)
    _context_manager: object = field(default=None, repr=False)


class GeminiLiveManager:
    """Manages per-user Gemini Live sessions for realtime audio."""

    CONTEXT_PUSH_INTERVAL = 10.0  # push sensor context every 10s

    def __init__(self):
        self._sessions: dict[str, LiveSessionState] = {}
        self._client: genai.Client | None = None
        self._context_push_task: asyncio.Task | None = None

    def _get_client(self) -> genai.Client:
        if self._client is None:
            from delightfulos.ai.config import settings
            if not settings.gemini_api_key:
                raise RuntimeError("GEMINI_API_KEY not configured")
            self._client = genai.Client(api_key=settings.gemini_api_key)
        return self._client

    @property
    def enabled(self) -> bool:
        from delightfulos.ai.config import settings
        return bool(settings.gemini_api_key)

    async def connect(
        self,
        user_id: str,
        system_instruction: str | None = None,
        voice: str = "Kore",
    ) -> LiveSessionState:
        """Open a Gemini Live session for a user.

        Uses context window compression for unlimited duration and enables
        both input and output transcription.
        """
        existing = self._sessions.get(user_id)
        if existing and existing.connected:
            return existing

        from delightfulos.ai.config import settings
        client = self._get_client()

        # Build session resumption config if we have a previous handle
        resume_config = None
        if existing and existing.resume_handle:
            resume_config = types.SessionResumptionConfig(handle=existing.resume_handle)
            log.info("Resuming Gemini Live session for %s", user_id)
        else:
            resume_config = types.SessionResumptionConfig()

        # Inject current sensor narrative into system instruction
        instruction = system_instruction or SYSTEM_INSTRUCTION
        narrative = context_log.narrative(limit=15, user=user_id)
        instruction = instruction.replace("{context_narrative}", narrative)

        config = types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            system_instruction=instruction,
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice),
                ),
            ),
            input_audio_transcription=types.AudioTranscriptionConfig(),
            output_audio_transcription=types.AudioTranscriptionConfig(),
            context_window_compression=types.ContextWindowCompressionConfig(
                sliding_window=types.SlidingWindow(),
            ),
            session_resumption=resume_config,
        )

        log.info("Connecting Gemini Live for user %s (model=%s, voice=%s)",
                 user_id, settings.gemini_live_model, voice)

        ctx = client.aio.live.connect(model=settings.gemini_live_model, config=config)
        session = await ctx.__aenter__()

        state = LiveSessionState(
            user_id=user_id,
            session=session,
            connected=True,
            _context_manager=ctx,
        )
        # Preserve transcripts from previous session if resuming
        if existing:
            state.input_transcripts = existing.input_transcripts
            state.output_transcripts = existing.output_transcripts

        state._receive_task = asyncio.create_task(self._receive_loop(state))
        self._sessions[user_id] = state

        # Start periodic context push if not already running
        if self._context_push_task is None or self._context_push_task.done():
            self._context_push_task = asyncio.create_task(self._context_push_loop())

        log.info("Gemini Live connected for user %s", user_id)
        return state

    async def disconnect(self, user_id: str):
        """Close a user's Gemini Live session."""
        state = self._sessions.pop(user_id, None)
        if state is None:
            return

        state.connected = False
        if state._receive_task and not state._receive_task.done():
            state._receive_task.cancel()
            try:
                await state._receive_task
            except asyncio.CancelledError:
                pass

        if state._context_manager:
            try:
                await state._context_manager.__aexit__(None, None, None)
            except Exception:
                pass

        log.info("Gemini Live disconnected for user %s", user_id)

    async def send_audio(self, user_id: str, pcm_bytes: bytes):
        """Send raw PCM audio (16kHz 16-bit mono) to a user's Gemini Live session."""
        state = self._sessions.get(user_id)
        if not state or not state.connected:
            return

        state.last_audio_in = time.time()

        for i in range(0, len(pcm_bytes), CHUNK_SIZE):
            chunk = pcm_bytes[i:i + CHUNK_SIZE]
            try:
                await state.session.send_realtime_input(
                    audio=types.Blob(data=chunk, mime_type="audio/pcm;rate=16000"),
                )
            except Exception:
                log.warning("Failed to send audio to Gemini Live for %s", user_id)
                state.connected = False
                return

    async def send_text(self, user_id: str, text: str):
        """Send a text message to the user's Gemini Live session."""
        state = self._sessions.get(user_id)
        if not state or not state.connected:
            return

        try:
            await state.session.send_client_content(
                turns=types.Content(
                    role="user",
                    parts=[types.Part(text=text)],
                ),
                turn_complete=True,
            )
        except Exception:
            log.warning("Failed to send text to Gemini Live for %s", user_id)

    def get_audio_output(self, user_id: str) -> asyncio.Queue:
        """Get the audio output queue for a user (24kHz 16-bit PCM chunks)."""
        state = self._sessions.get(user_id)
        if state:
            return state._audio_out_queue
        return asyncio.Queue()

    async def _receive_loop(self, state: LiveSessionState):
        """Background task: receives audio, transcriptions, and control messages."""
        try:
            while state.connected:
                async for response in state.session.receive():
                    if not state.connected:
                        return

                    sc = response.server_content
                    if sc:
                        # Audio + text from model turn
                        if sc.model_turn:
                            for part in sc.model_turn.parts:
                                if part.inline_data and isinstance(part.inline_data.data, bytes):
                                    state.last_audio_out = time.time()
                                    state.audio_out_bytes += len(part.inline_data.data)
                                    await state._audio_out_queue.put(part.inline_data.data)

                        # Output transcription (what the model said)
                        if sc.output_transcription and sc.output_transcription.text:
                            text = sc.output_transcription.text.strip()
                            if text:
                                state.output_transcripts.append(text)
                                await bus.emit_signal(Signal(
                                    source_device=f"gemini_live_{state.user_id}",
                                    source_user=state.user_id,
                                    signal_type="live_output_transcription",
                                    confidence=1.0,
                                    value={"text": text},
                                ))

                        # Input transcription (what the user said)
                        if sc.input_transcription and sc.input_transcription.text:
                            text = sc.input_transcription.text.strip()
                            if text:
                                state.input_transcripts.append(text)
                                await bus.emit_signal(Signal(
                                    source_device=f"gemini_live_{state.user_id}",
                                    source_user=state.user_id,
                                    signal_type="live_input_transcription",
                                    confidence=1.0,
                                    value={"text": text},
                                ))

                        # Interruption — clear pending audio output
                        if sc.interrupted:
                            while not state._audio_out_queue.empty():
                                try:
                                    state._audio_out_queue.get_nowait()
                                except asyncio.QueueEmpty:
                                    break
                            await bus.emit_signal(Signal(
                                source_device=f"gemini_live_{state.user_id}",
                                source_user=state.user_id,
                                signal_type="live_interrupted",
                                confidence=1.0,
                            ))

                        if sc.turn_complete:
                            break

                    # Session resumption — save handle for reconnection
                    if response.session_resumption_update:
                        update = response.session_resumption_update
                        if update.resumable and update.new_handle:
                            state.resume_handle = update.new_handle

                    # GoAway — server is about to close, reconnect
                    if response.go_away is not None:
                        log.warning("Gemini Live GoAway for %s (time_left=%s), will reconnect",
                                    state.user_id, response.go_away.time_left)
                        state.connected = False
                        # Trigger reconnection
                        asyncio.create_task(self._reconnect(state.user_id))
                        return

        except asyncio.CancelledError:
            return
        except Exception:
            log.exception("Gemini Live receive error for %s", state.user_id)
            state.connected = False

    async def _reconnect(self, user_id: str):
        """Attempt to reconnect after a GoAway or connection drop."""
        try:
            await asyncio.sleep(0.5)
            await self.connect(user_id)
            log.info("Gemini Live reconnected for %s", user_id)
        except Exception:
            log.exception("Gemini Live reconnection failed for %s", user_id)

    async def generate_artifact(self, user_id: str, artifact_type: str = "summary") -> str | None:
        """Generate an artifact from accumulated transcriptions using standard Gemini."""
        state = self._sessions.get(user_id)
        if not state:
            return None

        # Interleave input and output transcripts for context
        all_text = []
        for t in state.input_transcripts:
            all_text.append(f"User: {t}")
        for t in state.output_transcripts:
            all_text.append(f"AI: {t}")

        if not all_text:
            return None

        transcript = "\n".join(all_text)

        prompts = {
            "summary": f"Summarize this conversation concisely:\n\n{transcript}",
            "notes": f"Extract structured meeting notes with key points and decisions:\n\n{transcript}",
            "action_items": f"List action items and next steps from this conversation:\n\n{transcript}",
        }

        prompt = prompts.get(artifact_type, prompts["summary"])

        try:
            client = self._get_client()
            resp = await client.aio.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
            )
            artifact_text = resp.text.strip() if resp.text else None

            if artifact_text:
                await bus.emit_signal(Signal(
                    source_device=f"gemini_live_{user_id}",
                    source_user=user_id,
                    signal_type="artifact",
                    confidence=1.0,
                    value={
                        "type": artifact_type,
                        "text": artifact_text,
                        "input_chunks": len(state.input_transcripts),
                        "output_chunks": len(state.output_transcripts),
                    },
                ))

            return artifact_text
        except Exception:
            log.exception("Artifact generation failed for %s", user_id)
            return None

    async def _context_push_loop(self):
        """Periodically push sensor context narrative to active Gemini Live sessions."""
        try:
            while True:
                await asyncio.sleep(self.CONTEXT_PUSH_INTERVAL)
                narrative = context_log.narrative(limit=10)
                if narrative == "No significant events yet.":
                    continue
                for user_id, state in list(self._sessions.items()):
                    if state.connected:
                        user_narrative = context_log.narrative(limit=8, user=user_id)
                        text = (
                            f"[SENSOR UPDATE] Recent social dynamics:\n{narrative}\n"
                            f"Your user ({user_id}):\n{user_narrative}"
                        )
                        try:
                            await self.send_text(user_id, text)
                        except Exception:
                            log.debug("Failed to push context to %s", user_id)
        except asyncio.CancelledError:
            return
        except Exception:
            log.warning("Context push loop error", exc_info=True)

    def get_session(self, user_id: str) -> LiveSessionState | None:
        return self._sessions.get(user_id)

    def all_sessions(self) -> list[LiveSessionState]:
        return list(self._sessions.values())

    async def shutdown(self):
        """Disconnect all sessions."""
        if self._context_push_task and not self._context_push_task.done():
            self._context_push_task.cancel()
            try:
                await self._context_push_task
            except asyncio.CancelledError:
                pass
        for user_id in list(self._sessions):
            await self.disconnect(user_id)


# Singleton
gemini_live = GeminiLiveManager()
