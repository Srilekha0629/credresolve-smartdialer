"""Reproducible in-process ASGI load check for the agent-list endpoint."""

import argparse
import asyncio
import os
import statistics
import sys
import tempfile
import time
from pathlib import Path

import httpx

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Isolate benchmark data from the developer's persistent application database.
_load_test_directory = tempfile.TemporaryDirectory(prefix="smartdialer-read-load-")
os.environ["SMARTDIALER_DB_PATH"] = str(
    Path(_load_test_directory.name) / "load-test.sqlite3"
)

from backend.app.main import app
from backend.app.models.agent import Agent
from backend.app.models.enums import AgentState
from backend.app.storage.memory_store import MemoryStore


async def benchmark(agent_count: int, request_count: int, concurrency: int) -> dict:
    store = MemoryStore.get_instance()
    store.seed_defaults()
    with store.transaction():
        store.agents = {
            f"load_agent_{index:05d}": Agent(
                id=f"load_agent_{index:05d}",
                name=f"Load Test Agent {index}",
                state=AgentState.AVAILABLE,
            )
            for index in range(agent_count)
        }

    semaphore = asyncio.Semaphore(concurrency)
    latencies = []

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://smartdialer.local",
    ) as client:
        async def request_agents() -> None:
            async with semaphore:
                started = time.perf_counter()
                response = await client.get("/agents")
                elapsed = time.perf_counter() - started
                if response.status_code != 200:
                    raise RuntimeError(
                        f"GET /agents returned HTTP {response.status_code}"
                    )
                if len(response.json()) != agent_count:
                    raise RuntimeError(
                        f"GET /agents returned {len(response.json())} agents; "
                        f"expected {agent_count}"
                    )
                latencies.append(elapsed)

        started = time.perf_counter()
        await asyncio.gather(
            *(request_agents() for _ in range(request_count))
        )
        elapsed = time.perf_counter() - started

    ordered = sorted(latencies)
    p95_index = min(len(ordered) - 1, int(0.95 * len(ordered)))
    return {
        "agents": agent_count,
        "requests": request_count,
        "concurrency": concurrency,
        "elapsed_seconds": elapsed,
        "requests_per_second": request_count / elapsed,
        "p50_ms": statistics.median(ordered) * 1000,
        "p95_ms": ordered[p95_index] * 1000,
    }


async def run(args: argparse.Namespace) -> None:
    for agent_count in args.agents:
        result = await benchmark(
            agent_count=agent_count,
            request_count=args.requests,
            concurrency=args.concurrency,
        )
        print(
            f"agents={result['agents']} requests={result['requests']} "
            f"concurrency={result['concurrency']} "
            f"elapsed={result['elapsed_seconds']:.3f}s "
            f"throughput={result['requests_per_second']:.1f} req/s "
            f"p50={result['p50_ms']:.2f}ms p95={result['p95_ms']:.2f}ms"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agents", nargs="+", type=int, default=[100, 1000, 10000])
    parser.add_argument("--requests", type=int, default=50)
    parser.add_argument("--concurrency", type=int, default=10)
    args = parser.parse_args()
    if any(count <= 0 for count in args.agents):
        parser.error("--agents values must be positive")
    if args.requests <= 0 or args.concurrency <= 0:
        parser.error("--requests and --concurrency must be positive")
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
