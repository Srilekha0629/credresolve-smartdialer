import pytest
from backend.app.models.enums import AgentState, CallState
from backend.app.models.call import Call
from backend.app.services.safety_controller import SafetyController
from backend.app.storage.memory_store import MemoryStore


def test_safety_controller_reduces_unsafe_batches():
    """
    Test 3: Safety Controller reducing or rejecting unsafe batches.
    When 10 calls are proposed but only 3 agents are available,
    the Safety Controller clamps approved calls to exactly 3.
    """
    store = MemoryStore.get_instance()
    controller = SafetyController(store=store)

    assert len(store.get_available_agents()) == 3

    batch = controller.validate_and_filter_batch(proposed_count=10)

    assert batch.is_safe is True
    assert batch.proposed_count == 10
    assert batch.approved_count == 3
    assert len(batch.pairs) == 3
    assert "Reduced proposed batch from 10 to 3" in batch.audit_reason


def test_safety_controller_rejects_when_zero_capacity():
    """When no agents are available, safety controller rejects entire batch."""
    store = MemoryStore.get_instance()
    controller = SafetyController(store=store)

    # Set all agents to OFFLINE
    for agt in store.get_agents():
        agt.state = AgentState.OFFLINE
        store.update_agent(agt)

    assert len(store.get_available_agents()) == 0

    batch = controller.validate_and_filter_batch(proposed_count=5)

    assert batch.is_safe is False
    assert batch.approved_count == 0
    assert len(batch.pairs) == 0
    assert "Safety check rejected: 0 safe capacity" in batch.audit_reason


def test_safety_controller_prevents_duplicate_borrower_allocation():
    """Borrowers with active calls must not be assigned again."""
    store = MemoryStore.get_instance()
    controller = SafetyController(store=store)

    # Put bor_101 into an active call
    call = Call(
        id="call_existing_1",
        borrower_id="bor_101",
        borrower_name="Alice Walker",
        borrower_phone="+15550101",
        agent_id="agt_001",
        state=CallState.CONNECTED,
    )
    store.save_call(call)

    # Validate batch
    batch = controller.validate_and_filter_batch(proposed_count=5)
    allocated_borrower_ids = [bor.id for _, bor in batch.pairs]

    assert "bor_101" not in allocated_borrower_ids
