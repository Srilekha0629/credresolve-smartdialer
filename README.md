# CredResolve SmartDialer

A high-concurrency, resilience-oriented outbound dialer prototype built for the CredResolve Hiring Assignment. Implements **Progressive** and **Predictive** dialing modes with a separate **Safety Controller**, durable SQLite state, idempotent telecom event ingestion, mock carriers with acceptance-aware fallback, and a **React + Vite** dashboard.

---

## Features

- **Agent Lifecycle**: `OFFLINE`, `AVAILABLE`, `RESERVED`, `DIALING`, `CONNECTED`, `WRAP_UP`, `PAUSED`.
- **Call Lifecycle**: `QUEUED`, `RESERVED`, `INITIATED`, `RINGING`, `ANSWERED`, `CONNECTED`, `COMPLETED`, `FAILED`, `CANCELLED`.
- **Progressive Dialer**: Enforces 1:1 agent-to-call matching. Never initiates more calls than safe agent headroom.
- **Predictive Pacing Engine**: Computes bounded call suggestions from agent availability, active calls, answer rate, provider health, setup/talk times, and queued-borrower retry pressure. Every result still passes through the Safety Controller.
- **Setup-aware pacing**: Uses observed reservation-to-provider setup time and completed-call talk time when estimating near-horizon agent capacity.
- **Separate Safety Controller**: Independent enforcement layer that validates, clamps, or rejects unsafe proposed call batches.
- **Mock Telecom Providers**:
  - **Provider A**: Fast, reliable Tier-1 carrier with a simulated 45 ms setup delay.
  - **Provider B**: Flaky Tier-2 carrier with a simulated 200 ms setup delay, network timeouts, and definite 503 rejections. Duplicate and out-of-order callback generation is scenario-only (Scenario D), not a live webhook emitter for ordinary dial runs.
  - **Acceptance-aware fallback**: A definite Provider B rejection may fall back to Provider A; a timeout with uncertain acceptance is retained for reconciliation and is not retried.
- **Idempotency & Terminal Locking**: Dedupes provider events via unique `event_id` and keyed dial requests via `Idempotency-Key`; prevents late `ANSWERED` events from reviving completed calls.
- **Durable reservations**: SQLite persists agents, borrowers, calls, and processed event IDs. `BEGIN IMMEDIATE` and unique active-call indexes protect allocation across processes on the same host.
- **Crash-aware dispatch**: Unsubmitted reservations are failed and released; uncertain submissions remain reserved and are never retried; accepted and answered calls are reconciled to their agent/borrower state after restart.
- **Interactive React Dashboard**: Live API metrics, mode controls, agent state management, provider fault toggles, and explicit A-D simulated scenarios through call and provider-event processing.

---

## Tech Stack

- **Backend**: Python 3.10+, FastAPI, Pydantic v2, Uvicorn
- **Testing**: pytest, pytest-asyncio, httpx / FastAPI TestClient
- **Frontend**: React 18, Vite, JavaScript, Lucide Icons, Modern CSS
- **State & Concurrency**: SQLite-backed durable state with transactional reservations and local async/thread locks

---

## Directory Structure

```
credresolve-smartdialer/
├── backend/
│   ├── app/
│   │   ├── models/            # Pydantic schemas (Agent, Call, Borrower, Events, Metrics)
│   │   ├── state_machines/    # Agent & Call state transition machines
│   │   ├── storage/           # SQLite-backed durable store and reservation transactions
│   │   ├── providers/         # Base provider, Provider A, Provider B, ProviderManager
│   │   ├── services/          # SafetyController, PredictivePacing, Orchestrator, EventProcessor
│   │   └── main.py            # FastAPI REST application routes & OpenAPI docs
│   ├── tests/                 # Automated test suite (7 required categories + API tests)
│   ├── run_server.py          # Backend server launch script
│   ├── run_tests.py           # Test runner script
│   ├── load_test.py           # Concurrent API read throughput benchmark
│   └── dialing_load_test.py   # Concurrent dialing/reservation benchmark
├── frontend/
│   ├── src/
│   │   ├── components/        # Header, Metrics, Controls, Providers, Tables, Alerts
│   │   ├── api.js             # Backend API client
│   │   ├── App.jsx            # Main dashboard component & polling loop
│   │   └── index.css          # Scoped dark theme styles
│   ├── package.json           # Frontend dependencies
│   ├── vite.config.js         # Vite configuration with /api proxy
│   └── index.html             # HTML entry point
├── docs/
│   ├── architecture.mmd       # Mermaid architecture diagram
│   ├── state-machines.md      # Detailed Agent and Call transition specs
│   └── adr-001-architecture.md# Architecture Decision Record
├── ARCHITECTURE.md            # In-depth architectural specification
├── requirements.txt           # Python backend dependencies
└── README.md                  # Project documentation
```

---

## Quick Start (Windows / macOS / Linux)

### 1. Prerequisites
- **Python 3.10+**
- **Node.js 18+** and **npm**

---

### 2. Backend Setup & Run

Open a terminal in the project root:

```powershell
# 1. Create and activate a Python virtual environment
python -m venv venv
.\venv\Scripts\Activate.ps1       # On Windows PowerShell
# source venv/bin/activate       # On Linux/macOS

# 2. Install backend dependencies
pip install -r requirements.txt

# 3. Start the FastAPI server
.\venv\Scripts\python.exe -m backend.run_server
```
The backend server starts at: **`http://localhost:8000`**
Interactive Swagger API documentation: **`http://localhost:8000/docs`**
State is stored in SQLite at `%USERPROFILE%\.credresolve-smartdialer\smartdialer.sqlite3`
by default. Set `SMARTDIALER_DB_PATH` before starting the backend to select a
different local database file. Keep this file on a local disk; the prototype
does not support multi-host SQLite deployments.

---

### 3. Frontend Setup & Run

Open a second terminal window:

```powershell
# Navigate to the frontend directory
cd frontend

# Install npm dependencies
npm install

# Start the Vite development server
npm run dev
```

The frontend dashboard will be available at: **`http://localhost:5173`**

---

### 4. Running the Automated Tests

To run the full automated test suite verifying all 7 core specifications:

```powershell
# Run using the project virtual environment on Windows
.\venv\Scripts\python.exe -m pytest -v backend/tests

# Alternatively, run via the standalone test runner script:
python backend/run_tests.py
```

### 5. Reproducible Local Load Check

With the virtual environment installed, run both local load checks:

```powershell
.\venv\Scripts\python.exe backend\load_test.py --agents 100 1000 10000 --requests 50 --concurrency 10
.\venv\Scripts\python.exe backend\dialing_load_test.py --agents 100 --cycles 50 --concurrency 10
```

The first reports `GET /agents` throughput and p50/p95 latency. The second
measures concurrent progressive reservation cycles and checks unique agent and
borrower assignment. Neither is a production/network capacity guarantee. See
[docs/load-test.md](./docs/load-test.md) for measured local results and limits.

---

## Automated Test Coverage

The test suite in `backend/tests/` verifies the core requirements and API integration:

| Test File | Verified Requirement |
| :--- | :--- |
| `test_progressive_dialer.py` | Progressive mode never exceeds safe agent availability; respects max call caps. |
| `test_concurrency.py` | Same-process and separate-process cycles never reserve the same agent or borrower twice. |
| `test_safety_controller.py` | Safety Controller reduces or rejects unsafe batches; clamps to safe agent headroom; rejects duplicate borrowers. |
| `test_event_idempotency.py` | Duplicate provider events with identical `event_id` are idempotent and ignored safely. |
| `test_state_transitions.py` | Invalid or out-of-order transitions do not corrupt state; **late ANSWERED events never revive completed calls**. |
| `test_provider_fallback.py` | Definite Provider B rejection falls back; uncertain timeout is not retried; total outage releases reservations. |
| `test_failure_handling.py` | Worker exceptions/cancellation preserve uncertain calls and release only unsubmitted work; agent state cannot change during setup. |
| `test_predictive_pacing.py` | Provider health and queued-borrower retry pressure affect pacing; every executed proposal remains Safety Controller-bounded. |
| `test_dial_request_idempotency.py` | Completed requests replay the stored result; concurrent retries share one batch; key/payload conflicts are rejected. |
| `test_persistent_recovery.py` | Abrupt process exit recovery for NOT_SUBMITTED, SUBMITTING, ACCEPTED, and ANSWERED states, plus durable event idempotency. |
| `test_api_endpoints.py` | REST integration and deterministic A-D scenario simulations. |

---

## API Endpoints

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/health` | Service health status and timestamp. |
| `GET` | `/agents` | List all agents and their current states. |
| `POST` | `/agents/{id}/state` | Update an agent's state (`AVAILABLE`, `PAUSED`, `OFFLINE`). |
| `GET` | `/borrowers` | List all borrowers in the campaign queue. |
| `GET` | `/calls` | List all active and past calls with full lifecycle tracking. |
| `GET` | `/metrics` | Real-time system metrics (answer rate, utilization, active calls). |
| `GET` | `/providers` | Status and health metrics for Provider A and Provider B. |
| `POST` | `/dialer/progressive/run` | Execute progressive dial cycle (1:1 safe reservation); accepts optional `Idempotency-Key` header. |
| `POST` | `/dialer/predictive/run` | Execute predictive dial cycle (pacing suggestion $\to$ Safety Controller); accepts optional `Idempotency-Key` header. |
| `POST` | `/events/provider` | Ingest idempotent telecom provider webhook event. |
| `POST` | `/calls/{id}/progress` | Interactive simulation route to progress a call through its lifecycle. |
| `POST` | `/providers/configure` | Configure Provider B setup failures/timeouts and Scenario D duplicate/out-of-order webhook generation. |
| `POST` | `/simulation/reset` | Reset persistent demo database to clean seed state. |
| `POST` | `/simulation/scenarios/{A|B|C|D}` | Reset the demo dataset, then run a labeled simulation through dialing and provider-event processing. |

---

## Design Decisions & Concurrency Guarantees

1. **SQLite-serialized Reservation**:
   - Agent/borrower eligibility checks and call reservations execute within `BEGIN IMMEDIATE`; partial unique indexes additionally forbid multiple active calls per agent or borrower.
   - SQLite serializes independent store instances and Python processes sharing the same local database file. Provider I/O occurs after the short transaction.
   - This is a local-file prototype, not a distributed database. Do not put its SQLite file on a network filesystem or use it for multi-host coordination.
2. **Predictive Engine Separation**:
   - The `PredictivePacingEngine` is purely computational. It uses availability, answer rates, measured setup/talk times, provider route health, and queued-borrower retry pressure.
   - It **never** reserves agents or contacts carriers.
   - Its output is submitted directly to the `SafetyController`, which clamps the batch to safe real-time capacity.
3. **Out-of-Order Telecom Event Protection**:
   - In accordance with telephony standards, `COMPLETED`, `FAILED`, and `CANCELLED` are terminal states.
   - Any late-arriving `ANSWERED` or `RINGING` event arriving after a call has terminated is safely recorded and rejected, preventing "zombie calls" from trapping agent capacity.

---

## Persistence and Deployment Limitations

- SQLite transactions support competing processes on one host, verified by a two-process allocation test. They do not provide multi-host coordination, horizontal scalability, or campaign queue partitioning. Production deployments should use a server database and durable work queue.
- A `NOT_SUBMITTED` reservation left by a dead owner process is safely failed and released. A `SUBMITTING` call left by a dead process becomes `UNKNOWN` and remains reserved. The prototype deliberately does not retry unknown provider acceptance and has no automated external provider-reconciliation endpoint.
- `/simulation/reset` and `/simulation/scenarios/{A|B|C|D}` reset the persistent demo dataset. Do not use these controls against operational data.
- Dial-cycle retries are deduplicated when clients reuse the same `Idempotency-Key` and request body. A key reused with different parameters receives HTTP 409. Calls without the header retain legacy non-idempotent request behavior.
- Simulation reset clears demo calls and entities but deliberately retains the dial-request idempotency ledger; use a new key for every new dial action, including after reset.

## Assignment Scenarios and Safety Answer

Scenarios A-C seed explicitly simulated historical outcomes at 20%/120s,
50%/90s, and 70%/180s, run predictive pacing, then pass simulated call progress
through the provider-event processor. Scenario D changes answer-rate and
talk-time inputs, exercises a definite Provider B outage with Provider A
fallback, then progressive fallback plus duplicate/out-of-order webhook
handling. Scenario data is labeled simulated and is not carrier data.

Predictive utilization retains progressive deterministic safety by treating
pacing only as a **proposal**. Provider health and queued-borrower retry
pressure conservatively influence the suggested count. The orchestrator sends every proposed count,
including fallback batches, through `SafetyController.validate_and_filter_batch`
inside the same SQLite transaction that reserves the unique agent/borrower
pairs. The safety controller can reduce/reject the proposal; the pacing engine
never reserves or initiates a call.
