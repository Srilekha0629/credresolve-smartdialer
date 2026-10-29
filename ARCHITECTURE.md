# SmartDialer Architecture & System Design

SmartDialer is a high-concurrency, resilience-oriented outbound progressive and predictive dialing engine designed for debt recovery contact centers. This document details its component topology, safety guarantees, concurrency model, and failure handling mechanisms.

---

## 1. System Topology & Component Overview

```
                      +---------------------------------------+
                      |         React / Vite Dashboard        |
                      +---------------------------------------+
                                          |
                                          | REST API (HTTP/JSON)
                                          v
                      +---------------------------------------+
                      |        FastAPI REST Application       |
                      |  - /dialer/progressive/run            |
                      |  - /dialer/predictive/run             |
                      |  - /events/provider                   |
                      |  - /metrics, /agents, /calls          |
                      +---------------------------------------+
                               /                     \
                              /                       \
                             v                         v
              +--------------------------+    +--------------------------+
              |    Progressive Dialer    |    | Predictive Pacing Engine |
              |  - 1:1 Agent-Call Ratio  |    |  - Answer Rate Estimator |
              |  - Safe Agent Bound      |    |  - Overdial Suggestion   |
              +--------------------------+    +--------------------------+
                             \                         /
                              \                       /
                     (Proposes Batch)       (Proposes Batch)
                                \                   /
                                 v                 v
                      +---------------------------------------+
                      |           SAFETY CONTROLLER           |
                      |  - Computes Safe Real-Time Headroom   |
                      |  - Clamps or Rejects Unsafe Batches   |
                      |  - Prevents Duplicate Allocations     |
                      +---------------------------------------+
                                          |
                        (Approved Pairs | Lock Acquired)
                                          v
                      +---------------------------------------+
                      |      SQLite Durable State Store       |
                      |  - BEGIN IMMEDIATE transactions       |
                      |  - Unique active agent/borrower calls |
                      |  - Agent & Call State Machines        |
                      |  - Persistent event IDs and event log |
                      +---------------------------------------+
                                          |
                             (Dispatch Approved Calls)
                                          v
                      +---------------------------------------+
                      |           Provider Manager            |
                      |  - Primary Route Selection            |
                      |  - Consecutive-Failure Health Status |
                      |  - Automated Carrier Fallback         |
                      +---------------------------------------+
                               /                     \
                              v                       v
               +---------------------------+   +---------------------------+
               |        Provider A         |   |        Provider B         |
               | - High Reliability Tier 1 |   | - Flaky Fault Injection   |
               | - Fast Response           |   | - Setup Timeouts/Rejection|
               +---------------------------+   +---------------------------+
```

---

## 2. The Strict Safety Boundary

A non-negotiable architectural invariant of SmartDialer is the **Safety Boundary**.

### Principle of Separation
- **The Pacing Engine suggests; the Safety Controller decides.**
- Under no circumstance is the Predictive Pacing Engine allowed to reserve an agent, create a call, or contact a telecom carrier directly.
- Both Progressive and Predictive dialers must submit their proposed batches to `SafetyController.validate_and_filter_batch()`.

### Safety Validation Checklist
Before any call is initiated, the Safety Controller enforces:
1. **Safe Agent Headroom**:
   $$\text{Safe Headroom} = \text{Agents in AVAILABLE with no active call}$$
   Proposed calls exceeding this headroom are strictly **clamped or rejected**.
2. **Duplicate Borrower Prevention**:
   No borrower who currently has an in-flight call (`RESERVED`, `INITIATED`, `RINGING`, `ANSWERED`, `CONNECTED`) can be allocated.
3. **Duplicate Agent Prevention**:
   No agent can be assigned to more than one active call at any time.

---

## 3. Concurrency Protection & Limitations

### Transactional Reservation Model
The application coordinates changes via:
1. **`asyncio.Lock` and `threading.RLock`**: Serialize local async work and in-process state access.
2. **SQLite `BEGIN IMMEDIATE`**: Reloads the authoritative state only after acquiring the database write lock, then reserves calls and updates agent/borrower state in one transaction.
3. **Unique partial indexes**: Enforce at most one active call per agent and borrower at the database layer.
4. **Provider I/O outside transactions**: Each call is marked `SUBMITTING` durably before provider dispatch; network waits do not hold the reservation transaction open.

The two-process concurrency test exercises this same-file transaction guarantee.
It is a same-host SQLite guarantee only: the database must be on a local
filesystem. Multi-host deployment requires a server database/queue design;
the prototype does not claim distributed coordination.

---

## 4. Telecom Event Correctness & Resilience

### Idempotent Event Ingestion
Every webhook arriving at `POST /events/provider` contains an `event_id`.
- The `EventProcessor` maintains a persistent set of processed event IDs.
- If an event arrives with an ID that has already been seen, it returns `status: "ignored_duplicate"` with HTTP 200, without applying state mutations or duplicating counters.

### Idempotent Dial Requests
Progressive and predictive endpoints accept an optional `Idempotency-Key`
header. The key, normalized request fingerprint, status, and completed response
are persisted transactionally. A matching retry returns the saved response;
reusing a key with different parameters returns HTTP 409. A concurrent retry
waits for the first request to finish and cannot reserve a second batch. If the
owner process exits before completion, the key is marked interrupted and must
not be replayed; inspect reservations and issue a new key only after recovery.
The simulation reset clears demo entities but retains this idempotency ledger.

### Terminal State Locking
Telecom carriers occasionally deliver webhooks out of order or with significant latency.
- If a call has reached `COMPLETED`, `FAILED`, or `CANCELLED`, its state is immutable.
- A delayed `ANSWERED` or `RINGING` event arriving after termination is rejected (`status: "rejected_illegal_transition"`) and will never revive the call or trap an agent.

### Carrier Outage & Fallback Policy
The `ProviderManager` monitors consecutive failures:
- A definite Provider B rejection, unhealthy state, or manual outage can reroute to Provider A.
- A timeout or exception after submission has uncertain acceptance. The call stays `RESERVED` with submission status `UNKNOWN`; automatic retry is forbidden to avoid creating a duplicate call.
- If all providers fail, the call is marked `FAILED` with an audit error reason, and the reserved agent is immediately released back to `AVAILABLE`.

---

## 5. Worker-Crash Recovery & State Durability

### Durable Dispatch and Recovery
- Agents, borrowers, calls, and processed provider event IDs are persisted in SQLite. `SMARTDIALER_DB_PATH` selects the local database; by default it is under the user's home directory.
- A reservation is committed before the provider call. If the owner process exits before provider submission (`NOT_SUBMITTED`), startup safely marks the call `FAILED` and releases the borrower and agent.
- A dead process that left `SUBMITTING` is ambiguous: startup changes it to `UNKNOWN`, retains the agent/borrower reservation, and never retries automatically. A provider webhook can still reconcile it; manual provider reconciliation is needed if no webhook arrives.
- A durably accepted `INITIATED` call remains in that state and assigned to its agent after abrupt process exit. The abrupt-exit test verifies this path.
- After an `ANSWERED` callback, restart keeps the call `ANSWERED`, its agent assigned in `DIALING`, and its borrower `DIALING` until a bridge callback confirms `CONNECTED`.
- Provider calls run outside database transactions. A manual agent-state update is rejected with HTTP 409 while a matching nonterminal call is active.

## 6. Pacing Inputs and Provider Setup Timing

The pacing engine measures setup duration as `initiated_at - created_at` and
average connected-call duration from completed calls. During a setup-sized
horizon, it estimates the share of connected or wrap-up agents likely to finish
as `setup_time / (setup_time + average_talk_time)`. The estimate is combined
with currently available agents and the observed answer rate; pending
non-connected attempts are deducted, and the Safety Controller remains the
final authority on allocations. The current health factor is 1.0 for a healthy
primary route, 0.5 when Provider B is unhealthy but Provider A fallback is
healthy, and 0 when no supported route is healthy. Campaign behavior is
represented by the fraction of queued borrowers with prior attempts; the
pacing multiplier decreases as retry pressure increases. These are transparent
prototype heuristics, not a learned campaign model. Cold-start defaults are 0.1 seconds for setup
and 60 seconds for talk time. Provider A and Provider B simulate different
asynchronous setup delays (45 ms and 200 ms respectively); Provider B's timeout
fault takes 500 ms before reporting uncertain acceptance. It is not retried on
Provider A because that could duplicate an already accepted call.

## 7. Scaling from 100 to 10,000 Agents

These are engineering stages, not capacity claims. The benchmark in
[`docs/load-test.md`](./docs/load-test.md) is a local in-process endpoint
baseline and does not establish production throughput.

| Workforce | Prototype suitability | Required next steps |
|---:|---|---|
| 100 | Current local SQLite prototype can exercise API reads and concurrent reservations. | Keep the SQLite file local; measure disk and lock latency; paginate dashboard reads before growing workloads. |
| 1,000 | SQLite can serialize same-host work, but snapshot serialization and full-table reads are not an efficient production design. | Move to PostgreSQL or equivalent; use indexed candidate queries, short row-level transactions, and a durable shared work queue. |
| 10,000 | The prototype is not a production capacity claim; read/load baseline degrades with full-state serialization. | Partition campaign queues; add worker leases/outbox reconciliation, provider rate limits, paginated APIs, and load tests against the target multi-worker/server-database deployment. |

The read benchmark and dialing benchmark in [`docs/load-test.md`](./docs/load-test.md)
measure different behaviors. Neither predicts production throughput, but the
dialing benchmark checks concurrent agent/borrower reservation invariants.

### Predictive Utilization Without Weakening Progressive Safety
Predictive pacing estimates a desired count from available agents, measured
setup/talk time, and observed answer rate. It does not allocate. The orchestrator
passes that proposal (or its explicit 1:1 progressive fallback) to the separate
Safety Controller inside the same SQLite transaction that makes reservations.
The database unique indexes are a final guard. Thus predictive efficiency can
change the proposed count, but cannot override deterministic agent availability
or allocate a borrower twice.
