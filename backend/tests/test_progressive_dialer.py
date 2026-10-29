import pytest
from backend.app.models.enums import AgentState, CallState
from backend.app.models.agent import Agent
from backend.app.models.borrower import Borrower
from backend.app.models.enums import ProviderName
from backend.app.services.dialer_orchestrator import DialerOrchestrator
from backend.app.storage.memory_store import MemoryStore


class ImmediateProvider:
    primary_provider_name = ProviderName.PROVIDER_A

    async def initiate_call_with_fallback(self, call_id, borrower_phone):
        return True, ProviderName.PROVIDER_A, "INITIATED", {}, False


@pytest.mark.asyncio
async def test_progressive_dialer_never_exceeds_safe_agent_availability():
    """
    Test 1: Progressive mode never exceeding safe agent availability.
    With 3 available agents and 12 queued borrowers, progressive dialing
    must initiate AT MOST 3 calls and reserve AT MOST 3 agents.
    """
    store = MemoryStore.get_instance()
    orchestrator = DialerOrchestrator(store=store)

    # Initial state: 3 agents are AVAILABLE (agt_001, agt_002, agt_003)
    available_agents_before = store.get_available_agents()
    assert len(available_agents_before) == 3

    # Run progressive dial cycle
    result = await orchestrator.run_progressive_cycle()

    assert result.proposed_calls == 3
    assert result.safe_approved_calls == 3
    assert result.calls_initiated == 3
    assert len(result.call_ids) == 3

    # Verify no more agents are available now
    available_agents_after = store.get_available_agents()
    assert len(available_agents_after) == 0

    # Verify all 3 reserved/initiated agents are properly marked
    agents = store.get_agents()
    active_agent_states = [a.state for a in agents if a.id in ["agt_001", "agt_002", "agt_003"]]
    for state in active_agent_states:
        assert state in (AgentState.RESERVED, AgentState.DIALING)

    # Now run another cycle: 0 agents are available -> 0 calls initiated
    second_result = await orchestrator.run_progressive_cycle()
    assert second_result.safe_approved_calls == 0
    assert second_result.calls_initiated == 0
    assert len(second_result.call_ids) == 0


@pytest.mark.asyncio
async def test_progressive_dialer_respects_max_calls_cap():
    """Progressive mode respects user-supplied max_calls cap when lower than available agents."""
    store = MemoryStore.get_instance()
    orchestrator = DialerOrchestrator(store=store)

    result = await orchestrator.run_progressive_cycle(max_calls=1)

    assert result.safe_approved_calls == 1
    assert result.calls_initiated == 1
    assert len(result.call_ids) == 1

    # Exactly 2 agents should remain available
    assert len(store.get_available_agents()) == 2


@pytest.mark.asyncio
async def test_progressive_dialer_caps_at_60_after_availability_falls_from_100(tmp_path):
    store = MemoryStore(str(tmp_path / "availability-drop.sqlite3"))
    with store.transaction():
        store.agents = {
            f"agent_{index:03d}": Agent(
                id=f"agent_{index:03d}",
                name=f"Agent {index}",
                state=AgentState.AVAILABLE if index < 60 else AgentState.OFFLINE,
            )
            for index in range(100)
        }
        store.borrowers = {
            f"borrower_{index:03d}": Borrower(
                id=f"borrower_{index:03d}",
                name=f"Borrower {index}",
                phone=f"+1555{index:07d}",
            )
            for index in range(100)
        }

    result = await DialerOrchestrator(
        store=store, provider_manager=ImmediateProvider()
    ).run_progressive_cycle()

    active_calls = store.get_active_calls()
    assert result.available_agents_before == 60
    assert result.safe_approved_calls == result.calls_initiated == 60
    assert len(active_calls) == 60
    assert len({call.agent_id for call in active_calls}) == 60
    assert len({call.borrower_id for call in active_calls}) == 60
