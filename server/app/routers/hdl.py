"""HDL co-design API — AI-assisted wearable hardware specification."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from delightfulos.hdl.grammar import WearableSpec, WearableSystem
from delightfulos.hdl.codesign import CODESIGN_SYSTEM_PROMPT, spec_from_dict, gap_analysis_prompt
from delightfulos.hdl.library.devices import COLLAR_V1, SPECTACLES, SOCIAL_RADAR, FULL_BODY_STACK

from delightfulos.ai.config import settings
from delightfulos.ai.prime import chat
from delightfulos.ai.mediator import _extract_json

router = APIRouter(prefix="/hdl", tags=["hdl"])


class DesignRequest(BaseModel):
    description: str
    body_site: str | None = None


class AnalyzeRequest(BaseModel):
    system_name: str = "social_radar"


SYSTEMS = {
    "social_radar": SOCIAL_RADAR,
    "full_body": FULL_BODY_STACK,
}

DEVICES = {
    "collar_v1": COLLAR_V1,
    "spectacles": SPECTACLES,
}


@router.get("/devices")
async def list_devices():
    return {name: spec.to_dict() for name, spec in DEVICES.items()}


@router.get("/systems")
async def list_systems():
    return {name: s.to_dict() for name, s in SYSTEMS.items()}


@router.get("/systems/{name}/coverage")
async def system_coverage(name: str):
    system = SYSTEMS.get(name)
    if not system:
        raise HTTPException(status_code=404, detail=f"System '{name}' not found. Available: {list(SYSTEMS.keys())}")
    return {"coverage": system.coverage_report()}


@router.post("/design")
async def design_wearable(req: DesignRequest):
    user_msg = req.description
    if req.body_site:
        user_msg += f"\n\nConstrain to body site: {req.body_site}"

    raw = await chat(
        messages=[
            {"role": "system", "content": CODESIGN_SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        model=settings.model_quality,
        max_tokens=1024,
        temperature=0.5,
    )

    try:
        data = _extract_json(raw)
        spec = spec_from_dict(data)
        return {
            "spec": spec.to_dict(),
            "description": spec.describe(),
            "reasoning": data.get("reasoning", ""),
            "gaps": data.get("gaps", []),
        }
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Failed to parse AI response: {e}")


@router.post("/analyze")
async def analyze_system(req: AnalyzeRequest):
    system = SYSTEMS.get(req.system_name)
    if not system:
        raise HTTPException(status_code=404, detail=f"System '{req.system_name}' not found")

    prompt = gap_analysis_prompt(system)
    raw = await chat(
        messages=[
            {"role": "system", "content": "You are a wearable systems architect. Respond with only JSON."},
            {"role": "user", "content": prompt},
        ],
        model=settings.model_quality,
        max_tokens=1024,
        temperature=0.5,
    )

    try:
        data = _extract_json(raw)
        return {"system": req.system_name, "analysis": data}
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Failed to parse AI response: {e}")
