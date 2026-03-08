"""Pydantic models for AI-layer request/response types."""
from pydantic import BaseModel


class CollarEvent(BaseModel):
    type: str
    confidence: float = 1.0
    value: dict | None = None


class CollarState(BaseModel):
    user_id: str
    timestamp: float
    events: list[CollarEvent]
    imu: dict | None = None
    shared_context: dict | None = None


class MediatorResponse(BaseModel):
    action: str
    target_user: str | None = None
    message: str | None = None
    haptic: dict | None = None
    ar_overlay: dict | None = None
