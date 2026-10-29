from dataclasses import dataclass
from typing import List, Tuple, Optional
from backend.app.models.enums import AgentState, CallState
from backend.app.models.agent import Agent
from backend.app.models.borrower import Borrower
from backend.app.storage.memory_store import MemoryStore


@dataclass
class SafeAllocationBatch:
    is_safe: bool
    proposed_count: int
    approved_count: int
    pairs: List[Tuple[Agent, Borrower]]
    audit_reason: str


class SafetyController:
    """
    Separate Safety Enforcement Layer.

    Mandates:
    - Validate every proposed batch of calls immediately before allocation.
    - Reject or reduce unsafe batches to strict safety limits.
    - Account for reserved, dialing, connected, and other outstanding agent-bound calls.
    - Prevent duplicate agent or borrower allocations.
    - Never allow predictive pacing or any caller to bypass safety enforcement.
    """

    def __init__(self, store: Optional[MemoryStore] = None):
        self.store = store or MemoryStore.get_instance()

    def calculate_safe_headroom(self) -> int:
        """
        Calculates how many new agent-bound calls can be safely allocated right now.
        Must account for:
        - Currently AVAILABLE agents who are unassigned.
        - Existing outstanding agent-bound calls (RESERVED, INITIATED, RINGING, ANSWERED, CONNECTED).
        """
        all_agents = self.store.get_agents()
        active_agents = [a for a in all_agents if a.state not in (AgentState.OFFLINE, AgentState.PAUSED)]
        available_agents = [
            a for a in all_agents if a.state == AgentState.AVAILABLE and a.current_call_id is None
        ]

        active_calls = self.store.get_active_calls()
        outstanding_agent_bound = [
            c
            for c in active_calls
            if c.state
            in (
                CallState.RESERVED,
                CallState.INITIATED,
                CallState.RINGING,
                CallState.ANSWERED,
                CallState.CONNECTED,
            )
        ]

        # Safe limit: Cannot have more total active calls than total available workforce
        # and cannot initiate more calls right now than there are unreserved AVAILABLE agents.
        headroom = len(available_agents)
        return max(0, headroom)

    def validate_and_filter_batch(
        self,
        proposed_count: int,
        preferred_borrower_ids: Optional[List[str]] = None,
    ) -> SafeAllocationBatch:
        """
        Enforces safety rules on a proposed batch of calls:
        1. Checks safe headroom of truly AVAILABLE agents.
        2. Filters out borrowers who already have active calls or are queued duplicates.
        3. Clamps/reduces proposed count to available safe capacity.
        4. Matches available agents to unique, queued borrowers.
        """
        # 1. Fetch current candidates
        available_agents = self.store.get_available_agents()
        queued_borrowers = self.store.get_queued_borrowers()

        # Deduplicate borrowers and ensure no borrower has an active call
        active_calls = self.store.get_active_calls()
        active_borrower_ids = {c.borrower_id for c in active_calls}
        active_agent_ids = {c.agent_id for c in active_calls if c.agent_id}

        eligible_agents = [a for a in available_agents if a.id not in active_agent_ids]
        eligible_borrowers = [b for b in queued_borrowers if b.id not in active_borrower_ids]

        if preferred_borrower_ids:
            # Order preferred borrowers first if requested
            pref_set = set(preferred_borrower_ids)
            eligible_borrowers = sorted(
                eligible_borrowers, key=lambda b: (0 if b.id in pref_set else 1)
            )

        safe_capacity = min(len(eligible_agents), len(eligible_borrowers))

        if safe_capacity == 0:
            return SafeAllocationBatch(
                is_safe=False,
                proposed_count=proposed_count,
                approved_count=0,
                pairs=[],
                audit_reason=(
                    f"Safety check rejected: 0 safe capacity. "
                    f"Available agents: {len(eligible_agents)}, Queued borrowers: {len(eligible_borrowers)}."
                ),
            )

        # 2. Determine approved count (clamp if proposed exceeds safe capacity)
        approved_count = min(proposed_count, safe_capacity)
        pairs: List[Tuple[Agent, Borrower]] = []

        for i in range(approved_count):
            pairs.append((eligible_agents[i], eligible_borrowers[i]))

        audit_msg = f"Approved {approved_count} safe calls."
        if approved_count < proposed_count:
            audit_msg = (
                f"Reduced proposed batch from {proposed_count} to {approved_count}: "
                f"safe headroom limit of {safe_capacity} enforced."
            )

        return SafeAllocationBatch(
            is_safe=True,
            proposed_count=proposed_count,
            approved_count=approved_count,
            pairs=pairs,
            audit_reason=audit_msg,
        )
