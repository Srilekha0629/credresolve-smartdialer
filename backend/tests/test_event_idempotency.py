import pytest
from datetime import datetime
from backend.app.models.enums import CallState, ProviderEventType, ProviderName
from backend.app.models.call import Call
from backend.app.models.provider_event import ProviderWebhookRequest
from backend.app.services.event_processor import EventProcessor
from backend.app.storage.memory_store import MemoryStore


@pytest.mark.asyncio
async def test_duplicate_provider_events_are_idempotent():
    """
    Test 4: Duplicate provider events being idempotent.
    Sending the identical event_id twice must be safely ignored on subsequent calls.
    """
    store = MemoryStore.get_instance()
    processor = EventProcessor(store=store)

    # Setup initial call
    call = Call(
        id="call_test_idem_1",
        borrower_id="bor_101",
        borrower_name="Alice Walker",
        borrower_phone="+15550101",
        agent_id="agt_001",
        state=CallState.INITIATED,
    )
    store.save_call(call)

    # First event: RINGING
    event_1 = ProviderWebhookRequest(
        event_id="evt_ring_unique_001",
        call_id=call.id,
        provider=ProviderName.PROVIDER_A,
        event_type=ProviderEventType.RINGING,
        timestamp=datetime.utcnow(),
    )

    resp_1 = await processor.process_event(event_1)
    assert resp_1.success is True
    assert resp_1.status == "processed"
    assert resp_1.current_call_state == CallState.RINGING

    # Second event: DUPLICATE of event_1 with exact same event_id
    resp_2 = await processor.process_event(event_1)
    assert resp_2.success is True
    assert resp_2.status == "ignored_duplicate"
    assert "already processed" in resp_2.message
    assert resp_2.current_call_state == CallState.RINGING

    # Verify store still has call in RINGING
    updated_call = store.get_call(call.id)
    assert updated_call.state == CallState.RINGING
