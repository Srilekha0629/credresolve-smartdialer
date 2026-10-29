from datetime import datetime
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field
from backend.app.models.enums import CallState, ProviderEventType, ProviderName


class ProviderWebhookRequest(BaseModel):
    event_id: str = Field(..., description="Unique event identifier for idempotency")
    call_id: str = Field(..., description="ID of the call this event pertains to")
    provider: ProviderName = Field(..., description="Originating telecom provider")
    event_type: ProviderEventType = Field(..., description="Telecom event type")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Event timestamp")
    reason: Optional[str] = Field(None, description="Reason if call failed or was disconnected")
    payload: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Arbitrary provider metadata")


class ProviderWebhookResponse(BaseModel):
    success: bool
    status: str  # processed, ignored_duplicate, rejected_illegal_transition, not_found, error
    call_id: str
    current_call_state: Optional[CallState] = None
    agent_id: Optional[str] = None
    message: str
