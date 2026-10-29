from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field
from backend.app.models.enums import DialerMode


class ProgressiveDialRequest(BaseModel):
    max_calls: Optional[int] = Field(None, description="Optional cap on number of calls to initiate")


class PredictiveDialRequest(BaseModel):
    target_answer_rate: Optional[float] = Field(None, ge=0.01, le=1.0, description="Override estimated answer rate")
    max_pacing_ratio: Optional[float] = Field(2.0, ge=1.0, le=5.0, description="Max calls to place per available agent")
    allow_fallback: bool = Field(True, description="Fallback to progressive mode if answer rate data is unreliable")


class DialCycleResult(BaseModel):
    mode: DialerMode
    available_agents_before: int
    proposed_calls: int
    safe_approved_calls: int
    calls_initiated: int
    call_ids: List[str]
    notes: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)
