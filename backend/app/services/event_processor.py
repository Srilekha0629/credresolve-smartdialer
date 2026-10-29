from datetime import datetime
from typing import Optional
from backend.app.models.enums import (
    AgentState,
    CallState,
    ProviderEventType,
    ProviderSubmissionStatus,
)
from backend.app.models.provider_event import ProviderWebhookRequest, ProviderWebhookResponse
from backend.app.state_machines.call_state_machine import CallStateMachine
from backend.app.state_machines.agent_state_machine import AgentStateMachine
from backend.app.storage.memory_store import MemoryStore


class EventProcessor:
    """
    Idempotent Provider Event Processor.

    Key Guarantees:
    1. Idempotency: Duplicate events with the same `event_id` are safely ignored.
    2. State Machine Enforcement: Transition rules prevent invalid / corrupting state shifts.
    3. Terminal Preservation: Late events (e.g. ANSWERED) cannot revive COMPLETED / CANCELLED / FAILED calls.
    4. Synchronized Agent Lifecycle: Transitions call state and associated agent state in lockstep.
    """

    def __init__(self, store: Optional[MemoryStore] = None):
        self.store = store or MemoryStore.get_instance()

    async def process_event(self, event: ProviderWebhookRequest) -> ProviderWebhookResponse:
        async with self.store.atomic():
            # 1. Idempotency check via event_id
            if self.store.is_event_processed(event.event_id):
                call = self.store.get_call(event.call_id)
                return ProviderWebhookResponse(
                    success=True,
                    status="ignored_duplicate",
                    call_id=event.call_id,
                    current_call_state=call.state if call else None,
                    agent_id=call.agent_id if call else None,
                    message=f"Event {event.event_id} was already processed. Duplicate safely ignored.",
                )

            # 2. Lookup call
            call = self.store.get_call(event.call_id)
            if not call:
                return ProviderWebhookResponse(
                    success=False,
                    status="not_found",
                    call_id=event.call_id,
                    current_call_state=None,
                    agent_id=None,
                    message=f"Call {event.call_id} does not exist in store.",
                )

            # Map ProviderEventType to target CallState
            target_call_state = CallState(event.event_type.value)

            # 3. Check if call is already in a terminal state
            if CallStateMachine.is_terminal(call.state):
                # Critical requirement: NEVER let late events revive completed/cancelled/failed calls!
                self.store.mark_event_processed(event.event_id)
                self.store.record_event_log(event)
                return ProviderWebhookResponse(
                    success=False,
                    status="rejected_illegal_transition",
                    call_id=call.id,
                    current_call_state=call.state,
                    agent_id=call.agent_id,
                    message=(
                        f"Late event {event.event_type.value} rejected. "
                        f"Call {call.id} is already in terminal state {call.state.value}."
                    ),
                )

            # 4. Validate transition via CallStateMachine
            valid_transition, transition_msg = CallStateMachine.validate_transition(
                call.state, target_call_state
            )
            if not valid_transition:
                self.store.mark_event_processed(event.event_id)
                self.store.record_event_log(event)
                return ProviderWebhookResponse(
                    success=False,
                    status="rejected_illegal_transition",
                    call_id=call.id,
                    current_call_state=call.state,
                    agent_id=call.agent_id,
                    message=transition_msg,
                )

            # 5. Apply valid transition to Call and synchronized Agent
            now = event.timestamp or datetime.utcnow()
            call.state = target_call_state
            call.provider_submission_status = ProviderSubmissionStatus.ACCEPTED
            agent = self.store.get_agent(call.agent_id) if call.agent_id else None
            borrower = self.store.get_borrower(call.borrower_id)

            if target_call_state == CallState.INITIATED:
                call.initiated_at = call.initiated_at or now
            elif target_call_state == CallState.RINGING:
                call.ringing_at = now
            elif target_call_state == CallState.ANSWERED:
                call.answered_at = now
            if target_call_state in (
                CallState.INITIATED,
                CallState.RINGING,
                CallState.ANSWERED,
            ):
                if (
                    agent
                    and agent.current_call_id == call.id
                    and agent.state == AgentState.RESERVED
                    and AgentStateMachine.can_transition(
                        agent.state, AgentState.DIALING
                    )
                ):
                    agent.state = AgentState.DIALING
                    self.store.update_agent(agent)
            elif target_call_state == CallState.CONNECTED:
                call.connected_at = now
                if agent and agent.current_call_id == call.id and agent.state == AgentState.RESERVED:
                    agent.state = AgentState.DIALING
                if agent and AgentStateMachine.can_transition(agent.state, AgentState.CONNECTED):
                    agent.state = AgentState.CONNECTED
                    self.store.update_agent(agent)
            elif target_call_state == CallState.COMPLETED:
                call.ended_at = now
                if call.connected_at:
                    call.duration_seconds = max(0.0, (now - call.connected_at).total_seconds())
                elif call.initiated_at:
                    call.duration_seconds = max(0.0, (now - call.initiated_at).total_seconds())

                if agent:
                    agent.total_calls_handled += 1
                    agent.total_talk_time_seconds += call.duration_seconds
                    if agent.current_call_id == call.id:
                        if agent.state == AgentState.RESERVED:
                            agent.state = AgentState.DIALING
                        # Move the assigned agent to wrap-up without clearing a
                        # different call's assignment if state was inconsistent.
                        if AgentStateMachine.can_transition(
                            agent.state, AgentState.WRAP_UP
                        ):
                            agent.state = AgentState.WRAP_UP
                        agent.current_call_id = None
                    self.store.update_agent(agent)

                if borrower:
                    borrower.status = "COMPLETED"
                    self.store.update_borrower(borrower)

            elif target_call_state in (CallState.FAILED, CallState.CANCELLED):
                call.ended_at = now
                call.error_reason = event.reason or "Call ended in failure or cancellation"
                if agent and agent.current_call_id == call.id:
                    agent.current_call_id = None
                    if agent.state == AgentState.CONNECTED and AgentStateMachine.can_transition(
                        agent.state, AgentState.WRAP_UP
                    ):
                        agent.state = AgentState.WRAP_UP
                    elif AgentStateMachine.can_transition(agent.state, AgentState.AVAILABLE):
                        agent.state = AgentState.AVAILABLE
                    self.store.update_agent(agent)

                if borrower:
                    borrower.status = "FAILED" if target_call_state == CallState.FAILED else "QUEUED"
                    self.store.update_borrower(borrower)

            # Save mutated call
            self.store.save_call(call)
            self.store.mark_event_processed(event.event_id)
            self.store.record_event_log(event)

            return ProviderWebhookResponse(
                success=True,
                status="processed",
                call_id=call.id,
                current_call_state=call.state,
                agent_id=call.agent_id,
                message=f"Event {event.event_type.value} successfully processed for call {call.id}.",
            )
