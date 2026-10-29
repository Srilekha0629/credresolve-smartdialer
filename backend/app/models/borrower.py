from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class Borrower(BaseModel):
    id: str
    name: str
    phone: str
    debt_amount: float = 0.0
    status: str = "QUEUED"  # QUEUED, DIALING, COMPLETED, FAILED
    calls_attempted: int = 0
    last_call_id: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        from_attributes = True
