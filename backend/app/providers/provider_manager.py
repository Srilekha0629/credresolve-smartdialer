from typing import Dict, Any, List, Tuple, Optional
from backend.app.models.enums import ProviderName
from backend.app.providers.base_provider import BaseTelecomProvider
from backend.app.providers.provider_a import ProviderA
from backend.app.providers.provider_b import ProviderB


class ProviderManager:
    """
    Manages telecom providers, handles outage detection, and executes automatic fallback.
    Default routing: Provider A (reliable) as primary, with Provider B as selectable/testable,
    or Provider B with automatic fallback to Provider A if B fails or is unhealthy.
    """

    _instance: Optional["ProviderManager"] = None

    def __init__(self):
        self.provider_a = ProviderA()
        self.provider_b = ProviderB()
        self.primary_provider_name: ProviderName = ProviderName.PROVIDER_A

    @classmethod
    def get_instance(cls) -> "ProviderManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def get_provider(self, name: ProviderName) -> BaseTelecomProvider:
        if name == ProviderName.PROVIDER_A:
            return self.provider_a
        return self.provider_b

    def get_primary_provider(self) -> BaseTelecomProvider:
        return self.get_provider(self.primary_provider_name)

    def set_primary_provider(self, name: ProviderName):
        self.primary_provider_name = name

    async def initiate_call_with_fallback(
        self, call_id: str, borrower_phone: str, preferred_provider: Optional[ProviderName] = None
    ) -> Tuple[bool, ProviderName, str, Optional[Dict[str, Any]], bool]:
        """
        Attempts to initiate call using preferred (or primary) provider.
        Definite rejection or known unavailability may fall back to Provider A.
        An UNKNOWN acceptance result is never retried on another provider.
        Returns: (success, used_provider, status_or_error, meta, fallback_occurred)
        """
        target_name = preferred_provider or self.primary_provider_name
        target_provider = self.get_provider(target_name)

        # 1. Try target provider if healthy
        if target_provider.is_healthy():
            success, status, meta = await target_provider.initiate_call(call_id, borrower_phone)
            if success:
                return True, target_name, status, meta, False
            if meta and meta.get("acceptance_status") == "UNKNOWN":
                return False, target_name, status, meta, False

        # 2. Target provider failed or unhealthy -> Fallback policy
        # If target was Provider B, fallback to Provider A
        if target_name != ProviderName.PROVIDER_A:
            fallback_provider = self.provider_a
            if fallback_provider.is_healthy():
                success, status, meta = await fallback_provider.initiate_call(call_id, borrower_phone)
                if success:
                    meta = meta or {}
                    meta["fallback_from"] = target_name.value
                    return True, ProviderName.PROVIDER_A, status, meta, True
                if meta and meta.get("acceptance_status") == "UNKNOWN":
                    return False, ProviderName.PROVIDER_A, status, meta, True

        return (
            False,
            target_name,
            f"All providers exhausted or unhealthy for call {call_id}",
            {"acceptance_status": "REJECTED"},
            False,
        )

    def get_provider_statuses(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": self.provider_a.name.value,
                "is_healthy": self.provider_a.is_healthy(),
                "consecutive_failures": self.provider_a.consecutive_failures,
                "total_calls": self.provider_a.total_calls_initiated,
                "total_failures": self.provider_a.total_failures,
                "configured_latency_ms": self.provider_a.LATENCY_SECONDS * 1000,
                "is_primary": self.primary_provider_name == ProviderName.PROVIDER_A,
                "description": "Fast and reliable Tier-1 carrier route.",
            },
            {
                "name": self.provider_b.name.value,
                "is_healthy": self.provider_b.is_healthy(),
                "consecutive_failures": self.provider_b.consecutive_failures,
                "total_calls": self.provider_b.total_calls_initiated,
                "total_failures": self.provider_b.total_failures,
                "configured_latency_ms": self.provider_b.LATENCY_SECONDS * 1000,
                "timeout_ms": self.provider_b.TIMEOUT_SECONDS * 1000,
                "is_primary": self.primary_provider_name == ProviderName.PROVIDER_B,
                "simulation_modes": {
                    "simulate_timeout": self.provider_b.simulate_timeout,
                    "simulate_failure": self.provider_b.simulate_failure,
                    "simulate_duplicate": self.provider_b.simulate_duplicate_events,
                    "simulate_out_of_order": self.provider_b.simulate_out_of_order,
                },
                "description": "Flaky simulated provider with intentional faults & race conditions.",
            },
        ]
