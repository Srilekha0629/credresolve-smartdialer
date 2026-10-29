# Reproducible local load checks

These are local engineering checks, not production capacity claims. Both
benchmarks use temporary SQLite databases and leave the developer's default
application database unchanged.

## API read-throughput benchmark

This runs the real FastAPI `GET /agents` route through HTTPX's in-process ASGI
transport. It exercises 50 concurrent requests at concurrency 10 for 100,
1,000, and 10,000 agents, validates each response, and reports elapsed time,
throughput, and p50/p95 latency. It does not start Uvicorn or measure network,
TLS, provider dispatch, or multi-worker overhead.

From the project root in Windows PowerShell:

```powershell
.\venv\Scripts\python.exe backend\load_test.py --agents 100 1000 10000 --requests 50 --concurrency 10
```

### Measured local baseline

Measured on the current Windows workspace and repository virtual environment.
The benchmark capped each size at approximately 5,000 agent-cycle units.

Recorded during the current implementation run. Environment: local Windows
workspace and the repository virtual environment; repeat to obtain the
measurements for your machine.

| Agents | Requests | Concurrency | Elapsed | Throughput | p50 latency | p95 latency |
|---:|---:|---:|---:|---:|---:|---:|
| 100 | 50 | 10 | 1.767 s | 28.3 req/s | 31.40 ms | 62.10 ms |
| 1,000 | 50 | 10 | 3.771 s | 13.3 req/s | 62.85 ms | 101.21 ms |
| 10,000 | 50 | 10 | 20.795 s | 2.4 req/s | 372.11 ms | 480.16 ms |

These results show the cost of the current full-state SQLite load/serialization
path; they are not a throughput guarantee.

## Concurrent dialing/reservation benchmark

This runs real progressive cycles against an isolated SQLite store. It launches
concurrent cycles (each capped at one call) and uses an immediate fake provider
so the measured time focuses on reservation/storage, not simulated carrier
latency. It verifies the expected number of reservations and uniqueness of
agent and borrower assignments. A separate pytest also launches two Python
processes contending for the same database.

```powershell
.\venv\Scripts\python.exe backend\dialing_load_test.py --agents 100 1000 10000 --cycles 50 --concurrency 10
```

For dialing runs, `--cycles` is the maximum per agent size. The script caps
each run at approximately 5,000 agent-cycle units so the 10,000-agent case is
practical on a developer machine (one cycle at 10,000 agents with the defaults).
The actual cycle count is printed with each measurement.

### Measured local baseline

| Agents | Cycles | Concurrency | Elapsed | Throughput | Calls reserved | Unique agents | Unique borrowers | Invariants | p50 latency | p95 latency |
|---:|---:|---:|---:|---:|---:|---:|---:|:---:|---:|---:|
| 100 | 50 | 10 | 10.089 s | 5.0 cycles/s | 50 | 50 | 50 | true | 158.51 ms | 509.70 ms |
| 1,000 | 5 | 10 | 2.515 s | 2.0 cycles/s | 5 | 5 | 5 | true | 509.88 ms | 542.54 ms |
| 10,000 | 1 | 10 | 4.657 s | 0.2 cycles/s | 1 | 1 | 1 | true | 4,656.37 ms | 4,656.37 ms |

This is a single-process asyncio benchmark, not a network/server or sustained
multi-process throughput test. The separate-process test verifies correctness,
not performance. The 10,000-agent result has a single sample, so its p50 and
p95 are that one observation rather than statistically meaningful percentiles.

## Interpretation and limitations

The read test measures only API list retrieval. The dialing test measures
concurrent call reservation and uniqueness under the current SQLite snapshot
implementation; it does not simulate real providers, sustained campaign load,
or failures. The tests do not establish production performance, disk/network
filesystem suitability, or multi-host safety. For 1,000-10,000 agent production
workloads, use indexed row-level queries in a server database, a durable queue,
pagination, and benchmarks against the target deployment topology.
