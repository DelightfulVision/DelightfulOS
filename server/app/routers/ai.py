"""AI routes — inference, mediation, chat, Gemini Live."""
import asyncio
import base64
import json
import logging
from typing import Literal

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException
from pydantic import BaseModel, Field

from delightfulos.ai.config import settings
from delightfulos.ai.models import CollarState, MediatorResponse
from delightfulos.ai import prime, mediator
from delightfulos.ai.gemini_live import gemini_live

log = logging.getLogger("delightfulos.api.ai")

router = APIRouter(prefix="/ai", tags=["ai"])


@router.get("/models")
async def get_models():
    return await prime.list_models()


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    model: str = settings.model_quality
    max_tokens: int = Field(default=512, le=4096)
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)


@router.post("/chat")
async def chat_endpoint(req: ChatRequest):
    result = await prime.chat(
        messages=[m.model_dump() for m in req.messages],
        model=req.model,
        max_tokens=req.max_tokens,
        temperature=req.temperature,
    )
    return {"response": result}


@router.post("/mediate", response_model=MediatorResponse)
async def mediate_endpoint(state: CollarState):
    return await mediator.mediate(state)


# === Gemini Live ===


@router.get("/live/status")
async def live_status():
    """Check Gemini Live availability and active sessions."""
    return {
        "enabled": gemini_live.enabled,
        "sessions": [
            {
                "user_id": s.user_id,
                "connected": s.connected,
                "created_at": s.created_at,
                "input_transcripts": len(s.input_transcripts),
                "output_transcripts": len(s.output_transcripts),
                "audio_out_bytes": s.audio_out_bytes,
            }
            for s in gemini_live.all_sessions()
        ],
    }


@router.post("/live/connect/{user_id}")
async def live_connect(user_id: str):
    """Open a Gemini Live session for a user."""
    if not gemini_live.enabled:
        raise HTTPException(status_code=503, detail="GEMINI_API_KEY not configured")
    state = await gemini_live.connect(user_id)
    return {"status": "connected", "user_id": user_id, "created_at": state.created_at}


@router.post("/live/disconnect/{user_id}")
async def live_disconnect(user_id: str):
    """Close a user's Gemini Live session."""
    await gemini_live.disconnect(user_id)
    return {"status": "disconnected", "user_id": user_id}


@router.post("/live/artifact/{user_id}")
async def live_artifact(user_id: str, artifact_type: str = "summary"):
    """Generate an artifact (summary, notes, action_items) from accumulated transcriptions."""
    if artifact_type not in ("summary", "notes", "action_items"):
        raise HTTPException(status_code=400, detail="artifact_type must be: summary, notes, action_items")
    result = await gemini_live.generate_artifact(user_id, artifact_type)
    if result is None:
        raise HTTPException(status_code=404, detail="No session or transcription data for user")
    return {"user_id": user_id, "type": artifact_type, "text": result}


@router.websocket("/live/ws/{user_id}")
async def live_audio_ws(ws: WebSocket, user_id: str):
    """Bidirectional audio WebSocket for Gemini Live.

    Client sends: base64-encoded 16kHz 16-bit PCM audio chunks as text frames,
                  or JSON {"type": "text", "text": "..."} for text input.
    Server sends: base64-encoded 24kHz 16-bit PCM audio chunks as text frames,
                  or JSON {"type": "transcription", "text": "..."} for text output.
    """
    await ws.accept()

    if not gemini_live.enabled:
        await ws.send_text(json.dumps({"error": "GEMINI_API_KEY not configured"}))
        await ws.close()
        return

    try:
        state = await gemini_live.connect(user_id)
    except Exception as e:
        await ws.send_text(json.dumps({"error": str(e)}))
        await ws.close()
        return

    await ws.send_text(json.dumps({"type": "connected", "user_id": user_id}))

    async def forward_output():
        """Forward Gemini audio output + transcriptions to the WebSocket client."""
        queue = gemini_live.get_audio_output(user_id)
        while state.connected:
            try:
                audio_chunk = await asyncio.wait_for(queue.get(), timeout=1.0)
                await ws.send_text(base64.b64encode(audio_chunk).decode())
            except asyncio.TimeoutError:
                # Check for new transcription chunks
                pass
            except Exception:
                break

    output_task = asyncio.create_task(forward_output())

    try:
        while True:
            raw = await ws.receive_text()

            # Try JSON (text message or control)
            try:
                msg = json.loads(raw)
                if msg.get("type") == "text":
                    await gemini_live.send_text(user_id, msg["text"])
                elif msg.get("type") == "disconnect":
                    break
                continue
            except (json.JSONDecodeError, KeyError):
                pass

            # Otherwise treat as base64 PCM audio
            try:
                pcm_bytes = base64.b64decode(raw)
                await gemini_live.send_audio(user_id, pcm_bytes)
            except Exception:
                log.warning("Invalid audio data from %s", user_id)

    except WebSocketDisconnect:
        pass
    except Exception:
        log.exception("Gemini Live WebSocket error for %s", user_id)
    finally:
        output_task.cancel()
        try:
            await output_task
        except asyncio.CancelledError:
            pass
        await gemini_live.disconnect(user_id)
