import asyncio
from typing import Tuple, Optional, Dict, Any
from backend.app.models.enums import ProviderName
from backend.app.providers.base_provider import BaseTelecomProvider


class ProviderA(BaseTelecomProvider):
    """
    Provider A: Fast & Reliable Telecom Provider.
    Zero intentional flakiness; high availability.
    """

    LATENCY_SECONDS = 0.045

    def __init__(self):
        super().__init__(ProviderName.PROVIDER_A)
        self._manual_unhealthy = False

    def is_healthy(self) -> bool:
        if self._manual_unhealthy:
            return False
        return self.consecutive_failures < 3

    def set_healthy(self, healthy: bool):
        self._manual_unhealthy = not healthy

    async def initiate_call(
        self, call_id: str, borrower_phone: str
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        if not self.is_healthy():
            self.record_failure()
            return False, "Provider A is currently unavailable or unhealthy.", {
                "acceptance_status": "REJECTED"
            }

        await asyncio.sleep(self.LATENCY_SECONDS)
        if not self.is_healthy():
            self.record_failure()
            return False, "Provider A became unavailable during call setup.", {
                "acceptance_status": "UNKNOWN"
            }

        self.record_success()
        return (
            True,
            "INITIATED",
            {
                "provider": self.name.value,
                "provider_call_id": f"prv_a_{call_id[-8:]}",
                "carrier": "Tier1_Direct",
                "latency_ms": round(self.LATENCY_SECONDS * 1000),
            },
        )
