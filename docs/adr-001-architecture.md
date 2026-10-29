# ADR-001: Architecture, Concurrency Model, and Safety Boundary for SmartDialer Prototype

## Status
**ACCEPTED**

## Context
CredResolve requires a prototype SmartDialer that implements:
1. Progressive and predictive outbound dialing.
2. Safe agent-to-call allocation with strict concurrency protection.
3. Telecommunications event ingestion with idempotency and out-of-order handling.
4. Mock telecom providers with failure simulation and automated fallback.
5. A full-stack solution (FastAPI + React) runnable locally without external dependencies, paid services, or real telephone networks.

The core challenge is balancing a reproducible local prototype with durable
reservations, cross-process allocation safety on one host, and clear boundaries
between pacing, safety, provider submission, and event processing.

---

## Architectural Decisions

### 1. SQLite State and Same-Host Atomic Reservations
- **Decision**: Keep the existing `MemoryStore` API but persist agents, borrowers,
  calls, and processed event IDs in SQLite. Reservation and event state changes
  run in `BEGIN IMMEDIATE` transactions, with partial unique indexes on active
  agent and borrower assignments.
- **Rationale**: Retains a zero-service local setup while making state durable
  and allocation atomic across separate backend processes sharing a local
  database file. `asyncio.Lock` and `threading.RLock` coordinate within a
  process; the SQLite writer lock is the cross-process boundary.
- **Explicit Limitation**: SQLite is a same-host prototype. It is not a
  multi-host database, and whole-state snapshot reads/writes are not a
  production scaling strategy. Production should use a server database with
  row-level locking plus a durable queue/outbox.

### 2. Strict Architectural Decoupling: Pacing Engine vs. Safety Controller
- **Decision**: Separate the predictive calculation from safety enforcement. The `PredictivePacingEngine` is purely functional and computational. It can only propose call batches; it has zero direct access to reserve agents, initiate calls, or talk to telecom carriers.
- **Rationale**: In real debt recovery dialers, overdial algorithms can cause compliance violations (abandoned call rates exceeding statutory limits). Forcing all dial requests (progressive and predictive) through an independent `SafetyController` prevents unsafe overdialing regardless of algorithmic edge cases.

### 3. Idempotent Provider Event Ingestion with Terminal Locking
- **Decision**:
  - Every incoming webhook must include a unique `event_id`. Processed IDs and call transitions are committed together in SQLite to ensure idempotent execution across restarts.
  - Calls in terminal states (`COMPLETED`, `FAILED`, `CANCELLED`) reject all incoming transitions. Late events (such as an out-of-order `ANSWERED` event from flaky Provider B) are rejected without altering the call or reviving the agent.
- **Rationale**: Telecom carriers regularly retry webhooks upon network hiccups or send events out of chronological sequence. Strict terminal locking guarantees that a call that was hung up or failed is never accidentally reactivated.

### 4. Mock Telecom Provider Abstraction with Outage Fallback
- **Decision**: Implement a `BaseTelecomProvider` contract with two concrete mock providers:
  - `Provider A`: High-availability Tier-1 provider (fast, reliable).
  - `Provider B`: Flaky Tier-2 carrier with configurable setup faults (timeouts and definite 503 rejections); duplicate and out-of-order callback generation is exercised by Scenario D, not emitted by normal dial runs.
  - `ProviderManager`: Falls back after a definite rejection or known unavailability. Does not retry when a timeout leaves acceptance uncertain.
- **Rationale**: Allows deterministic unit and integration testing of network failure scenarios, idempotency, and automated carrier failover without real SIP/PSTN infrastructure.

### 5. Decoupled Frontend (React + Vite + Modern CSS)
- **Decision**: Build the dashboard using React, Vite, and scoped CSS, connecting to the live FastAPI REST API.
- **Rationale**: Eliminates template rendering overhead, provides immediate interactive feedback for dialer cycles and provider fault toggles, and guarantees dashboard metrics accurately reflect live server state.

---

## Consequences
- **Positive**:
  - Zero external database or cloud dependencies needed to run or test.
  - Tests exercise concurrent allocation, durable recovery, safety limits,
    idempotency, provider fallback, and scenario/event flows; this is not a
    claim of complete code coverage.
  - Clean, legible code structure suitable for explaining in an interview.
- **Trade-offs**:
  - `NOT_SUBMITTED` work from a dead process is failed and released; `SUBMITTING`
    work becomes `UNKNOWN` and remains reserved pending reconciliation.
  - Automated provider reconciliation for calls left `UNKNOWN` is outside this
    prototype; resetting or running scenarios clears demo state and must not be
    used for operational data.
