"""HDL co-design API — AI-assisted full-stack wearable hardware specification.

Devices and systems are loaded from YAML data files in the library.
AI-generated specs can be persisted as new YAML files.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from delightfulos.hdl.grammar import SITE_PROPERTIES
from delightfulos.hdl.loader import library
from delightfulos.hdl.codesign import (
    CODESIGN_SYSTEM_PROMPT, GAP_ANALYSIS_SYSTEM_PROMPT,
    spec_from_dict, gap_analysis_prompt, body_site_context,
    save_generated_spec, slugify,
)

from delightfulos.ai.config import settings
from delightfulos.ai.prime import chat
from delightfulos.ai.mediator import _extract_json

router = APIRouter(prefix="/hdl", tags=["hdl"])

# Load library on import
library.ensure_loaded()


class DesignRequest(BaseModel):
    description: str
    body_site: str | None = None
    save: bool = False


class AnalyzeRequest(BaseModel):
    system_name: str = "social_radar"


@router.get("/devices")
async def list_devices():
    library.ensure_loaded()
    return {name: spec.to_dict() for name, spec in library.devices.items()}


@router.get("/devices/{name}")
async def get_device(name: str):
    library.ensure_loaded()
    spec = library.devices.get(name)
    if not spec:
        raise HTTPException(status_code=404,
                            detail=f"Device '{name}' not found. Available: {list(library.devices.keys())}")
    return {"spec": spec.to_dict(), "description": spec.describe()}


@router.get("/systems")
async def list_systems():
    library.ensure_loaded()
    return {name: s.to_dict() for name, s in library.systems.items()}


@router.get("/systems/{name}/coverage")
async def system_coverage(name: str):
    library.ensure_loaded()
    system = library.systems.get(name)
    if not system:
        raise HTTPException(status_code=404,
                            detail=f"System '{name}' not found. Available: {list(library.systems.keys())}")
    return {"coverage": system.coverage_report()}


@router.get("/body-sites")
async def list_body_sites():
    """Reference of all body sites with anatomical and social properties."""
    return {
        site.value: {
            "proximity_to": props.proximity_to,
            "motion_class": props.motion_class,
            "social_visibility": props.social_visibility,
            "skin_contact": props.skin_contact,
            "nerve_density": props.nerve_density,
            "anatomical_notes": props.anatomical_notes,
        }
        for site, props in SITE_PROPERTIES.items()
    }


@router.post("/design")
async def design_wearable(req: DesignRequest):
    """AI co-design: generate a full-stack wearable spec from natural language.

    Set save=true to persist the generated spec as a YAML file in the library.
    """
    user_msg = req.description
    if req.body_site:
        user_msg += f"\n\nConstrain to body site: {req.body_site}"

    raw = await chat(
        messages=[
            {"role": "system", "content": CODESIGN_SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        model=settings.model_codesign,
        max_tokens=4096,
        temperature=1.0,  # K2 Think V2 recommended: temperature=1.0
    )

    try:
        data = _extract_json(raw)
        spec = spec_from_dict(data)
        result = {
            "spec": spec.to_dict(),
            "description": spec.describe(),
            "reasoning": data.get("reasoning", ""),
            "gaps": data.get("gaps", []),
            "psychological_notes": data.get("psychological_notes", ""),
        }

        if req.save:
            key = save_generated_spec(spec)
            result["saved_as"] = key

        return result
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Failed to parse AI response: {e}")


@router.post("/analyze")
async def analyze_system(req: AnalyzeRequest):
    """AI analysis: identify gaps across all eight dimensions of a wearable system."""
    library.ensure_loaded()
    system = library.systems.get(req.system_name)
    if not system:
        raise HTTPException(status_code=404, detail=f"System '{req.system_name}' not found")

    prompt = gap_analysis_prompt(system)
    raw = await chat(
        messages=[
            {"role": "system", "content": GAP_ANALYSIS_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        model=settings.model_codesign,
        max_tokens=4096,
        temperature=1.0,  # K2 Think V2 recommended: temperature=1.0
    )

    try:
        data = _extract_json(raw)
        return {"system": req.system_name, "analysis": data}
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Failed to parse AI response: {e}")
