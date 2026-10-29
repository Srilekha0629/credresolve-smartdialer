from typing import Optional, Dict
from backend.app.models.enums import AgentState, CallState, ProviderSubmissionStatus
from backend.app.models.metrics import SystemMetrics
from backend.app.storage.memory_store import MemoryStore
from backend.app.providers.provider_manager import ProviderManager
from backend.app.services.predictive_pacing import PredictivePacingEngine


class MetricsService:
    """Computes real-time system metrics from live in-memory state."""

    def __init__(
        self,
        store: Optional[MemoryStore] = None,
        provider_manager: Optional[ProviderManager] = None,
    ):
        self.store = store or MemoryStore.get_instance()
        self.provider_manager = provider_manager or ProviderManager.get_instance()

    def get_system_metrics(self) -> SystemMetrics:
        agents = self.store.get_agents()
        borrowers = self.store.get_borrowers()
        calls = self.store.get_calls()

        # Agents by state
        agents_by_state: Dict[AgentState, int] = {state: 0 for state in AgentState}
        for agt in agents:
            agents_by_state[agt.state] += 1

        # Calls breakdown
        active_calls = 0
        completed_calls = 0
        failed_calls = 0
        answered_calls = 0
        placed_calls = 0

        for c in calls:
            if c.state in (
                CallState.RESERVED,
                CallState.INITIATED,
                CallState.RINGING,
                CallState.ANSWERED,
                CallState.CONNECTED,
            ):
                active_calls += 1
            if c.state == CallState.COMPLETED:
                completed_calls += 1
            if c.state == CallState.FAILED:
                failed_calls += 1
            if c.state in (CallState.CONNECTED, CallState.COMPLETED) or c.answered_at is not None:
                answered_calls += 1
            if c.state not in (CallState.QUEUED, CallState.CANCELLED):
                placed_calls += 1

        answer_rate_pct = (
            round((answered_calls / placed_calls) * 100, 1) if placed_calls > 0 else 0.0
        )

        active_working_agents = sum(
            1 for a in agents if a.state not in (AgentState.OFFLINE, AgentState.PAUSED)
        )
        utilized_agents = sum(
            1
            for a in agents
            if a.state
            in (
                AgentState.RESERVED,
                AgentState.CONNECTED,
                AgentState.WRAP_UP,
                AgentState.DIALING,
            )
        )
        agent_utilization_pct = (
            round((utilized_agents / active_working_agents) * 100, 1)
            if active_working_agents > 0
            else 0.0
        )

        completed_call_records = [
            c for c in calls if c.state == CallState.COMPLETED and c.duration_seconds > 0
        ]
        avg_talk_time = (
            round(
                sum(c.duration_seconds for c in completed_call_records)
                / len(completed_call_records),
                1,
            )
            if completed_call_records
            else 0.0
        )
        setup_durations = [
            max(0.0, (c.initiated_at - c.created_at).total_seconds())
            for c in calls
            if c.initiated_at is not None
        ]
        avg_setup_time = (
            round(sum(setup_durations) / len(setup_durations), 3)
            if setup_durations
            else PredictivePacingEngine.DEFAULT_SETUP_TIME_SECONDS
        )
        available_agents = sum(
            1
            for agent in agents
            if agent.state == AgentState.AVAILABLE and agent.current_call_id is None
        )
        pacing_suggestion = PredictivePacingEngine(self.store).suggest_call_volume()
        pacing_multiplier = (
            round(pacing_suggestion.suggested_calls / available_agents, 2)
            if available_agents
            else 0.0
        )

        primary_healthy = self.provider_manager.get_primary_provider().is_healthy()

        return SystemMetrics(
            total_agents=len(agents),
            agents_by_state=agents_by_state,
            total_borrowers=len(borrowers),
            queued_borrowers=len(self.store.get_queued_borrowers()),
            total_calls=len(calls),
            active_calls=active_calls,
            completed_calls=completed_calls,
            failed_calls=failed_calls,
            uncertain_provider_submissions=sum(
                1
                for call in calls
                if call.provider_submission_status == ProviderSubmissionStatus.UNKNOWN
                and call.state == CallState.RESERVED
            ),
            answer_rate_pct=answer_rate_pct,
            agent_utilization_pct=agent_utilization_pct,
            average_talk_time_seconds=avg_talk_time,
            average_call_setup_seconds=avg_setup_time,
            pacing_suggested_multiplier=pacing_multiplier,
            primary_provider_healthy=primary_healthy,
        )
