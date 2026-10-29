import asyncio
from typing import Tuple, Optional, Dict, Any, List
from datetime import datetime
import uuid
from backend.app.models.enums import ProviderName, ProviderEventType
from backend.app.models.provider_event import ProviderWebhookRequest
from backend.app.providers.base_provider import BaseTelecomProvider


class ProviderB(BaseTelecomProvider):
    """
    Provider B: Flaky Telecom Provider.
    Simulates telecom timeouts, unexpected failures, duplicate webhook events,
    and out-of-order event sequences for testing resilience and idempotency.
    """

    LATENCY_SECONDS = 0.2
    TIMEOUT_SECONDS = 0.5

    def __init__(self):
        super().__init__(ProviderName.PROVIDER_B)
        self.simulate_timeout: bool = False
        self.simulate_failure: bool = False
        self.simulate_duplicate_events: bool = False
        self.simulate_out_of_order: bool = False
        self._manual_unhealthy: bool = False

    def is_healthy(self) -> bool:
        if self._manual_unhealthy:
            return False
        return self.consecutive_failures < 3

    def set_healthy(self, healthy: bool):
        self._manual_unhealthy = not healthy

    def configure_simulation(
        self,
        simulate_timeout: Optional[bool] = None,
        simulate_failure: Optional[bool] = None,
        simulate_duplicate: Optional[bool] = None,
        simulate_out_of_order: Optional[bool] = None,
    ):
        if simulate_timeout is not None:
            self.simulate_timeout = simulate_timeout
        if simulate_failure is not None:
            self.simulate_failure = simulate_failure
        if simulate_duplicate is not None:
            self.simulate_duplicate_events = simulate_duplicate
        if simulate_out_of_order is not None:
            self.simulate_out_of_order = simulate_out_of_order

    async def initiate_call(
        self, call_id: str, borrower_phone: str
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        if not self.is_healthy():
            self.record_failure()
            return False, "Provider B outage: consecutive-failure health threshold reached.", {
                "acceptance_status": "REJECTED"
            }

        if self.simulate_timeout:
            await asyncio.sleep(self.TIMEOUT_SECONDS)
            self.record_failure()
            return False, "Provider B gateway timeout (504): carrier connection timed out.", {
                "acceptance_status": "UNKNOWN"
            }

        await asyncio.sleep(self.LATENCY_SECONDS)
        if not self.is_healthy():
            self.record_failure()
            return False, "Provider B became unavailable during call setup.", {
                "acceptance_status": "UNKNOWN"
            }

        if self.simulate_failure:
            self.record_failure()
            return False, "Provider B simulated failure (503): trunk capacity exhausted.", {
                "acceptance_status": "REJECTED"
            }

        self.record_success()
        return (
            True,
            "INITIATED",
            {
                "provider": self.name.value,
                "provider_call_id": f"prv_b_{call_id[-8:]}",
                "carrier": "Tier2_Secondary",
                "latency_ms": round(self.LATENCY_SECONDS * 1000),
                "simulated_flakiness": {
                    "duplicate": self.simulate_duplicate_events,
                    "out_of_order": self.simulate_out_of_order,
                },
            },
        )

    def generate_simulated_events(self, call_id: str) -> List[ProviderWebhookRequest]:
        """
        Generates simulated webhook events according to configured behavior:
        - Normal: RINGING -> ANSWERED -> CONNECTED
        - Out-of-order: ANSWERED before RINGING or ANSWERED after COMPLETED
        - Duplicates: Emits the exact same event twice with the same event_id
        """
        events = []
        now = datetime.utcnow()

        if self.simulate_out_of_order:
            # Emit ANSWERED before RINGING, or late events
            events.append(
                ProviderWebhookRequest(
                    event_id=f"evt_{uuid.uuid4().hex[:8]}",
                    call_id=call_id,
                    provider=self.name,
                    event_type=ProviderEventType.ANSWERED,
                    timestamp=now,
                )
            )
            events.append(
                ProviderWebhookRequest(
                    event_id=f"evt_{uuid.uuid4().hex[:8]}",
                    call_id=call_id,
                    provider=self.name,
                    event_type=ProviderEventType.RINGING,
                    timestamp=now,
                )
            )
        else:
            ring_evt_id = f"evt_{uuid.uuid4().hex[:8]}"
            events.append(
                ProviderWebhookRequest(
                    event_id=ring_evt_id,
                    call_id=call_id,
                    provider=self.name,
                    event_type=ProviderEventType.RINGING,
                    timestamp=now,
                )
            )
            if self.simulate_duplicate_events:
                # Duplicate with identical event_id to test idempotency
                events.append(
                    ProviderWebhookRequest(
                        event_id=ring_evt_id,
                        call_id=call_id,
                        provider=self.name,
                        event_type=ProviderEventType.RINGING,
                        timestamp=now,
                    )
                )

            ans_evt_id = f"evt_{uuid.uuid4().hex[:8]}"
            events.append(
                ProviderWebhookRequest(
                    event_id=ans_evt_id,
                    call_id=call_id,
                    provider=self.name,
                    event_type=ProviderEventType.ANSWERED,
                    timestamp=now,
                )
            )
            if self.simulate_duplicate_events:
                events.append(
                    ProviderWebhookRequest(
                        event_id=ans_evt_id,
                        call_id=call_id,
                        provider=self.name,
                        event_type=ProviderEventType.ANSWERED,
                        timestamp=now,
                    )
                )

            events.append(
                ProviderWebhookRequest(
                    event_id=f"evt_{uuid.uuid4().hex[:8]}",
                    call_id=call_id,
                    provider=self.name,
                    event_type=ProviderEventType.CONNECTED,
                    timestamp=now,
                )
            )

        return events
