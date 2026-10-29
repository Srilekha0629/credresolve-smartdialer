import math
from dataclasses import dataclass
from typing import Optional
from backend.app.storage.memory_store import MemoryStore
from backend.app.models.enums import AgentState, CallState
from backend.app.providers.provider_manager import ProviderManager


@dataclass
class PacingSuggestion:
    suggested_calls: int
    raw_calls: int
    bounded_calls: int
    answer_rate_used: float
    setup_time_used_seconds: float
    average_talk_time_used_seconds: float
    provider_health_factor: float
    primary_provider_healthy: bool
    fallback_provider_healthy: bool
    campaign_retry_rate: float
    fallback_to_progressive: bool
    reason: str


class PredictivePacingEngine:
    """
    Predictive Pacing Engine.

    Calculates optimal call batch size based on:
    - Current agent availability
    - Active calls and agents expected to free up soon
    - Historical / observed answer rate
    - Average talk time

    SEPARATION OF CONCERNS:
    - This engine ONLY computes a suggested number of calls.
    - It NEVER reserves agents, NEVER creates calls, and NEVER contacts telecom providers.
    - Its output must always be validated by the Safety Controller before execution.
    """

    DEFAULT_FALLBACK_MIN_ANSWER_RATE = 0.15  # 15%
    DEFAULT_MAX_PACING_RATIO = 2.0  # At most 2x available agents
    DEFAULT_SETUP_TIME_SECONDS = 0.1
    DEFAULT_AVERAGE_TALK_TIME_SECONDS = 60.0

    def __init__(
        self,
        store: Optional[MemoryStore] = None,
        provider_manager: Optional[ProviderManager] = None,
    ):
        self.store = store or MemoryStore.get_instance()
        self.provider_manager = provider_manager or ProviderManager.get_instance()

    def calculate_historical_answer_rate(self) -> float:
        """Computes observed answer rate from historical calls."""
        calls = self.store.get_calls()
        if not calls:
            return 0.50  # Default baseline for cold start

        total_placed = [
            c
            for c in calls
            if c.state in (CallState.CONNECTED, CallState.COMPLETED, CallState.FAILED)
        ]
        if not total_placed:
            return 0.50

        answered = [
            c
            for c in total_placed
            if c.state in (CallState.CONNECTED, CallState.COMPLETED)
            or (c.answered_at is not None)
        ]
        return max(0.05, len(answered) / len(total_placed))

    def calculate_average_talk_time(self) -> float:
        """Returns average talk time in seconds for completed calls."""
        calls = self.store.get_calls()
        completed = [c for c in calls if c.state == CallState.COMPLETED and c.duration_seconds > 0]
        if not completed:
            return self.DEFAULT_AVERAGE_TALK_TIME_SECONDS
        return sum(c.duration_seconds for c in completed) / len(completed)

    def calculate_average_setup_time(self) -> float:
        """Returns mean reservation-to-provider-acknowledgement time in seconds."""
        durations = [
            max(0.0, (call.initiated_at - call.created_at).total_seconds())
            for call in self.store.get_calls()
            if call.initiated_at is not None
        ]
        if not durations:
            return self.DEFAULT_SETUP_TIME_SECONDS
        return sum(durations) / len(durations)

    def suggest_call_volume(
        self,
        override_answer_rate: Optional[float] = None,
        max_pacing_ratio: float = DEFAULT_MAX_PACING_RATIO,
        allow_fallback: bool = True,
    ) -> PacingSuggestion:
        """
        Estimates the recommended number of outbound calls to place.
        """
        agents = self.store.get_agents()
        available_count = sum(
            1 for a in agents if a.state == AgentState.AVAILABLE and a.current_call_id is None
        )
        connected_count = sum(1 for a in agents if a.state == AgentState.CONNECTED)
        wrap_up_count = sum(1 for a in agents if a.state == AgentState.WRAP_UP)

        active_calls = len(self.store.get_active_calls())

        answer_rate = (
            override_answer_rate
            if override_answer_rate is not None
            else self.calculate_historical_answer_rate()
        )
        setup_time = self.calculate_average_setup_time()
        average_talk_time = self.calculate_average_talk_time()
        provider_statuses = {
            provider["name"]: provider
            for provider in self.provider_manager.get_provider_statuses()
        }
        primary_name = self.provider_manager.primary_provider_name.value
        primary_provider_healthy = provider_statuses[primary_name]["is_healthy"]
        fallback_provider_healthy = (
            provider_statuses["PROVIDER_A"]["is_healthy"]
            if primary_name == "PROVIDER_B"
            else False
        )
        if primary_provider_healthy:
            provider_health_factor = 1.0
        elif fallback_provider_healthy:
            provider_health_factor = 0.5
        else:
            provider_health_factor = 0.0

        queued_borrowers = self.store.get_queued_borrowers()
        campaign_retry_rate = (
            sum(1 for borrower in queued_borrowers if borrower.calls_attempted > 0)
            / len(queued_borrowers)
            if queued_borrowers
            else 0.0
        )
        campaign_behavior_factor = 1.0 - (0.5 * campaign_retry_rate)

        if provider_health_factor == 0:
            return PacingSuggestion(
                suggested_calls=0,
                raw_calls=0,
                bounded_calls=0,
                answer_rate_used=answer_rate,
                setup_time_used_seconds=setup_time,
                average_talk_time_used_seconds=average_talk_time,
                provider_health_factor=provider_health_factor,
                primary_provider_healthy=primary_provider_healthy,
                fallback_provider_healthy=fallback_provider_healthy,
                campaign_retry_rate=campaign_retry_rate,
                fallback_to_progressive=False,
                reason="No healthy provider route is available; pacing proposed no calls.",
            )

        # 1. Fallback to progressive check:
        # If no agents are available, or answer rate is below minimum reliability threshold
        if allow_fallback and (
            answer_rate < self.DEFAULT_FALLBACK_MIN_ANSWER_RATE or available_count == 0
        ):
            return PacingSuggestion(
                suggested_calls=available_count,
                raw_calls=available_count,
                bounded_calls=available_count,
                answer_rate_used=answer_rate,
                setup_time_used_seconds=setup_time,
                average_talk_time_used_seconds=average_talk_time,
                provider_health_factor=provider_health_factor,
                primary_provider_healthy=primary_provider_healthy,
                fallback_provider_healthy=fallback_provider_healthy,
                campaign_retry_rate=campaign_retry_rate,
                fallback_to_progressive=True,
                reason=(
                    f"Fallen back to progressive mode: answer rate ({answer_rate:.2%}) "
                    f"is below safety threshold ({self.DEFAULT_FALLBACK_MIN_ANSWER_RATE:.2%}) "
                    f"or available agents is {available_count}."
                ),
            )

        # Estimate the portion of occupied agents likely to finish during the
        # time needed to set up another call batch.
        completion_probability = setup_time / max(
            setup_time + average_talk_time, 1e-9
        )
        expected_free_capacity = available_count + (
            (wrap_up_count + connected_count) * completion_probability
        )

        # In order to keep expected_free_capacity agents busy, we need:
        # raw_needed = expected_free_capacity / answer_rate
        raw_needed = math.ceil(expected_free_capacity / max(0.05, answer_rate))

        # Adjust for existing active ringing/initiated calls
        additional_needed = max(0, raw_needed - (active_calls - connected_count))

        # 3. Bounded pacing enforcement:
        # Limit to max_pacing_ratio * available_count
        upper_bound = math.ceil(max(1, available_count) * max_pacing_ratio)
        capped_needed = min(additional_needed, upper_bound)
        bounded_needed = math.ceil(
            capped_needed * provider_health_factor * campaign_behavior_factor
        )

        return PacingSuggestion(
            suggested_calls=bounded_needed,
            raw_calls=additional_needed,
            bounded_calls=bounded_needed,
            answer_rate_used=answer_rate,
            setup_time_used_seconds=setup_time,
            average_talk_time_used_seconds=average_talk_time,
            provider_health_factor=provider_health_factor,
            primary_provider_healthy=primary_provider_healthy,
            fallback_provider_healthy=fallback_provider_healthy,
            campaign_retry_rate=campaign_retry_rate,
            fallback_to_progressive=False,
            reason=(
                f"Predictive pacing calculated {bounded_needed} calls "
                f"(raw: {additional_needed}, bounded by {max_pacing_ratio}x cap of {upper_bound}) "
                f"based on {available_count} available agents, {answer_rate:.1%} answer rate, "
                f"provider health factor {provider_health_factor:.2f}, and campaign retry rate "
                f"{campaign_retry_rate:.1%}."
            ),
        )
