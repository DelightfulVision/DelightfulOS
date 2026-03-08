"""AI Social Mediator — LLM-based social interaction facilitation."""
import json
import re

from delightfulos.ai.config import settings
from delightfulos.ai.models import CollarState, MediatorResponse
from delightfulos.ai.prime import chat

SYSTEM_PROMPT = """You are a Social Radar AI mediator for a co-located augmented reality experience. Users are wearing AR glasses and sensor collars in the same physical space.

Your job: interpret the structured context log and decide what action to take to facilitate social interaction. You must be subtle, respectful, and never obnoxious.

You receive a JSON context object with:
- users: dict of user_id -> current body state (mode, speech_active, speech_intent, stress_level, engagement, arousal, attention_direction, overloaded, hidden_overlays)
- num_users: how many active users
- recent_events: structured semantic events (speech_start, speech_end, intent_rising, stress_rising, stress_resolved, collar_tap, mode_change, overlay_toggle, etc.)
- narrative: human-readable timeline of recent events

You must respond with ONLY a JSON object (no markdown, no explanation):
{
  "action": "nudge|highlight|suppress|haptic|narrate|fade|none",
  "target_user": "user_id or null",
  "message": "short text or null",
  "haptic": {"direction": "left|right|front|back", "pattern": "tap|pulse|buzz", "intensity": 0.0-1.0} or null,
  "ar_overlay": {"type": "halo|arrow|fade|glow", "color": "#hex", "target": "user_id|object_id"} or null
}

Rules:
- Default to "none" if nothing interesting is happening
- Never interrupt active speech
- Use haptics sparingly — only for genuine attention guidance
- If stress is rising or sustained: suppress notifications, simplify overlays
- If someone is about to speak (intent_rising): optionally highlight them for others
- If engagement drops: gently fade AR elements
- If someone is overloaded: suppress everything, send calming haptic
- Use the narrative to understand temporal context (what just happened)
- Keep messages under 10 words
- Be a facilitator, not a controller"""


def _extract_json(raw: str) -> dict:
    """Extract JSON from model output, handling markdown wrapping and thinking traces."""
    cleaned = raw.strip()
    # Strip thinking traces (K2 Think V2 outputs <think>...</think> before answer)
    if "</think>" in cleaned:
        cleaned = cleaned.split("</think>", 1)[-1].strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

    # Try direct parse first
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Find matching braces with a counter (handles nested objects)
    start = cleaned.find("{")
    if start == -1:
        raise ValueError("No JSON object found in response")
    depth = 0
    for i in range(start, len(cleaned)):
        if cleaned[i] == "{":
            depth += 1
        elif cleaned[i] == "}":
            depth -= 1
            if depth == 0:
                return json.loads(cleaned[start:i + 1])

    raise ValueError("Unbalanced braces in response")


async def mediate(state: CollarState) -> MediatorResponse:
    user_msg = json.dumps(state.model_dump(), default=str)
    raw = await chat(
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        model=settings.model_mediator,
        max_tokens=256,
        temperature=0.3,
    )

    try:
        data = _extract_json(raw)
        return MediatorResponse(**data)
    except Exception:
        return MediatorResponse(action="none")
