import pytest
from datetime import datetime
from backend.app.models.enums import AgentState, CallState, ProviderEventType, ProviderName
from backend.app.models.call import Call
from backend.app.models.agent import Agent
from backend.app.models.provider_event import ProviderWebhookRequest
from backend.app.services.event_processor import EventProcessor
from backend.app.storage.memory_store import MemoryStore
from backend.app.state_machines.agent_state_machine import AgentStateMachine


def test_reserved_and_dialing_agents_cannot_transition_offline():
    assert not AgentStateMachine.can_transition(
        AgentState.RESERVED, AgentState.OFFLINE
    )
    assert not AgentStateMachine.can_transition(
        AgentState.DIALING, AgentState.OFFLINE
    )


@pytest.mark.asyncio
async def test_answered_event_synchronizes_reserved_agent_to_dialing():
    store = MemoryStore.get_instance()
    agent = store.get_agent("agt_001")
    borrower = store.get_borrower("bor_101")
    call = Call(
        id="call_answered_reservation",
        borrower_id=borrower.id,
        borrower_name=borrower.name,
        borrower_phone=borrower.phone,
        agent_id=agent.id,
        state=CallState.RESERVED,
    )
    agent.state = AgentState.RESERVED
    agent.current_call_id = call.id
    store.update_agent(agent)
    borrower.status = "DIALING"
    borrower.last_call_id = call.id
    store.update_borrower(borrower)
    store.save_call(call)

    response = await EventProcessor(store).process_event(
        ProviderWebhookRequest(
            event_id="evt_answered_reserved",
            call_id=call.id,
            provider=ProviderName.PROVIDER_A,
            event_type=ProviderEventType.ANSWERED,
            timestamp=datetime.utcnow(),
        )
    )

    assert response.success
    assert store.get_call(call.id).state == CallState.ANSWERED
    assert store.get_agent(agent.id).state == AgentState.DIALING
    assert store.get_agent(agent.id).current_call_id == call.id
    assert store.get_borrower(borrower.id).status == "DIALING"


@pytest.mark.asyncio
async def test_late_answered_event_never_revives_completed_call():
    """
    Test 5A: Terminal preservation.
    A late ANSWERED event arriving after a call is COMPLETED must be rejected,
    and must NEVER revive the call or corrupt agent state.
    """
    store = MemoryStore.get_instance()
    processor = EventProcessor(store=store)

    call = Call(
        id="call_completed_001",
        borrower_id="bor_101",
        borrower_name="Alice Walker",
        borrower_phone="+15550101",
        agent_id="agt_001",
        state=CallState.COMPLETED,
    )
    store.save_call(call)

    # Set agent to WRAP_UP
    agent = store.get_agent("agt_001")
    agent.state = AgentState.WRAP_UP
    store.update_agent(agent)

    # Late arriving ANSWERED event
    late_event = ProviderWebhookRequest(
        event_id="evt_late_ans_999",
        call_id=call.id,
        provider=ProviderName.PROVIDER_B,
        event_type=ProviderEventType.ANSWERED,
        timestamp=datetime.utcnow(),
    )

    resp = await processor.process_event(late_event)

    assert resp.success is False
    assert resp.status == "rejected_illegal_transition"
    assert "terminal state COMPLETED" in resp.message
    assert resp.current_call_state == CallState.COMPLETED

    # Verify call state remains COMPLETED
    call_in_db = store.get_call(call.id)
    assert call_in_db.state == CallState.COMPLETED

    # Verify agent was not modified to CONNECTED
    agent_in_db = store.get_agent("agt_001")
    assert agent_in_db.state == AgentState.WRAP_UP


@pytest.mark.asyncio
async def test_late_event_never_revives_cancelled_call():
    """Test 5B: Late events cannot revive a CANCELLED call."""
    store = MemoryStore.get_instance()
    processor = EventProcessor(store=store)

    call = Call(
        id="call_cancelled_002",
        borrower_id="bor_102",
        borrower_name="Bob Martin",
        borrower_phone="+15550102",
        agent_id="agt_002",
        state=CallState.CANCELLED,
    )
    store.save_call(call)

    late_event = ProviderWebhookRequest(
        event_id="evt_late_ring_888",
        call_id=call.id,
        provider=ProviderName.PROVIDER_B,
        event_type=ProviderEventType.RINGING,
        timestamp=datetime.utcnow(),
    )

    resp = await processor.process_event(late_event)
    assert resp.success is False
    assert resp.status == "rejected_illegal_transition"
    assert resp.current_call_state == CallState.CANCELLED


@pytest.mark.asyncio
async def test_invalid_skip_transition_rejected():
    """Test 5C: Skipping legal states (e.g. QUEUED directly to CONNECTED) is rejected."""
    store = MemoryStore.get_instance()
    processor = EventProcessor(store=store)

    call = Call(
        id="call_queued_003",
        borrower_id="bor_103",
        borrower_name="Charlie Brown",
        borrower_phone="+15550103",
        state=CallState.QUEUED,
    )
    store.save_call(call)

    invalid_event = ProviderWebhookRequest(
        event_id="evt_illegal_conn_777",
        call_id=call.id,
        provider=ProviderName.PROVIDER_A,
        event_type=ProviderEventType.CONNECTED,
        timestamp=datetime.utcnow(),
    )

    resp = await processor.process_event(invalid_event)
    assert resp.success is False
    assert resp.status == "rejected_illegal_transition"
    assert resp.current_call_state == CallState.QUEUED


@pytest.mark.asyncio
async def test_out_of_order_ringing_after_answered_is_rejected():
    store = MemoryStore.get_instance()
    processor = EventProcessor(store=store)
    call = Call(
        id="call_out_of_order_004",
        borrower_id="bor_104",
        borrower_name="Diana Prince",
        borrower_phone="+15550104",
        agent_id="agt_001",
        state=CallState.INITIATED,
    )
    store.save_call(call)

    answered = ProviderWebhookRequest(
        event_id="evt_answered_first_004",
        call_id=call.id,
        provider=ProviderName.PROVIDER_B,
        event_type=ProviderEventType.ANSWERED,
        timestamp=datetime.utcnow(),
    )
    late_ringing = ProviderWebhookRequest(
        event_id="evt_ringing_late_004",
        call_id=call.id,
        provider=ProviderName.PROVIDER_B,
        event_type=ProviderEventType.RINGING,
        timestamp=datetime.utcnow(),
    )

    answered_response = await processor.process_event(answered)
    ringing_response = await processor.process_event(late_ringing)

    assert answered_response.success is True
    assert answered_response.current_call_state == CallState.ANSWERED
    assert ringing_response.success is False
    assert ringing_response.status == "rejected_illegal_transition"
    assert ringing_response.current_call_state == CallState.ANSWERED
    assert store.get_call(call.id).state == CallState.ANSWERED


@pytest.mark.asyncio
async def test_connected_call_failure_moves_agent_to_wrap_up():
    store = MemoryStore.get_instance()
    processor = EventProcessor(store=store)
    call = Call(
        id="call_connected_failure",
        borrower_id="bor_105",
        borrower_name="Evan Wright",
        borrower_phone="+15550105",
        agent_id="agt_001",
        state=CallState.CONNECTED,
    )
    agent = store.get_agent(call.agent_id)
    agent.state = AgentState.CONNECTED
    agent.current_call_id = call.id
    store.update_agent(agent)
    store.save_call(call)

    response = await processor.process_event(
        ProviderWebhookRequest(
            event_id="evt_connected_failure",
            call_id=call.id,
            provider=ProviderName.PROVIDER_A,
            event_type=ProviderEventType.FAILED,
        )
    )

    assert response.success is True
    assert store.get_call(call.id).state == CallState.FAILED
    updated_agent = store.get_agent(call.agent_id)
    assert updated_agent.state == AgentState.WRAP_UP
    assert updated_agent.current_call_id is None
