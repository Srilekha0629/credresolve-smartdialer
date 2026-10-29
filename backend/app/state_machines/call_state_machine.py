from typing import Set, Dict, Tuple
from backend.app.models.enums import CallState


class CallStateMachine:
    """
    Defines and validates legal call lifecycle transitions:
    QUEUED, RESERVED, INITIATED, RINGING, ANSWERED, CONNECTED, COMPLETED, FAILED, CANCELLED.

    Crucially, terminal states cannot transition to any active state.
    Late events such as ANSWERED or RINGING arriving after COMPLETED or CANCELLED
    are explicitly rejected.
    """

    TERMINAL_STATES: Set[CallState] = {
        CallState.COMPLETED,
        CallState.FAILED,
        CallState.CANCELLED,
    }

    ALLOWED_TRANSITIONS: Dict[CallState, Set[CallState]] = {
        CallState.QUEUED: {
            CallState.RESERVED,
            CallState.CANCELLED,
        },
        CallState.RESERVED: {
            CallState.INITIATED,
            CallState.RINGING,
            CallState.ANSWERED,
            CallState.CONNECTED,
            CallState.CANCELLED,
            CallState.FAILED,
        },
        CallState.INITIATED: {
            CallState.RINGING,
            CallState.ANSWERED,  # Some telecom networks go direct to answered
            CallState.CONNECTED,  # Direct bridge upon answer
            CallState.FAILED,
            CallState.CANCELLED,
        },
        CallState.RINGING: {
            CallState.ANSWERED,
            CallState.CONNECTED,  # Direct bridge upon answer
            CallState.FAILED,
            CallState.CANCELLED,
        },
        CallState.ANSWERED: {
            CallState.CONNECTED,
            CallState.COMPLETED,  # Short call hung up immediately
            CallState.FAILED,
        },
        CallState.CONNECTED: {
            CallState.COMPLETED,
            CallState.FAILED,
        },
        # Terminal states have NO allowed transitions
        CallState.COMPLETED: set(),
        CallState.FAILED: set(),
        CallState.CANCELLED: set(),
    }

    @classmethod
    def is_terminal(cls, state: CallState) -> bool:
        return state in cls.TERMINAL_STATES

    @classmethod
    def can_transition(cls, current_state: CallState, target_state: CallState) -> bool:
        if current_state == target_state:
            return True  # Idempotent re-affirmation
        if cls.is_terminal(current_state):
            # Terminal states CANNOT be revived by any event
            return False
        allowed = cls.ALLOWED_TRANSITIONS.get(current_state, set())
        return target_state in allowed

    @classmethod
    def validate_transition(
        cls, current_state: CallState, target_state: CallState
    ) -> Tuple[bool, str]:
        if cls.can_transition(current_state, target_state):
            return True, f"Transition from {current_state.value} to {target_state.value} is valid."
        if cls.is_terminal(current_state):
            return (
                False,
                f"Call is in terminal state {current_state.value}. Cannot transition to {target_state.value}.",
            )
        return (
            False,
            f"Illegal call transition from {current_state.value} to {target_state.value}. Allowed: {[s.value for s in cls.ALLOWED_TRANSITIONS.get(current_state, set())]}",
        )
