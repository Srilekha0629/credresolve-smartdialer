import uuid
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from backend.app.models.call import Call
from backend.app.models.enums import (
    AgentState,
    CallState,
    ProviderEventType,
    ProviderName,
)
from backend.app.models.provider_event import ProviderWebhookRequest
from backend.app.providers.provider_manager import ProviderManager
from backend.app.services.dialer_orchestrator import DialerOrchestrator
from backend.app.services.event_processor import EventProcessor
from backend.app.services.metrics_service import MetricsService
from backend.app.storage.memory_store import MemoryStore


SCENARIOS: Dict[str, Dict[str, object]] = {
    "A": {"answer_rate": 0.20, "average_talk_time_seconds": 120},
    "B": {"answer_rate": 0.50, "average_talk_time_seconds": 90},
    "C": {"answer_rate": 0.70, "average_talk_time_seconds": 180},
    "D": {
        "phases": [
            {
                "answer_rate": 0.50,
                "average_talk_time_seconds": 90,
                "provider_b_failure": True,
            },
            {
                "answer_rate": 0.10,
                "average_talk_time_seconds": 180,
                "provider_b_failure": False,
            },
        ]
    },
}


class ScenarioRunner:
    """Runs explicitly simulated pacing, provider, and webhook scenarios."""

    def __init__(
        self,
        store: MemoryStore,
        provider_manager: ProviderManager,
    ):
        self.store = store
        self.provider_manager = provider_manager
        self.orchestrator = DialerOrchestrator(
            store=store, provider_manager=provider_manager
        )
        self.event_processor = EventProcessor(store)
        self.metrics_service = MetricsService(store, provider_manager)

    async def run(self, scenario_id: str) -> Dict[str, object]:
        scenario_id = scenario_id.upper()
        if scenario_id not in SCENARIOS:
            raise ValueError(f"Unknown scenario '{scenario_id}'. Choose A, B, C, or D.")
        async with self.store.atomic():
            if self.store.get_active_calls():
                raise RuntimeError(
                    "Cannot start a scenario while calls are active. Complete or reset them first."
                )
            self.store.seed_defaults()
        self._reset_providers()
        if scenario_id == "D":
            phases = []
            for phase_index, profile in enumerate(SCENARIOS["D"]["phases"]):
                phases.append(await self._run_changing_phase(phase_index, profile))
            summary = {
                "simulated": True,
                "scenario": "D",
                "description": "Changing answer rate, talk time, and Provider B availability.",
                "phases": phases,
                "metrics": self.metrics_service.get_system_metrics().model_dump(mode="json"),
            }
            return summary

        profile = SCENARIOS[scenario_id]
        self._seed_history(
            float(profile["answer_rate"]),
            int(profile["average_talk_time_seconds"]),
        )
        self.provider_manager.set_primary_provider(ProviderName.PROVIDER_A)
        cycle = await self.orchestrator.run_predictive_cycle(
            max_pacing_ratio=2.0,
            allow_fallback=True,
        )
        event_results = await self._process_cycle_events(
            cycle.call_ids,
            float(profile["answer_rate"]),
            int(profile["average_talk_time_seconds"]),
            use_provider_b_event_generator=False,
        )
        return {
            "simulated": True,
            "scenario": scenario_id,
            "description": (
                f"Historical answer rate {float(profile['answer_rate']):.0%}, "
                f"average talk time {int(profile['average_talk_time_seconds'])} seconds."
            ),
            "inputs": profile,
            "cycle": cycle.model_dump(mode="json"),
            "event_results": event_results,
            "provider_statuses": self.provider_manager.get_provider_statuses(),
            "metrics": self.metrics_service.get_system_metrics().model_dump(mode="json"),
        }

    def _reset_providers(self) -> None:
        for provider in (self.provider_manager.provider_a, self.provider_manager.provider_b):
            provider.consecutive_failures = 0
            provider.total_calls_initiated = 0
            provider.total_failures = 0
            provider.set_healthy(True)
        self.provider_manager.provider_b.configure_simulation(
            simulate_timeout=False,
            simulate_failure=False,
            simulate_duplicate=False,
            simulate_out_of_order=False,
        )
        self.provider_manager.set_primary_provider(ProviderName.PROVIDER_A)

    def _seed_history(self, answer_rate: float, talk_time_seconds: int) -> None:
        sample_count = 100
        answered_count = round(sample_count * answer_rate)
        now = datetime.utcnow()
        with self.store.transaction():
            for index in range(sample_count):
                answered = index < answered_count
                created_at = now - timedelta(hours=4, seconds=index)
                self.store.save_call(
                    Call(
                        id=f"scenario_history_{index:03d}",
                        borrower_id=f"scenario_borrower_{index:03d}",
                        borrower_name="Simulated borrower",
                        borrower_phone="+15550000000",
                        provider=ProviderName.PROVIDER_A,
                        state=(
                            CallState.COMPLETED if answered else CallState.FAILED
                        ),
                        created_at=created_at,
                        initiated_at=created_at + timedelta(seconds=0.15),
                        connected_at=(
                            created_at + timedelta(seconds=0.15)
                            if answered
                            else None
                        ),
                        ended_at=(
                            created_at + timedelta(seconds=0.15 + talk_time_seconds)
                        ),
                        duration_seconds=float(talk_time_seconds if answered else 0),
                    )
                )

    async def _run_changing_phase(
        self, phase_index: int, profile: Dict[str, object]
    ) -> Dict[str, object]:
        answer_rate = float(profile["answer_rate"])
        talk_time_seconds = int(profile["average_talk_time_seconds"])
        provider_b_failure = bool(profile["provider_b_failure"])
        self.provider_manager.set_primary_provider(ProviderName.PROVIDER_B)
        self.provider_manager.provider_b.configure_simulation(
            simulate_failure=provider_b_failure,
            simulate_timeout=False,
            simulate_duplicate=False,
            simulate_out_of_order=False,
        )
        if not provider_b_failure:
            self.provider_manager.provider_b.consecutive_failures = 0

        cycle = await self.orchestrator.run_predictive_cycle(
            target_answer_rate=answer_rate,
            max_pacing_ratio=2.0,
            allow_fallback=True,
        )
        event_results = await self._process_cycle_events(
            cycle.call_ids,
            answer_rate,
            talk_time_seconds,
            use_provider_b_event_generator=not provider_b_failure,
        )

        with self.store.transaction():
            for agent in self.store.get_agents():
                if agent.state == AgentState.WRAP_UP:
                    agent.state = AgentState.AVAILABLE
                    self.store.update_agent(agent)

        if phase_index == 0:
            self.provider_manager.provider_b.configure_simulation(simulate_failure=False)
            self.provider_manager.provider_b.consecutive_failures = 0
            next_rate = 0.10
            next_talk_time = 180
        else:
            next_rate = answer_rate
            next_talk_time = talk_time_seconds
        providers_used = sorted(
            {
                self.store.get_call(call_id).provider.value
                for call_id in cycle.call_ids
                if self.store.get_call(call_id) is not None
            }
        )
        return {
            "phase": phase_index + 1,
            "inputs": {
                "answer_rate": answer_rate,
                "average_talk_time_seconds": talk_time_seconds,
                "provider_b_failure": provider_b_failure,
            },
            "next_phase_conditions": {
                "answer_rate": next_rate,
                "average_talk_time_seconds": next_talk_time,
                "provider_b_failure": False,
            },
            "cycle": cycle.model_dump(mode="json"),
            "providers_used": providers_used,
            "event_results": event_results,
            "provider_statuses": self.provider_manager.get_provider_statuses(),
        }

    async def _process_cycle_events(
        self,
        call_ids: List[str],
        answer_rate: float,
        talk_time_seconds: int,
        use_provider_b_event_generator: bool,
    ) -> Dict[str, int]:
        answered_count = min(
            len(call_ids),
            max(1, round(len(call_ids) * answer_rate)) if call_ids else 0,
        )
        result_counts = {"processed": 0, "ignored_duplicate": 0, "rejected": 0}
        now = datetime.utcnow()

        for index, call_id in enumerate(call_ids):
            call = self.store.get_call(call_id)
            if call is None:
                continue
            answered = index < answered_count
            if (
                not answered
                and use_provider_b_event_generator
                and call.provider == ProviderName.PROVIDER_B
                and index == 1
            ):
                failed_event = self._event(
                    call_id,
                    call.provider,
                    ProviderEventType.FAILED,
                    now + timedelta(milliseconds=index),
                    "Simulated duplicate no-answer event.",
                )
                events = [failed_event, failed_event.model_copy()]
            elif not answered:
                events = [
                    self._event(
                        call_id,
                        call.provider,
                        ProviderEventType.FAILED,
                        now + timedelta(milliseconds=index),
                        "Simulated no-answer outcome.",
                    )
                ]
            elif (
                use_provider_b_event_generator
                and call.provider == ProviderName.PROVIDER_B
            ):
                if index == 0:
                    self.provider_manager.provider_b.configure_simulation(
                        simulate_duplicate=False, simulate_out_of_order=True
                    )
                else:
                    self.provider_manager.provider_b.configure_simulation(
                        simulate_duplicate=True, simulate_out_of_order=False
                    )
                events = self.provider_manager.provider_b.generate_simulated_events(call_id)
                self.provider_manager.provider_b.configure_simulation(
                    simulate_duplicate=False, simulate_out_of_order=False
                )
                events.append(
                    self._event(
                        call_id,
                        call.provider,
                        ProviderEventType.CONNECTED,
                        now + timedelta(seconds=1, milliseconds=index),
                    )
                )
                events.append(
                    self._event(
                        call_id,
                        call.provider,
                        ProviderEventType.COMPLETED,
                        now
                        + timedelta(
                            seconds=1 + talk_time_seconds,
                            milliseconds=index,
                        ),
                    )
                )
            else:
                base = now + timedelta(milliseconds=index)
                events = [
                    self._event(call_id, call.provider, ProviderEventType.RINGING, base),
                    self._event(
                        call_id,
                        call.provider,
                        ProviderEventType.ANSWERED,
                        base + timedelta(milliseconds=100),
                    ),
                    self._event(
                        call_id,
                        call.provider,
                        ProviderEventType.CONNECTED,
                        base + timedelta(seconds=1),
                    ),
                    self._event(
                        call_id,
                        call.provider,
                        ProviderEventType.COMPLETED,
                        base + timedelta(seconds=1 + talk_time_seconds),
                    ),
                ]
            for event in events:
                response = await self.event_processor.process_event(event)
                if response.status in result_counts:
                    result_counts[response.status] += 1
                else:
                    result_counts["rejected"] += 1

        return result_counts

    @staticmethod
    def _event(
        call_id: str,
        provider: ProviderName,
        event_type: ProviderEventType,
        timestamp: datetime,
        reason: Optional[str] = None,
    ) -> ProviderWebhookRequest:
        return ProviderWebhookRequest(
            event_id=f"evt_{uuid.uuid4().hex}",
            call_id=call_id,
            provider=provider,
            event_type=event_type,
            timestamp=timestamp,
            reason=reason,
        )
