import os
import subprocess
import sys
from pathlib import Path

import pytest

from backend.app.models.call import Call
from backend.app.models.enums import (
    AgentState,
    CallState,
    ProviderName,
    ProviderSubmissionStatus,
)
from backend.app.models.provider_event import ProviderWebhookRequest
from backend.app.services.event_processor import EventProcessor
from backend.app.storage.memory_store import MemoryStore


def test_restart_recovers_uncertain_submission_without_releasing_reservations(tmp_path):
    database_path = tmp_path / "uncertain.sqlite3"
    store = MemoryStore(str(database_path))
    agent = store.get_available_agents()[0]
    borrower = store.get_queued_borrowers()[0]
    call = Call(
        id="call_uncertain",
        borrower_id=borrower.id,
        borrower_name=borrower.name,
        borrower_phone=borrower.phone,
        agent_id=agent.id,
        provider=ProviderName.PROVIDER_A,
        state=CallState.RESERVED,
        provider_submission_status=ProviderSubmissionStatus.SUBMITTING,
    )
    with store.transaction():
        agent.state = AgentState.RESERVED
        agent.current_call_id = call.id
        store.update_agent(agent)
        borrower.status = "DIALING"
        borrower.last_call_id = call.id
        store.update_borrower(borrower)
        store.save_call(call)

    restarted = MemoryStore(str(database_path))
    recovered = restarted.get_call(call.id)

    assert recovered.state == CallState.RESERVED
    assert recovered.provider_submission_status == ProviderSubmissionStatus.UNKNOWN
    assert restarted.get_agent(agent.id).current_call_id == call.id
    assert restarted.get_borrower(borrower.id).status == "DIALING"


def test_abrupt_process_exit_preserves_accepted_initiated_call(tmp_path):
    database_path = tmp_path / "crash-recovery.sqlite3"
    project_root = Path(__file__).resolve().parents[2]
    script = """
import asyncio
import os
from backend.app.models.enums import ProviderName
from backend.app.services.dialer_orchestrator import DialerOrchestrator
from backend.app.storage.memory_store import MemoryStore

class AcceptedProvider:
    primary_provider_name = ProviderName.PROVIDER_A
    async def initiate_call_with_fallback(self, call_id, borrower_phone):
        return True, ProviderName.PROVIDER_A, "INITIATED", {}, False

async def main():
    store = MemoryStore()
    await DialerOrchestrator(store=store, provider_manager=AcceptedProvider()).run_progressive_cycle(max_calls=1)

asyncio.run(main())
os._exit(0)
"""
    environment = os.environ.copy()
    environment["SMARTDIALER_DB_PATH"] = str(database_path)

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=project_root,
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0

    restarted = MemoryStore(str(database_path))
    calls = restarted.get_calls()
    assert len(calls) == 1
    call = calls[0]
    assert call.state == CallState.INITIATED
    assert call.provider_submission_status == ProviderSubmissionStatus.ACCEPTED
    agent = restarted.get_agent(call.agent_id)
    assert agent.state == AgentState.DIALING
    assert agent.current_call_id == call.id
    borrower = restarted.get_borrower(call.borrower_id)
    assert borrower.status == "DIALING"
    assert borrower.last_call_id == call.id


@pytest.mark.parametrize(
    ("stage", "expected_state", "expected_submission", "expected_agent_state", "expected_borrower"),
    [
        ("NOT_SUBMITTED", CallState.FAILED, ProviderSubmissionStatus.NOT_SUBMITTED, AgentState.AVAILABLE, "QUEUED"),
        ("SUBMITTING", CallState.RESERVED, ProviderSubmissionStatus.UNKNOWN, AgentState.RESERVED, "DIALING"),
        ("ACCEPTED", CallState.INITIATED, ProviderSubmissionStatus.ACCEPTED, AgentState.DIALING, "DIALING"),
        ("ANSWERED", CallState.ANSWERED, ProviderSubmissionStatus.ACCEPTED, AgentState.DIALING, "DIALING"),
    ],
)
def test_abrupt_process_exit_recovers_each_submission_stage(
    tmp_path,
    stage,
    expected_state,
    expected_submission,
    expected_agent_state,
    expected_borrower,
):
    database_path = tmp_path / f"crash-{stage.lower()}.sqlite3"
    project_root = Path(__file__).resolve().parents[2]
    script = """
import asyncio
import os
from backend.app.models.call import Call
from backend.app.models.enums import AgentState, CallState, ProviderName, ProviderSubmissionStatus
from backend.app.models.provider_event import ProviderWebhookRequest
from backend.app.services.event_processor import EventProcessor
from backend.app.storage.memory_store import MemoryStore

store = MemoryStore()
agent = store.get_available_agents()[0]
borrower = store.get_queued_borrowers()[0]
stage = os.environ["SMARTDIALER_CRASH_STAGE"]
call_state = CallState.RESERVED if stage in ("NOT_SUBMITTED", "SUBMITTING") else CallState.INITIATED
submission_status = {
    "NOT_SUBMITTED": ProviderSubmissionStatus.NOT_SUBMITTED,
    "SUBMITTING": ProviderSubmissionStatus.SUBMITTING,
    "ACCEPTED": ProviderSubmissionStatus.ACCEPTED,
    "ANSWERED": ProviderSubmissionStatus.ACCEPTED,
}[stage]
call = Call(
    id=f"call_crash_{stage.lower()}",
    borrower_id=borrower.id,
    borrower_name=borrower.name,
    borrower_phone=borrower.phone,
    agent_id=agent.id,
    provider=ProviderName.PROVIDER_A,
    state=call_state,
    provider_submission_status=submission_status,
    submission_process_id=os.getpid() if stage in ("NOT_SUBMITTED", "SUBMITTING") else None,
)
with store.transaction():
    agent.state = AgentState.RESERVED if call_state == CallState.RESERVED else AgentState.DIALING
    agent.current_call_id = call.id
    store.update_agent(agent)
    borrower.status = "DIALING"
    borrower.last_call_id = call.id
    store.update_borrower(borrower)
    store.save_call(call)

if stage == "ANSWERED":
    asyncio.run(EventProcessor(store).process_event(ProviderWebhookRequest(
        event_id="evt_crash_answered",
        call_id=call.id,
        provider=ProviderName.PROVIDER_A,
        event_type="ANSWERED",
    )))
os._exit(0)
"""
    environment = os.environ.copy()
    environment["SMARTDIALER_DB_PATH"] = str(database_path)
    environment["SMARTDIALER_CRASH_STAGE"] = stage

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=project_root,
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0

    restarted = MemoryStore(str(database_path))
    call = restarted.get_call(f"call_crash_{stage.lower()}")
    agent = restarted.get_agent("agt_001")
    borrower = restarted.get_borrower("bor_101")

    assert call.state == expected_state
    assert call.provider_submission_status == expected_submission
    assert agent.state == expected_agent_state
    assert agent.current_call_id == (None if stage == "NOT_SUBMITTED" else call.id)
    assert borrower.status == expected_borrower
    if stage == "SUBMITTING":
        assert "acceptance was uncertain" in call.error_reason
    if stage in ("ACCEPTED", "ANSWERED"):
        assert call.provider_submission_status == ProviderSubmissionStatus.ACCEPTED


@pytest.mark.asyncio
async def test_processed_provider_event_remains_idempotent_after_store_restart(tmp_path):
    database_path = tmp_path / "event-idempotency.sqlite3"
    store = MemoryStore(str(database_path))
    agent = store.get_available_agents()[0]
    borrower = store.get_queued_borrowers()[0]
    call = Call(
        id="call_event_restart",
        borrower_id=borrower.id,
        borrower_name=borrower.name,
        borrower_phone=borrower.phone,
        agent_id=agent.id,
        provider=ProviderName.PROVIDER_A,
        state=CallState.INITIATED,
        provider_submission_status=ProviderSubmissionStatus.ACCEPTED,
    )
    with store.transaction():
        agent.state = AgentState.DIALING
        agent.current_call_id = call.id
        store.update_agent(agent)
        borrower.status = "DIALING"
        borrower.last_call_id = call.id
        store.update_borrower(borrower)
        store.save_call(call)

    event = ProviderWebhookRequest(
        event_id="evt_restart_duplicate",
        call_id=call.id,
        provider=ProviderName.PROVIDER_A,
        event_type="RINGING",
    )
    first = await EventProcessor(store).process_event(event)
    restarted = MemoryStore(str(database_path))
    duplicate = await EventProcessor(restarted).process_event(event)

    assert first.status == "processed"
    assert duplicate.status == "ignored_duplicate"
    assert restarted.get_call(call.id).state == CallState.RINGING
