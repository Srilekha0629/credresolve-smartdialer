from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field
from backend.app.models.enums import AgentState


class AgentBase(BaseModel):
    name: str = Field(..., description="Agent name")
    state: AgentState = Field(default=AgentState.AVAILABLE, description="Current agent state")


class AgentCreate(AgentBase):
    id: Optional[str] = None


class AgentStateUpdate(BaseModel):
    state: AgentState = Field(..., description="Target state to transition to")


class Agent(BaseModel):
    id: str
    name: str
    state: AgentState = AgentState.AVAILABLE
    current_call_id: Optional[str] = None
    total_calls_handled: int = 0
    total_talk_time_seconds: float = 0.0
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        from_attributes = True
