import asyncio
import hashlib
import json
import logging
import os
import uuid
from datetime import datetime
from typing import Awaitable, Callable, List, Optional, Tuple
from backend.app.models.agent import Agent
from backend.app.models.borrower import Borrower
from backend.app.models.enums import (
    AgentState,
    CallState,
    DialerMode,
    ProviderName,
    ProviderSubmissionStatus,
)
from backend.app.models.call import Call
from backend.app.models.dialer import DialCycleResult
from backend.app.state_machines.agent_state_machine import AgentStateMachine
from backend.app.storage.memory_store import MemoryStore
from backend.app.services.safety_controller import SafetyController
from backend.app.services.predictive_pacing import PredictivePacingEngine
from backend.app.providers.provider_manager import ProviderManager

logger = logging.getLogger(__name__)

class DialRequestConflict(RuntimeError):
    """A keyed dial request cannot safely be executed again."""


class DialerOrchestrator:
    """
    Coordinates outbound dialing cycles across Progressive and Predictive modes.

    Core Invariants:
    1. Transactional atomic allocation: uses a SQLite write transaction and
       unique indexes to prevent duplicate reservations across processes.
    2. Strict safety boundary: All call proposals (whether progressive or predictive)
       MUST pass through the SafetyController.
    3. Acceptance-aware cleanup: Definitely rejected and unsubmitted calls are
       released; uncertain provider acceptance keeps the assignment reserved.
    """

    def __init__(
        self,
        store: Optional[MemoryStore] = None,
        safety_controller: Optional[SafetyController] = None,
        pacing_engine: Optional[PredictivePacingEngine] = None,
        provider_manager: Optional[ProviderManager] = None,
    ):
        self.store = store or MemoryStore.get_instance()
        self.provider_manager = provider_manager or ProviderManager.get_instance()
        self.safety_controller = safety_controller or SafetyController(self.store)
        self.pacing_engine = pacing_engine or PredictivePacingEngine(
            self.store, self.provider_manager
        )

    async def _execute_idempotent(
        self,
        idempotency_key: Optional[str],
        request_data: dict,
        operation: Callable[[], Awaitable[DialCycleResult]],
    ) -> DialCycleResult:
        if idempotency_key is None:
            return await operation()

        request_hash = hashlib.sha256(
            json.dumps(request_data, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        request = self.store.claim_dial_request(idempotency_key, request_hash)
        if request["status"] == "COMPLETED":
            return DialCycleResult.model_validate_json(request["response"])
        if request["status"] in ("FAILED", "INTERRUPTED"):
            raise DialRequestConflict(
                request.get("error")
                or "This idempotency key belongs to a request that did not complete."
            )

        if not request["claimed"]:
            deadline = asyncio.get_running_loop().time() + 30
            while asyncio.get_running_loop().time() < deadline:
                await asyncio.sleep(0.05)
                request = self.store.get_dial_request(idempotency_key)
                if request is None:
                    raise DialRequestConflict("The keyed dial request disappeared.")
                if request["status"] == "COMPLETED":
                    return DialCycleResult.model_validate_json(request["response"])
                if request["status"] in ("FAILED", "INTERRUPTED"):
                    raise DialRequestConflict(
                        request.get("error")
                        or "This idempotency key belongs to a request that did not complete."
                    )
                if not self.store._process_is_alive(request.get("process_id")):
                    request = self.store.claim_dial_request(
                        idempotency_key, request_hash
                    )
                    if request["status"] != "RUNNING":
                        raise DialRequestConflict(
                            request.get("error") or "The keyed request was interrupted."
                        )
            raise DialRequestConflict(
                "A request with this idempotency key is still in progress."
            )

        try:
            result = await operation()
            self.store.complete_dial_request(
                idempotency_key, result.model_dump_json()
            )
            return result
        except BaseException as exc:
            self.store.fail_dial_request(
                idempotency_key, f"{type(exc).__name__}: {exc}"
            )
            raise

    async def _dispatch_reserved_call(self, call: Call) -> bool:
        async with self.store.lock:
            with self.store.transaction():
                current_call = self.store.get_call(call.id)
                if (
                    current_call is None
                    or current_call.state != CallState.RESERVED
                    or current_call.provider_submission_status
                    != ProviderSubmissionStatus.NOT_SUBMITTED
                ):
                    return False
                agent = (
                    self.store.get_agent(current_call.agent_id)
                    if current_call.agent_id
                    else None
                )
                if (
                    agent is None
                    or agent.current_call_id != current_call.id
                    or agent.state != AgentState.RESERVED
                ):
                    self._fail_call_locked(
                        current_call, "Agent reservation was lost before provider submission."
                    )
                    return False
                current_call.provider_submission_status = (
                    ProviderSubmissionStatus.SUBMITTING
                )
                current_call.submission_process_id = os.getpid()
                self.store.save_call(current_call)

        try:
            success, used_provider, status, meta, _ = (
                await self.provider_manager.initiate_call_with_fallback(
                    call.id, call.borrower_phone
                )
            )
            acceptance_status = (
                meta.get("acceptance_status")
                if isinstance(meta, dict)
                else None
            )
        except asyncio.CancelledError:
            await self._mark_acceptance_unknown(
                call, "Provider setup task was cancelled; acceptance is unknown."
            )
            raise
        except Exception as exc:
            logger.exception("Provider setup failed unexpectedly for call %s", call.id)
            success = False
            used_provider = call.provider
            status = f"Provider setup raised {type(exc).__name__}: {exc}"
            acceptance_status = "UNKNOWN"

        async with self.store.lock:
            with self.store.transaction():
                current_call = self.store.get_call(call.id)
                if current_call is None:
                    logger.error("Reserved call %s disappeared during provider setup", call.id)
                    return False

                current_agent = (
                    self.store.get_agent(current_call.agent_id)
                    if current_call.agent_id
                    else None
                )
                reservation_is_current = (
                    current_agent is not None
                    and current_agent.current_call_id == current_call.id
                    and current_agent.state == AgentState.RESERVED
                )

                if success and reservation_is_current:
                    current_call.state = CallState.INITIATED
                    current_call.provider = used_provider
                    current_call.provider_submission_status = (
                        ProviderSubmissionStatus.ACCEPTED
                    )
                    current_call.submission_process_id = None
                    current_call.initiated_at = datetime.utcnow()
                    self.store.save_call(current_call)
                    current_agent.state = AgentState.DIALING
                    self.store.update_agent(current_agent)
                    return True

                if success:
                    status = (
                        "Provider accepted the call but the agent reservation changed; "
                        "the call remains reserved for reconciliation."
                    )
                    acceptance_status = "UNKNOWN"
                    logger.error("Reservation lost for call %s during provider setup", call.id)

                if acceptance_status == "UNKNOWN":
                    current_call.provider_submission_status = ProviderSubmissionStatus.UNKNOWN
                    current_call.error_reason = status
                    self.store.save_call(current_call)
                    return False

                current_call.provider_submission_status = ProviderSubmissionStatus.REJECTED
                self._fail_call_locked(current_call, status)
                return False

    async def _mark_acceptance_unknown(self, call: Call, reason: str) -> None:
        async with self.store.lock:
            with self.store.transaction():
                current_call = self.store.get_call(call.id)
                if (
                    current_call is not None
                    and current_call.state == CallState.RESERVED
                    and current_call.provider_submission_status
                    == ProviderSubmissionStatus.SUBMITTING
                ):
                    current_call.provider_submission_status = (
                        ProviderSubmissionStatus.UNKNOWN
                    )
                    current_call.error_reason = reason
                    self.store.save_call(current_call)

    async def _fail_unsubmitted_call(self, call: Call, reason: str) -> None:
        async with self.store.lock:
            with self.store.transaction():
                current_call = self.store.get_call(call.id)
                if (
                    current_call is not None
                    and current_call.state == CallState.RESERVED
                    and current_call.provider_submission_status
                    == ProviderSubmissionStatus.NOT_SUBMITTED
                ):
                    current_call.provider_submission_status = (
                        ProviderSubmissionStatus.REJECTED
                    )
                    self._fail_call_locked(current_call, reason)

    async def _dispatch_reserved_calls(self, calls: List[Call]) -> List[str]:
        initiated_call_ids: List[str] = []
        try:
            for call in calls:
                if await self._dispatch_reserved_call(call):
                    initiated_call_ids.append(call.id)
        except asyncio.CancelledError:
            for call in calls:
                await self._mark_acceptance_unknown(
                    call,
                    "Dialer cycle was cancelled after provider submission may have begun.",
                )
                await self._fail_unsubmitted_call(
                    call,
                    "Dialer cycle was cancelled before provider submission began.",
                )
            raise
        return initiated_call_ids

    def _fail_call_locked(self, call: Call, reason: str) -> None:
        call.state = CallState.FAILED
        call.error_reason = reason
        call.ended_at = datetime.utcnow()
        self.store.save_call(call)

        agent = self.store.get_agent(call.agent_id) if call.agent_id else None
        if agent and agent.current_call_id == call.id:
            agent.current_call_id = None
            if AgentStateMachine.can_transition(agent.state, AgentState.AVAILABLE):
                agent.state = AgentState.AVAILABLE
            self.store.update_agent(agent)

        borrower = self.store.get_borrower(call.borrower_id)
        if borrower and borrower.last_call_id == call.id:
            borrower.status = "QUEUED"
            self.store.update_borrower(borrower)

    async def run_progressive_cycle(
        self,
        max_calls: Optional[int] = None,
        idempotency_key: Optional[str] = None,
    ) -> DialCycleResult:
        return await self._execute_idempotent(
            idempotency_key,
            {"mode": "PROGRESSIVE", "max_calls": max_calls},
            lambda: self._run_progressive_cycle(max_calls),
        )

    async def _run_progressive_cycle(
        self, max_calls: Optional[int] = None
    ) -> DialCycleResult:
        """
        Executes a 1:1 progressive dialing cycle:
        - Only available agents are matched 1:1 with queued borrowers.
        - Concurrency lock ensures atomic reservation.
        """
        async with self.store.lock:
            with self.store.transaction():
                available_agents = self.store.get_available_agents()
                proposed_count = len(available_agents)
                if max_calls is not None:
                    proposed_count = min(proposed_count, max_calls)

                batch = self.safety_controller.validate_and_filter_batch(proposed_count)

                if not batch.is_safe or batch.approved_count == 0:
                    return DialCycleResult(
                        mode=DialerMode.PROGRESSIVE,
                        available_agents_before=len(available_agents),
                        proposed_calls=proposed_count,
                        safe_approved_calls=0,
                        calls_initiated=0,
                        call_ids=[],
                        notes=batch.audit_reason,
                    )

                created_calls = self._reserve_batch(batch.pairs)

        # Provider dispatch phase (lock is released so async I/O doesn't block store)
        initiated_call_ids = await self._dispatch_reserved_calls(created_calls)

        return DialCycleResult(
            mode=DialerMode.PROGRESSIVE,
            available_agents_before=len(available_agents),
            proposed_calls=proposed_count,
            safe_approved_calls=batch.approved_count,
            calls_initiated=len(initiated_call_ids),
            call_ids=initiated_call_ids,
            notes=f"{batch.audit_reason} Placed {len(initiated_call_ids)} outbound calls.",
        )

    def _reserve_batch(
        self, pairs: List[Tuple[Agent, Borrower]]
    ) -> List[Call]:
        created_calls: List[Call] = []
        for agent, borrower in pairs:
            call_id = f"call_{uuid.uuid4().hex[:10]}"
            call = Call(
                id=call_id,
                borrower_id=borrower.id,
                borrower_name=borrower.name,
                borrower_phone=borrower.phone,
                agent_id=agent.id,
                provider=self.provider_manager.primary_provider_name,
                state=CallState.RESERVED,
                submission_process_id=os.getpid(),
                created_at=datetime.utcnow(),
            )
            self.store.save_call(call)
            agent.state = AgentState.RESERVED
            agent.current_call_id = call_id
            self.store.update_agent(agent)
            borrower.status = "DIALING"
            borrower.last_call_id = call_id
            borrower.calls_attempted += 1
            self.store.update_borrower(borrower)
            created_calls.append(call)
        return created_calls

    async def run_predictive_cycle(
        self,
        target_answer_rate: Optional[float] = None,
        max_pacing_ratio: float = 2.0,
        allow_fallback: bool = True,
        idempotency_key: Optional[str] = None,
    ) -> DialCycleResult:
        return await self._execute_idempotent(
            idempotency_key,
            {
                "mode": "PREDICTIVE",
                "target_answer_rate": target_answer_rate,
                "max_pacing_ratio": max_pacing_ratio,
                "allow_fallback": allow_fallback,
            },
            lambda: self._run_predictive_cycle(
                target_answer_rate, max_pacing_ratio, allow_fallback
            ),
        )

    async def _run_predictive_cycle(
        self,
        target_answer_rate: Optional[float] = None,
        max_pacing_ratio: float = 2.0,
        allow_fallback: bool = True,
    ) -> DialCycleResult:
        """
        Executes a predictive dialing cycle:
        1. Pacing engine estimates suggested calls based on metrics.
        2. Suggested batch is submitted to SafetyController for validation.
        3. SafetyController clamps or rejects any unsafe excess.
        4. Approved calls are atomically reserved and dispatched.
        """
        suggestion = self.pacing_engine.suggest_call_volume(
            override_answer_rate=target_answer_rate,
            max_pacing_ratio=max_pacing_ratio,
            allow_fallback=allow_fallback,
        )

        actual_mode = (
            DialerMode.PROGRESSIVE
            if suggestion.fallback_to_progressive
            else DialerMode.PREDICTIVE
        )
        async with self.store.lock:
            with self.store.transaction():
                available_agents = self.store.get_available_agents()
                proposed_count = suggestion.suggested_calls

                # CRITICAL SAFETY BOUNDARY: Both modes pass through the safety gate.
                batch = self.safety_controller.validate_and_filter_batch(proposed_count)

                if not batch.is_safe or batch.approved_count == 0:
                    return DialCycleResult(
                        mode=actual_mode,
                        available_agents_before=len(available_agents),
                        proposed_calls=proposed_count,
                        safe_approved_calls=0,
                        calls_initiated=0,
                        call_ids=[],
                        notes=f"{suggestion.reason} | {batch.audit_reason}",
                    )

                created_calls = self._reserve_batch(batch.pairs)

        # Provider dispatch phase
        initiated_call_ids = await self._dispatch_reserved_calls(created_calls)

        return DialCycleResult(
            mode=actual_mode,
            available_agents_before=len(available_agents),
            proposed_calls=proposed_count,
            safe_approved_calls=batch.approved_count,
            calls_initiated=len(initiated_call_ids),
            call_ids=initiated_call_ids,
            notes=(
                f"{suggestion.reason} | {batch.audit_reason} "
                f"Placed {len(initiated_call_ids)} calls."
            ),
        )
