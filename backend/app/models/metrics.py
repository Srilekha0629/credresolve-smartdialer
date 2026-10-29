from typing import Dict
from pydantic import BaseModel
from backend.app.models.enums import AgentState


class SystemMetrics(BaseModel):
    total_agents: int
    agents_by_state: Dict[AgentState, int]
    total_borrowers: int
    queued_borrowers: int
    total_calls: int
    active_calls: int
    completed_calls: int
    failed_calls: int
    uncertain_provider_submissions: int
    answer_rate_pct: float
    agent_utilization_pct: float
    average_talk_time_seconds: float
    average_call_setup_seconds: float
    pacing_suggested_multiplier: float
    primary_provider_healthy: bool
