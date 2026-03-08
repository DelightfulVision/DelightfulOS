"""AI Social Mediator — LLM-based social interaction facilitation."""
import json
import re

from delightfulos.ai.config import settings
from delightfulos.ai.models import CollarState, MediatorResponse
from delightfulos.ai.prime import chat

SYSTEM_PROMPT = """You are a Social Radar AI mediator for a co-located augmented reality experience. Two users are wearing AR glasses and sensor collars in the same physical space.

Your job: interpret collar sensor events and decide what action to take to facilitate their social interaction. You must be subtle, respectful, and never obnoxious.

You receive a JSON object with:
- user_id: who generated these events
- events: list of detected signals (about_to_speak, speaking, stress_high, engagement_drop, orientation_shift, touch, breathing_change)
- shared_context: current AR scene state

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
- If stress_high: suppress notifications, simplify
- If about_to_speak: optionally highlight speaker for the other user
- If engagement_drop: gently fade AR elements
- Keep messages under 10 words
- Be a facilitator, not a controller"""


def _extract_json(raw: str) -> dict:
    """Extract JSON from model output, handling markdown wrapping."""
    cleaned = raw.strip()
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
