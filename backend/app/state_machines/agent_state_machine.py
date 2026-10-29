from typing import Set, Dict, Tuple
from backend.app.models.enums import AgentState


class AgentStateMachine:
    """
    Defines and validates legal agent lifecycle transitions:
    OFFLINE, AVAILABLE, RESERVED, DIALING, CONNECTED, WRAP_UP, PAUSED.
    """

    ALLOWED_TRANSITIONS: Dict[AgentState, Set[AgentState]] = {
        AgentState.OFFLINE: {AgentState.AVAILABLE},
        AgentState.AVAILABLE: {
            AgentState.PAUSED,
            AgentState.OFFLINE,
            AgentState.RESERVED,
        },
        AgentState.PAUSED: {
            AgentState.AVAILABLE,
            AgentState.OFFLINE,
        },
        AgentState.RESERVED: {
            AgentState.DIALING,
            AgentState.AVAILABLE,  # If dial canceled / failed early
        },
        AgentState.DIALING: {
            AgentState.CONNECTED,
            AgentState.AVAILABLE,  # Call failed / borrower busy / no answer
            AgentState.WRAP_UP,
        },
        AgentState.CONNECTED: {
            AgentState.WRAP_UP,
        },
        AgentState.WRAP_UP: {
            AgentState.AVAILABLE,
            AgentState.PAUSED,
            AgentState.OFFLINE,
        },
    }

    @classmethod
    def can_transition(cls, current_state: AgentState, target_state: AgentState) -> bool:
        if current_state == target_state:
            return True
        allowed = cls.ALLOWED_TRANSITIONS.get(current_state, set())
        return target_state in allowed

    @classmethod
    def validate_transition(
        cls, current_state: AgentState, target_state: AgentState
    ) -> Tuple[bool, str]:
        if cls.can_transition(current_state, target_state):
            return True, f"Transition from {current_state.value} to {target_state.value} is valid."
        return (
            False,
            f"Illegal agent transition from {current_state.value} to {target_state.value}. Allowed: {[s.value for s in cls.ALLOWED_TRANSITIONS.get(current_state, set())]}",
        )
