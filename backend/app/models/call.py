from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field
from backend.app.models.enums import CallState, ProviderName, ProviderSubmissionStatus


class Call(BaseModel):
    id: str
    borrower_id: str
    borrower_name: str
    borrower_phone: str
    agent_id: Optional[str] = None
    provider: ProviderName = ProviderName.PROVIDER_A
    state: CallState = CallState.QUEUED
    provider_submission_status: ProviderSubmissionStatus = ProviderSubmissionStatus.NOT_SUBMITTED
    submission_process_id: Optional[int] = None
    error_reason: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    # Time spent preparing the provider request is observed as initiated_at - created_at.
    initiated_at: Optional[datetime] = None
    ringing_at: Optional[datetime] = None
    answered_at: Optional[datetime] = None
    connected_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    duration_seconds: float = 0.0

    class Config:
        from_attributes = True
