import asyncio

import pytest
from fastapi import HTTPException

from backend.app.main import update_agent_state
from backend.app.models.agent import AgentStateUpdate
from backend.app.models.enums import (
    AgentState,
    CallState,
    ProviderName,
    ProviderSubmissionStatus,
)
from backend.app.services.dialer_orchestrator import DialerOrchestrator
from backend.app.storage.memory_store import MemoryStore


class CrashingProviderManager:
    primary_provider_name = ProviderName.PROVIDER_A

    async def initiate_call_with_fallback(self, call_id, borrower_phone):
        raise RuntimeError("simulated provider worker crash")


class GatedProviderManager:
    primary_provider_name = ProviderName.PROVIDER_A

    def __init__(self):
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def initiate_call_with_fallback(self, call_id, borrower_phone):
        self.started.set()
        await self.release.wait()
        return True, ProviderName.PROVIDER_A, "INITIATED", {}, False


@pytest.mark.asyncio
async def test_provider_worker_exception_retains_uncertain_call_reservation():
    store = MemoryStore.get_instance()
    orchestrator = DialerOrchestrator(
        store=store, provider_manager=CrashingProviderManager()
    )

    result = await orchestrator.run_progressive_cycle(max_calls=1)

    assert result.calls_initiated == 0
    call = store.get_call(result.call_ids[0]) if result.call_ids else store.get_calls()[0]
    assert call.state == CallState.RESERVED
    assert call.provider_submission_status == ProviderSubmissionStatus.UNKNOWN
    assert "simulated provider worker crash" in call.error_reason
    agent = store.get_agent(call.agent_id)
    assert agent.state == AgentState.RESERVED
    assert agent.current_call_id == call.id
    borrower = store.get_borrower(call.borrower_id)
    assert borrower.status == "DIALING"


@pytest.mark.asyncio
async def test_agent_cannot_be_taken_offline_during_provider_setup():
    store = MemoryStore.get_instance()
    provider = GatedProviderManager()
    orchestrator = DialerOrchestrator(store=store, provider_manager=provider)

    cycle = asyncio.create_task(orchestrator.run_progressive_cycle(max_calls=1))
    await provider.started.wait()

    agent = next(agent for agent in store.get_agents() if agent.state == AgentState.RESERVED)
    with pytest.raises(HTTPException) as exc_info:
        await update_agent_state(agent.id, AgentStateUpdate(state=AgentState.OFFLINE))
    assert exc_info.value.status_code == 409
    reserved_call = store.get_call(agent.current_call_id)
    assert reserved_call.state == CallState.RESERVED
    assert reserved_call.provider_submission_status == ProviderSubmissionStatus.SUBMITTING
    assert store.get_agent(agent.id).state == AgentState.RESERVED
    assert store.get_borrower(reserved_call.borrower_id).status == "DIALING"

    provider.release.set()
    result = await cycle
    assert result.calls_initiated == 1
    call = store.get_call(result.call_ids[0])
    updated_agent = store.get_agent(agent.id)
    assert call.state == CallState.INITIATED
    assert updated_agent.state == AgentState.DIALING
    assert updated_agent.current_call_id == call.id


@pytest.mark.asyncio
async def test_cancelled_dialer_cycle_retains_uncertain_call_and_releases_unsubmitted_calls():
    store = MemoryStore.get_instance()
    provider = GatedProviderManager()
    orchestrator = DialerOrchestrator(store=store, provider_manager=provider)

    cycle = asyncio.create_task(orchestrator.run_progressive_cycle())
    await provider.started.wait()
    cycle.cancel()
    with pytest.raises(asyncio.CancelledError):
        await cycle

    assert len(store.get_calls()) == 3
    uncertain = [
        call for call in store.get_calls()
        if call.provider_submission_status == ProviderSubmissionStatus.UNKNOWN
    ]
    failed = [call for call in store.get_calls() if call.state == CallState.FAILED]
    assert len(uncertain) == 1
    assert len(failed) == 2
    assert len(store.get_available_agents()) == 2
    assert store.get_agent(uncertain[0].agent_id).current_call_id == uncertain[0].id
