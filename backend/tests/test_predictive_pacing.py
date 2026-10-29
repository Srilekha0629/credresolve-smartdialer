from datetime import datetime, timedelta
import pytest
from backend.app.models.call import Call
from backend.app.models.enums import AgentState, CallState, DialerMode, ProviderName
from backend.app.services.predictive_pacing import PredictivePacingEngine
from backend.app.services.dialer_orchestrator import DialerOrchestrator
from backend.app.providers.provider_manager import ProviderManager
from backend.app.storage.memory_store import MemoryStore


def test_predictive_pacing_low_answer_rate_triggers_progressive_fallback():
    """
    Test 7A: When answer rate is below safety threshold (e.g. 10% < 15%),
    the pacing engine safely falls back to progressive mode (1:1 with available agents).
    """
    store = MemoryStore.get_instance()
    pacing = PredictivePacingEngine(store=store)

    assert len(store.get_available_agents()) == 3

    suggestion = pacing.suggest_call_volume(override_answer_rate=0.08, allow_fallback=True)

    assert suggestion.fallback_to_progressive is True
    assert suggestion.suggested_calls == 3
    assert "Fallen back to progressive mode" in suggestion.reason


def test_predictive_pacing_respects_max_pacing_ratio_cap():
    """
    Test 7B: Bounded pacing prevents runaway overdialing by capping suggestions
    to max_pacing_ratio * available agents.
    """
    store = MemoryStore.get_instance()
    pacing = PredictivePacingEngine(store=store)

    # 3 available agents with 2.0x ratio -> capped at 6 calls maximum
    suggestion = pacing.suggest_call_volume(
        override_answer_rate=0.20,
        max_pacing_ratio=2.0,
        allow_fallback=False,
    )

    assert suggestion.suggested_calls <= 6
    assert suggestion.bounded_calls <= 6


@pytest.mark.asyncio
async def test_predictive_low_answer_rate_executes_progressive_fallback_through_safety():
    store = MemoryStore.get_instance()
    orchestrator = DialerOrchestrator(store=store)

    result = await orchestrator.run_predictive_cycle(
        target_answer_rate=0.08,
        allow_fallback=True,
    )

    assert result.mode == DialerMode.PROGRESSIVE
    assert result.proposed_calls == 3
    assert result.safe_approved_calls <= len(store.get_agents())
    assert result.calls_initiated == len(result.call_ids)
    assert "Fallen back to progressive mode" in result.notes


@pytest.mark.asyncio
async def test_predictive_cycle_strictly_enforced_by_safety_controller():
    """
    Test 7C: Even if predictive pacing suggests a higher volume of calls,
    the dialer cycle cannot bypass the Safety Controller and is strictly clamped
    to safe agent capacity.
    """
    store = MemoryStore.get_instance()
    orchestrator = DialerOrchestrator(store=store)

    assert len(store.get_available_agents()) == 3

    # Force predictive cycle with high multiplier
    result = await orchestrator.run_predictive_cycle(
        target_answer_rate=0.30,
        max_pacing_ratio=3.0,
        allow_fallback=False,
    )

    assert result.mode == DialerMode.PREDICTIVE
    # Safe approved calls cannot exceed available agent count (3)
    assert result.safe_approved_calls <= 3
    assert result.calls_initiated <= 3
    assert len(result.call_ids) <= 3


def test_predictive_pacing_never_directly_initiates_calls_or_reserves_agents():
    """
    Test 7D: Pacing logic is purely computational and never mutates agent/call state.
    """
    store = MemoryStore.get_instance()
    pacing = PredictivePacingEngine(store=store)

    available_before = len(store.get_available_agents())
    calls_before = len(store.get_calls())

    # Generate suggestion
    _ = pacing.suggest_call_volume(override_answer_rate=0.50)

    # Verify zero mutations
    assert len(store.get_available_agents()) == available_before
    assert len(store.get_calls()) == calls_before


def test_predictive_pacing_uses_measured_setup_and_talk_times():
    store = MemoryStore.get_instance()
    agents = store.get_agents()
    for agent in agents:
        agent.state = AgentState.OFFLINE
        store.update_agent(agent)

    available = store.get_agent("agt_001")
    available.state = AgentState.AVAILABLE
    store.update_agent(available)

    base_time = datetime.utcnow() - timedelta(minutes=2)
    for index, agent_id in enumerate(("agt_002", "agt_003"), start=1):
        agent = store.get_agent(agent_id)
        agent.state = AgentState.CONNECTED
        agent.current_call_id = f"call_connected_{index}"
        store.update_agent(agent)
        store.save_call(
            Call(
                id=agent.current_call_id,
                borrower_id=f"bor_10{index}",
                borrower_name="Connected borrower",
                borrower_phone="+15550101",
                agent_id=agent_id,
                state=CallState.CONNECTED,
                created_at=base_time,
                initiated_at=base_time + timedelta(seconds=1),
            )
        )

    store.save_call(
        Call(
            id="call_completed_for_talk_time",
            borrower_id="bor_103",
            borrower_name="Completed borrower",
            borrower_phone="+15550103",
            state=CallState.COMPLETED,
            created_at=base_time,
            initiated_at=base_time + timedelta(seconds=1),
            duration_seconds=10,
        )
    )
    pacing = PredictivePacingEngine(store)

    quick_setup = pacing.suggest_call_volume(
        override_answer_rate=0.8, max_pacing_ratio=5.0, allow_fallback=False
    )
    assert quick_setup.setup_time_used_seconds == pytest.approx(1.0)
    assert quick_setup.average_talk_time_used_seconds == pytest.approx(10.0)

    for call in store.get_calls():
        if call.initiated_at is not None:
            call.initiated_at = call.created_at + timedelta(seconds=10)
            store.save_call(call)

    slower_setup = pacing.suggest_call_volume(
        override_answer_rate=0.8, max_pacing_ratio=5.0, allow_fallback=False
    )
    assert slower_setup.setup_time_used_seconds == pytest.approx(10.0)
    assert slower_setup.suggested_calls > quick_setup.suggested_calls


def test_predictive_pacing_reduces_batch_when_primary_provider_is_unhealthy():
    store = MemoryStore.get_instance()
    providers = ProviderManager.get_instance()
    providers.set_primary_provider(ProviderName.PROVIDER_B)
    engine = PredictivePacingEngine(store, providers)

    healthy = engine.suggest_call_volume(
        override_answer_rate=0.20, max_pacing_ratio=2.0, allow_fallback=False
    )
    providers.provider_b.set_healthy(False)
    degraded = engine.suggest_call_volume(
        override_answer_rate=0.20, max_pacing_ratio=2.0, allow_fallback=False
    )

    assert healthy.provider_health_factor == 1.0
    assert degraded.primary_provider_healthy is False
    assert degraded.fallback_provider_healthy is True
    assert degraded.provider_health_factor == 0.5
    assert degraded.suggested_calls < healthy.suggested_calls


def test_predictive_pacing_accounts_for_campaign_retry_behavior():
    store = MemoryStore.get_instance()
    engine = PredictivePacingEngine(store, ProviderManager.get_instance())
    fresh_campaign = engine.suggest_call_volume(
        override_answer_rate=0.20, max_pacing_ratio=2.0, allow_fallback=False
    )

    for borrower in store.get_queued_borrowers():
        borrower.calls_attempted = 1
        store.update_borrower(borrower)

    retry_heavy_campaign = engine.suggest_call_volume(
        override_answer_rate=0.20, max_pacing_ratio=2.0, allow_fallback=False
    )

    assert fresh_campaign.campaign_retry_rate == 0
    assert retry_heavy_campaign.campaign_retry_rate == 1
    assert retry_heavy_campaign.suggested_calls < fresh_campaign.suggested_calls


@pytest.mark.asyncio
async def test_predictive_provider_health_adjustment_still_passes_safety_gate():
    store = MemoryStore.get_instance()
    providers = ProviderManager.get_instance()
    providers.set_primary_provider(ProviderName.PROVIDER_B)
    providers.provider_b.set_healthy(False)
    available_before = len(store.get_available_agents())

    result = await DialerOrchestrator(
        store=store, provider_manager=providers
    ).run_predictive_cycle(
        target_answer_rate=0.20,
        max_pacing_ratio=3.0,
        allow_fallback=False,
    )

    assert result.safe_approved_calls <= available_before
    assert result.calls_initiated <= result.safe_approved_calls
    assert len(result.call_ids) == result.calls_initiated
