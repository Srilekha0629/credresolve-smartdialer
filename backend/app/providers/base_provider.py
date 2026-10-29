from abc import ABC, abstractmethod
from typing import Tuple, Optional, Dict, Any
from backend.app.models.enums import ProviderName


class BaseTelecomProvider(ABC):
    """Common abstraction for all telecom providers."""

    def __init__(self, name: ProviderName):
        self.name = name
        self.is_active = True
        self.consecutive_failures = 0
        self.total_calls_initiated = 0
        self.total_failures = 0

    @abstractmethod
    def is_healthy(self) -> bool:
        """Return True if provider is operational and able to accept new calls."""
        pass

    @abstractmethod
    async def initiate_call(
        self, call_id: str, borrower_phone: str
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """
        Attempts to initiate an outbound phone call via telecom provider.
        Returns: (success: bool, status_or_error: str, provider_meta: dict)
        """
        pass

    def record_success(self):
        self.consecutive_failures = 0
        self.total_calls_initiated += 1

    def record_failure(self):
        self.consecutive_failures += 1
        self.total_failures += 1
