from types import SimpleNamespace
import pytest
from backend.app.models.enums import (
    AgentState,
    CallState,
    ProviderName,
    ProviderSubmissionStatus,
)
from backend.app.providers.provider_manager import ProviderManager
from backend.app.services.dialer_orchestrator import DialerOrchestrator
from backend.app.storage.memory_store import MemoryStore


@pytest.mark.asyncio
async def test_provider_b_timeout_does_not_retry_uncertain_call_on_provider_a():
    """
    Test 6A: Provider failures and fallback behavior.
    A gateway timeout has uncertain acceptance, so retrying on Provider A could
    create a second outbound call. The assignment remains reserved for reconciliation.
    """
    store = MemoryStore.get_instance()
    pm = ProviderManager.get_instance()
    pm.set_primary_provider(ProviderName.PROVIDER_B)
    pm.provider_b.configure_simulation(simulate_timeout=True)

    orchestrator = DialerOrchestrator(store=store, provider_manager=pm)

    result = await orchestrator.run_progressive_cycle(max_calls=1)

    assert result.safe_approved_calls == 1
    assert result.calls_initiated == 0

    call = store.get_calls()[0]
    assert call.provider == ProviderName.PROVIDER_B
    assert call.state == CallState.RESERVED
    assert call.provider_submission_status == ProviderSubmissionStatus.UNKNOWN
    assert store.get_agent(call.agent_id).current_call_id == call.id


@pytest.mark.asyncio
async def test_definite_provider_b_rejection_falls_back_to_provider_a():
    store = MemoryStore.get_instance()
    pm = ProviderManager.get_instance()
    pm.set_primary_provider(ProviderName.PROVIDER_B)
    pm.provider_b.configure_simulation(simulate_failure=True)

    result = await DialerOrchestrator(store=store, provider_manager=pm).run_progressive_cycle(
        max_calls=1
    )

    assert result.calls_initiated == 1
    call = store.get_call(result.call_ids[0])
    assert call.provider == ProviderName.PROVIDER_A
    assert call.provider_submission_status == ProviderSubmissionStatus.ACCEPTED
    assert call.state == CallState.INITIATED


@pytest.mark.asyncio
async def test_total_provider_outage_safely_releases_reserved_agents():
    """
    Test 6B: When all telecom providers are down/unhealthy, calls fail gracefully
    and reserved agents are immediately freed back to AVAILABLE.
    """
    store = MemoryStore.get_instance()
    pm = ProviderManager.get_instance()
    pm.set_primary_provider(ProviderName.PROVIDER_B)
    pm.provider_b.configure_simulation(simulate_failure=True)
    pm.provider_a.set_healthy(False)  # Both providers now down

    orchestrator = DialerOrchestrator(store=store, provider_manager=pm)

    result = await orchestrator.run_progressive_cycle(max_calls=1)

    # 0 calls successfully initiated
    assert result.calls_initiated == 0

    # All originally available agents must be freed back to AVAILABLE (not stuck in RESERVED)
    available_agents = store.get_available_agents()
    assert len(available_agents) == 3

    # Check that failed call recorded proper error reason
    calls = store.get_calls()
    assert len(calls) == 1
    assert calls[0].state == CallState.FAILED
    assert "All providers exhausted or unhealthy" in calls[0].error_reason


@pytest.mark.asyncio
async def test_mock_providers_have_distinct_async_setup_latency(monkeypatch):
    pm = ProviderManager.get_instance()
    observed_delays = []

    async def record_delay(delay):
        observed_delays.append(delay)

    simulated_asyncio = SimpleNamespace(sleep=record_delay)
    monkeypatch.setattr(
        "backend.app.providers.provider_a.asyncio", simulated_asyncio
    )
    monkeypatch.setattr(
        "backend.app.providers.provider_b.asyncio", simulated_asyncio
    )

    success_a, _, meta_a = await pm.provider_a.initiate_call("call_latency_a", "+15550101")
    success_b, _, meta_b = await pm.provider_b.initiate_call("call_latency_b", "+15550102")

    assert success_a and success_b
    assert meta_a["latency_ms"] == 45
    assert meta_b["latency_ms"] == 200
    assert observed_delays == [0.045, 0.2]
