"""Measure concurrent dial-cycle reservation throughput and uniqueness."""

import argparse
import asyncio
import statistics
import sys
import tempfile
import time
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.models.agent import Agent
from backend.app.models.borrower import Borrower
from backend.app.models.enums import AgentState, ProviderName
from backend.app.services.dialer_orchestrator import DialerOrchestrator
from backend.app.storage.memory_store import MemoryStore


class ImmediateProvider:
    primary_provider_name = ProviderName.PROVIDER_A

    async def initiate_call_with_fallback(self, call_id: str, borrower_phone: str):
        return True, ProviderName.PROVIDER_A, "INITIATED", {}, False


async def benchmark(agent_count: int, cycles: int, concurrency: int) -> dict:
    with tempfile.TemporaryDirectory(prefix="smartdialer-load-") as temp_dir:
        store = MemoryStore(str(Path(temp_dir) / "load.sqlite3"))
        with store.transaction():
            store.agents = {
                f"load_agent_{index:05d}": Agent(
                    id=f"load_agent_{index:05d}",
                    name=f"Load Test Agent {index}",
                    state=AgentState.AVAILABLE,
                )
                for index in range(agent_count)
            }
            store.borrowers = {
                f"load_borrower_{index:05d}": Borrower(
                    id=f"load_borrower_{index:05d}",
                    name=f"Load Test Borrower {index}",
                    phone=f"+1555{index:07d}",
                )
                for index in range(agent_count)
            }
            store.calls.clear()
            store.seen_event_ids.clear()
            store.event_log.clear()

        orchestrator = DialerOrchestrator(
            store=store, provider_manager=ImmediateProvider()
        )
        semaphore = asyncio.Semaphore(concurrency)
        latencies = []
        allocations = []

        async def run_cycle() -> None:
            async with semaphore:
                started = time.perf_counter()
                result = await orchestrator.run_progressive_cycle(max_calls=1)
                latencies.append(time.perf_counter() - started)
                allocations.extend(result.call_ids)

        started = time.perf_counter()
        await asyncio.gather(*(run_cycle() for _ in range(cycles)))
        elapsed = time.perf_counter() - started

        calls = store.get_calls()
        assigned_agents = [call.agent_id for call in calls if call.agent_id is not None]
        assigned_borrowers = [call.borrower_id for call in calls]
        safe = (
            len(assigned_agents) == len(set(assigned_agents))
            and len(assigned_borrowers) == len(set(assigned_borrowers))
            and len(calls) == min(agent_count, cycles)
        )
        if not safe:
            raise RuntimeError(
                f"Reservation invariant failed: {len(calls)} calls for "
                f"{agent_count} agents and {cycles} cycles."
            )

        ordered = sorted(latencies)
        p95_index = min(len(ordered) - 1, int(0.95 * len(ordered)))
        return {
            "agents": agent_count,
            "cycles": cycles,
            "concurrency": concurrency,
            "elapsed_seconds": elapsed,
            "cycles_per_second": cycles / elapsed,
            "calls_reserved": len(allocations),
            "unique_agents": len(set(assigned_agents)),
            "unique_borrowers": len(set(assigned_borrowers)),
            "invariants": safe,
            "p50_ms": statistics.median(ordered) * 1000,
            "p95_ms": ordered[p95_index] * 1000,
        }


async def run(args: argparse.Namespace) -> None:
    for agent_count in args.agents:
        cycles = min(args.cycles, max(1, 5000 // agent_count))
        result = await benchmark(agent_count, cycles, args.concurrency)
        print(
            f"agents={result['agents']} cycles={result['cycles']} "
            f"concurrency={result['concurrency']} elapsed={result['elapsed_seconds']:.3f}s "
            f"throughput={result['cycles_per_second']:.1f} cycles/s "
            f"calls_reserved={result['calls_reserved']} "
            f"unique_agents={result['unique_agents']} "
            f"unique_borrowers={result['unique_borrowers']} "
            f"invariants={result['invariants']} "
            f"p50={result['p50_ms']:.2f}ms p95={result['p95_ms']:.2f}ms"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agents", type=int, nargs="+", default=[100, 1000, 10000])
    parser.add_argument("--cycles", type=int, default=50)
    parser.add_argument("--concurrency", type=int, default=10)
    args = parser.parse_args()
    if any(agent_count <= 0 for agent_count in args.agents) or args.cycles <= 0 or args.concurrency <= 0:
        parser.error("--agents, --cycles, and --concurrency must be positive")
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
