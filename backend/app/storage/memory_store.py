import asyncio
import json
import os
import sqlite3
import threading
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Set

from backend.app.models.agent import Agent
from backend.app.models.borrower import Borrower
from backend.app.models.call import Call
from backend.app.models.enums import (
    AgentState,
    CallState,
    ProviderSubmissionStatus,
)
from backend.app.models.provider_event import ProviderWebhookRequest


class MemoryStore:
    """SQLite-backed state store retaining the existing in-memory store API.

    A short SQLite ``BEGIN IMMEDIATE`` transaction serializes reservation
    decisions across store instances and Python processes. Provider I/O is
    deliberately performed outside that transaction. Calls left in SUBMITTING
    at startup are marked UNKNOWN and retain their agent reservation; they are
    never automatically retried because provider acceptance cannot be inferred.
    """

    _instance: Optional["MemoryStore"] = None
    _instance_lock = threading.Lock()

    def __init__(self, database_path: Optional[str] = None):
        configured_path = database_path or os.environ.get("SMARTDIALER_DB_PATH")
        self.database_path = Path(
            configured_path
            or (Path.home() / ".credresolve-smartdialer" / "smartdialer.sqlite3")
        ).expanduser().resolve()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)

        self._async_lock = asyncio.Lock()
        self._sync_lock = threading.RLock()
        self._transaction_depth = 0

        self.agents: Dict[str, Agent] = {}
        self.borrowers: Dict[str, Borrower] = {}
        self.calls: Dict[str, Call] = {}
        self.seen_event_ids: Set[str] = set()
        self.event_log: List[ProviderWebhookRequest] = []
        self.dial_requests: Dict[str, dict] = {}

        self._initialize_schema()
        with self.transaction():
            if not self.agents:
                self.seed_defaults()
        self._recover_after_restart()

    @classmethod
    def get_instance(cls) -> "MemoryStore":
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @property
    def lock(self) -> asyncio.Lock:
        return self._async_lock

    @asynccontextmanager
    async def atomic(self):
        """Serialize async work and its persistent state changes as one transaction."""
        async with self._async_lock:
            with self.transaction():
                yield

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            str(self.database_path),
            timeout=30.0,
            isolation_level=None,
        )
        connection.execute("PRAGMA busy_timeout = 30000")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = FULL")
        return connection

    def _initialize_schema(self) -> None:
        connection = self._connect()
        try:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS agents (
                    id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS borrowers (
                    id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS calls (
                    id TEXT PRIMARY KEY,
                    agent_id TEXT,
                    borrower_id TEXT NOT NULL,
                    state TEXT NOT NULL,
                    submission_status TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS one_active_call_per_agent
                    ON calls(agent_id)
                    WHERE agent_id IS NOT NULL
                      AND state NOT IN ('COMPLETED', 'FAILED', 'CANCELLED');
                CREATE UNIQUE INDEX IF NOT EXISTS one_active_call_per_borrower
                    ON calls(borrower_id)
                    WHERE state NOT IN ('COMPLETED', 'FAILED', 'CANCELLED');
                CREATE TABLE IF NOT EXISTS processed_events (
                    event_id TEXT PRIMARY KEY
                );
                CREATE TABLE IF NOT EXISTS event_log (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS dial_requests (
                    idempotency_key TEXT PRIMARY KEY,
                    payload TEXT NOT NULL
                );
                """
            )
        finally:
            connection.close()

    def _load_state(self, connection: Optional[sqlite3.Connection] = None) -> None:
        owns_connection = connection is None
        connection = connection or self._connect()
        try:
            self.agents = {
                row[0]: Agent.model_validate_json(row[1])
                for row in connection.execute("SELECT id, payload FROM agents")
            }
            self.borrowers = {
                row[0]: Borrower.model_validate_json(row[1])
                for row in connection.execute("SELECT id, payload FROM borrowers")
            }
            self.calls = {
                row[0]: Call.model_validate_json(row[1])
                for row in connection.execute("SELECT id, payload FROM calls")
            }
            self.seen_event_ids = {
                row[0] for row in connection.execute("SELECT event_id FROM processed_events")
            }
            self.event_log = [
                ProviderWebhookRequest.model_validate_json(row[0])
                for row in connection.execute(
                    "SELECT payload FROM event_log ORDER BY sequence"
                )
            ]
            self.dial_requests = {
                row[0]: json.loads(row[1])
                for row in connection.execute(
                    "SELECT idempotency_key, payload FROM dial_requests"
                )
            }
        finally:
            if owns_connection:
                connection.close()

    def _refresh_if_needed(self) -> None:
        if self._transaction_depth:
            return
        with self._sync_lock:
            if not self._transaction_depth:
                self._load_state()

    def _write_snapshot(self, connection: sqlite3.Connection) -> None:
        connection.execute("DELETE FROM agents")
        connection.executemany(
            "INSERT INTO agents(id, payload) VALUES (?, ?)",
            [
                (agent.id, agent.model_dump_json())
                for agent in self.agents.values()
            ],
        )
        connection.execute("DELETE FROM borrowers")
        connection.executemany(
            "INSERT INTO borrowers(id, payload) VALUES (?, ?)",
            [
                (borrower.id, borrower.model_dump_json())
                for borrower in self.borrowers.values()
            ],
        )
        connection.execute("DELETE FROM calls")
        connection.executemany(
            """
            INSERT INTO calls(id, agent_id, borrower_id, state, submission_status, payload)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    call.id,
                    call.agent_id,
                    call.borrower_id,
                    call.state.value,
                    call.provider_submission_status.value,
                    call.model_dump_json(),
                )
                for call in self.calls.values()
            ],
        )
        connection.execute("DELETE FROM processed_events")
        connection.executemany(
            "INSERT INTO processed_events(event_id) VALUES (?)",
            [(event_id,) for event_id in self.seen_event_ids],
        )
        connection.execute("DELETE FROM event_log")
        connection.executemany(
            "INSERT INTO event_log(payload) VALUES (?)",
            [(event.model_dump_json(),) for event in self.event_log],
        )
        connection.execute("DELETE FROM dial_requests")
        connection.executemany(
            "INSERT INTO dial_requests(idempotency_key, payload) VALUES (?, ?)",
            [
                (key, json.dumps(request, separators=(",", ":"), sort_keys=True))
                for key, request in self.dial_requests.items()
            ],
        )

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """Reload and atomically update the full state under SQLite's write lock."""
        with self._sync_lock:
            if self._transaction_depth:
                self._transaction_depth += 1
                try:
                    yield
                finally:
                    self._transaction_depth -= 1
                return

            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                self._load_state(connection)
                self._transaction_depth = 1
                yield
                self._write_snapshot(connection)
                connection.commit()
            except BaseException:
                connection.rollback()
                self._load_state(connection)
                raise
            finally:
                self._transaction_depth = 0
                connection.close()

    def _recover_after_restart(self) -> None:
        with self.transaction():
            for call in list(self.calls.values()):
                if call.state == CallState.RESERVED:
                    owner_alive = (
                        call.submission_process_id is not None
                        and self._process_is_alive(call.submission_process_id)
                    )
                    if not owner_alive and (
                        call.provider_submission_status
                        == ProviderSubmissionStatus.NOT_SUBMITTED
                    ):
                        call.state = CallState.FAILED
                        call.error_reason = (
                            "Backend restarted before provider submission; call was not retried."
                        )
                        call.ended_at = datetime.utcnow()
                        self.calls[call.id] = call
                        self._release_failed_reservation(call, borrower_queued=True)
                    elif not owner_alive and (
                        call.provider_submission_status
                        == ProviderSubmissionStatus.SUBMITTING
                    ):
                        call.provider_submission_status = ProviderSubmissionStatus.UNKNOWN
                        call.error_reason = (
                            "Backend restarted while provider acceptance was uncertain; "
                            "manual/provider reconciliation is required."
                        )
                        self.calls[call.id] = call

            for key, request in self.dial_requests.items():
                if (
                    request.get("status") == "RUNNING"
                    and not self._process_is_alive(request.get("process_id"))
                ):
                    request["status"] = "INTERRUPTED"
                    request["error"] = (
                        "The dial request owner exited before saving a result. "
                        "Do not retry with this key; inspect any reserved calls first."
                    )

            self._synchronize_recovered_state()

    def _synchronize_recovered_state(self) -> None:
        for call in self.calls.values():
            if call.state in (
                CallState.COMPLETED,
                CallState.FAILED,
                CallState.CANCELLED,
            ):
                agent = self.agents.get(call.agent_id) if call.agent_id else None
                if agent and agent.current_call_id == call.id:
                    agent.current_call_id = None
                    if call.state == CallState.COMPLETED:
                        if agent.state == AgentState.RESERVED:
                            agent.state = AgentState.DIALING
                        if agent.state in (AgentState.DIALING, AgentState.CONNECTED):
                            agent.state = AgentState.WRAP_UP
                    elif agent.state == AgentState.CONNECTED:
                        agent.state = AgentState.WRAP_UP
                    elif agent.state in (AgentState.RESERVED, AgentState.DIALING):
                        agent.state = AgentState.AVAILABLE
                    self.agents[agent.id] = agent

                borrower = self.borrowers.get(call.borrower_id)
                if borrower and borrower.last_call_id == call.id:
                    if call.state == CallState.COMPLETED:
                        borrower.status = "COMPLETED"
                    elif call.state == CallState.FAILED and borrower.status == "DIALING":
                        borrower.status = "FAILED"
                    elif (
                        call.state == CallState.CANCELLED
                        and borrower.status == "DIALING"
                    ):
                        borrower.status = "QUEUED"
                    self.borrowers[borrower.id] = borrower

        for call in self.calls.values():
            if call.state in (
                CallState.COMPLETED,
                CallState.FAILED,
                CallState.CANCELLED,
            ):
                continue
            agent = self.agents.get(call.agent_id) if call.agent_id else None
            if agent:
                agent.current_call_id = call.id
                if call.state == CallState.RESERVED:
                    agent.state = AgentState.RESERVED
                elif call.state == CallState.CONNECTED:
                    agent.state = AgentState.CONNECTED
                else:
                    agent.state = AgentState.DIALING
                self.agents[agent.id] = agent
            borrower = self.borrowers.get(call.borrower_id)
            if borrower:
                borrower.status = "DIALING"
                borrower.last_call_id = call.id
                self.borrowers[borrower.id] = borrower

    @staticmethod
    def _process_is_alive(process_id: Optional[int]) -> bool:
        if process_id is None:
            return False
        try:
            os.kill(process_id, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except OSError:
            return False
        return True

    def _release_failed_reservation(self, call: Call, borrower_queued: bool) -> None:
        agent = self.agents.get(call.agent_id) if call.agent_id else None
        if agent and agent.current_call_id == call.id:
            agent.current_call_id = None
            if agent.state in (AgentState.RESERVED, AgentState.DIALING):
                agent.state = AgentState.AVAILABLE
            self.agents[agent.id] = agent

        borrower = self.borrowers.get(call.borrower_id)
        if borrower and borrower.last_call_id == call.id and borrower_queued:
            borrower.status = "QUEUED"
            self.borrowers[borrower.id] = borrower

    def seed_defaults(self):
        """Reset the persistent store to deterministic demonstration data."""
        with self.transaction():
            self.agents.clear()
            self.borrowers.clear()
            self.calls.clear()
            self.seen_event_ids.clear()
            self.event_log.clear()

            initial_agents = [
                Agent(id="agt_001", name="Sarah Jenkins", state=AgentState.AVAILABLE),
                Agent(id="agt_002", name="Michael Chang", state=AgentState.AVAILABLE),
                Agent(id="agt_003", name="Priya Sharma", state=AgentState.AVAILABLE),
                Agent(id="agt_004", name="David Rodriguez", state=AgentState.PAUSED),
                Agent(id="agt_005", name="Amina Yusuf", state=AgentState.OFFLINE),
            ]
            self.agents = {agent.id: agent for agent in initial_agents}

            initial_borrowers = [
                Borrower(id="bor_101", name="Alice Walker", phone="+15550101", debt_amount=1450.00, status="QUEUED"),
                Borrower(id="bor_102", name="Bob Martin", phone="+15550102", debt_amount=2300.50, status="QUEUED"),
                Borrower(id="bor_103", name="Charlie Brown", phone="+15550103", debt_amount=890.00, status="QUEUED"),
                Borrower(id="bor_104", name="Diana Prince", phone="+15550104", debt_amount=4120.75, status="QUEUED"),
                Borrower(id="bor_105", name="Evan Wright", phone="+15550105", debt_amount=730.00, status="QUEUED"),
                Borrower(id="bor_106", name="Fiona Gallagher", phone="+15550106", debt_amount=3150.20, status="QUEUED"),
                Borrower(id="bor_107", name="George Clark", phone="+15550107", debt_amount=1950.00, status="QUEUED"),
                Borrower(id="bor_108", name="Hannah Abbott", phone="+15550108", debt_amount=520.00, status="QUEUED"),
                Borrower(id="bor_109", name="Ian Malcolm", phone="+15550109", debt_amount=6700.00, status="QUEUED"),
                Borrower(id="bor_110", name="Julia Roberts", phone="+15550110", debt_amount=1200.00, status="QUEUED"),
                Borrower(id="bor_111", name="Kevin Bacon", phone="+15550111", debt_amount=3400.00, status="QUEUED"),
                Borrower(id="bor_112", name="Laura Croft", phone="+15550112", debt_amount=4800.00, status="QUEUED"),
            ]
            self.borrowers = {borrower.id: borrower for borrower in initial_borrowers}

    def get_agents(self) -> List[Agent]:
        self._refresh_if_needed()
        with self._sync_lock:
            return [agent.model_copy() for agent in self.agents.values()]

    def get_agent(self, agent_id: str) -> Optional[Agent]:
        self._refresh_if_needed()
        with self._sync_lock:
            agent = self.agents.get(agent_id)
            return agent.model_copy() if agent else None

    def get_available_agents(self) -> List[Agent]:
        self._refresh_if_needed()
        with self._sync_lock:
            return [
                agent.model_copy()
                for agent in self.agents.values()
                if agent.state == AgentState.AVAILABLE and agent.current_call_id is None
            ]

    def update_agent(self, agent: Agent) -> Agent:
        if not self._transaction_depth:
            with self.transaction():
                return self.update_agent(agent)
        with self._sync_lock:
            agent.updated_at = datetime.utcnow()
            self.agents[agent.id] = agent
            return agent.model_copy()

    def get_borrowers(self) -> List[Borrower]:
        self._refresh_if_needed()
        with self._sync_lock:
            return [borrower.model_copy() for borrower in self.borrowers.values()]

    def get_borrower(self, borrower_id: str) -> Optional[Borrower]:
        self._refresh_if_needed()
        with self._sync_lock:
            borrower = self.borrowers.get(borrower_id)
            return borrower.model_copy() if borrower else None

    def get_queued_borrowers(self) -> List[Borrower]:
        self._refresh_if_needed()
        with self._sync_lock:
            active_borrower_ids = {
                call.borrower_id
                for call in self.calls.values()
                if call.state
                not in (CallState.COMPLETED, CallState.FAILED, CallState.CANCELLED)
            }
            return [
                borrower.model_copy()
                for borrower in self.borrowers.values()
                if borrower.status == "QUEUED" and borrower.id not in active_borrower_ids
            ]

    def update_borrower(self, borrower: Borrower) -> Borrower:
        if not self._transaction_depth:
            with self.transaction():
                return self.update_borrower(borrower)
        with self._sync_lock:
            borrower.updated_at = datetime.utcnow()
            self.borrowers[borrower.id] = borrower
            return borrower.model_copy()

    def get_calls(self) -> List[Call]:
        self._refresh_if_needed()
        with self._sync_lock:
            return sorted(
                [call.model_copy() for call in self.calls.values()],
                key=lambda call: call.created_at,
                reverse=True,
            )

    def get_call(self, call_id: str) -> Optional[Call]:
        self._refresh_if_needed()
        with self._sync_lock:
            call = self.calls.get(call_id)
            return call.model_copy() if call else None

    def save_call(self, call: Call) -> Call:
        if not self._transaction_depth:
            with self.transaction():
                return self.save_call(call)
        with self._sync_lock:
            self.calls[call.id] = call
            return call.model_copy()

    def get_active_calls(self) -> List[Call]:
        self._refresh_if_needed()
        with self._sync_lock:
            return [
                call.model_copy()
                for call in self.calls.values()
                if call.state
                not in (CallState.COMPLETED, CallState.FAILED, CallState.CANCELLED)
            ]

    def claim_dial_request(self, idempotency_key: str, request_hash: str) -> dict:
        with self.transaction():
            request = self.dial_requests.get(idempotency_key)
            if request is not None:
                if request["request_hash"] != request_hash:
                    raise ValueError(
                        "Idempotency-Key was already used with a different dial request."
                    )
                if (
                    request["status"] == "RUNNING"
                    and not self._process_is_alive(request.get("process_id"))
                ):
                    request["status"] = "INTERRUPTED"
                    request["error"] = (
                        "The dial request owner exited before saving a result. "
                        "Inspect persisted calls before starting a new request."
                    )
                return {"claimed": False, **request}

            request = {
                "request_hash": request_hash,
                "status": "RUNNING",
                "process_id": os.getpid(),
                "response": None,
                "error": None,
            }
            self.dial_requests[idempotency_key] = request
            return {"claimed": True, **request}

    def get_dial_request(self, idempotency_key: str) -> Optional[dict]:
        self._refresh_if_needed()
        with self._sync_lock:
            request = self.dial_requests.get(idempotency_key)
            return dict(request) if request is not None else None

    def complete_dial_request(self, idempotency_key: str, response: str) -> None:
        with self.transaction():
            request = self.dial_requests.get(idempotency_key)
            if request is None or request["status"] != "RUNNING":
                raise RuntimeError("Cannot complete a dial request that is not running.")
            request["status"] = "COMPLETED"
            request["response"] = response
            request["process_id"] = None

    def fail_dial_request(self, idempotency_key: str, error: str) -> None:
        with self.transaction():
            request = self.dial_requests.get(idempotency_key)
            if request is not None and request["status"] == "RUNNING":
                request["status"] = "FAILED"
                request["error"] = error
                request["process_id"] = None

    def is_event_processed(self, event_id: str) -> bool:
        self._refresh_if_needed()
        with self._sync_lock:
            return event_id in self.seen_event_ids

    def mark_event_processed(self, event_id: str):
        if not self._transaction_depth:
            with self.transaction():
                self.mark_event_processed(event_id)
                return
        with self._sync_lock:
            self.seen_event_ids.add(event_id)

    def record_event_log(self, event: ProviderWebhookRequest):
        if not self._transaction_depth:
            with self.transaction():
                self.record_event_log(event)
                return
        with self._sync_lock:
            self.event_log.append(event)
