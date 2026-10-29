import pytest
import asyncio
import os
import subprocess
import sys
from pathlib import Path

from backend.app.services.dialer_orchestrator import DialerOrchestrator
from backend.app.storage.memory_store import MemoryStore


@pytest.mark.asyncio
async def test_concurrent_allocation_not_reserving_same_agent_twice():
    """
    Test 2: Concurrent allocation not reserving the same agent twice.
    Fires 5 simultaneous progressive dial cycles.
    Since only 3 agents are available, total calls initiated across ALL 5 concurrent
    requests must exactly equal 3, and each agent must be assigned to at most one call.
    """
    store = MemoryStore.get_instance()
    orchestrator = DialerOrchestrator(store=store)

    assert len(store.get_available_agents()) == 3

    # Launch 5 concurrent dial cycles
    tasks = [orchestrator.run_progressive_cycle() for _ in range(5)]
    results = await asyncio.gather(*tasks)

    total_initiated = sum(r.calls_initiated for r in results)
    assert total_initiated == 3, f"Expected exactly 3 calls initiated, got {total_initiated}"

    # Verify no agent is assigned to more than 1 active call
    calls = store.get_calls()
    agent_ids_in_calls = [c.agent_id for c in calls if c.agent_id is not None]
    assert len(agent_ids_in_calls) == len(set(agent_ids_in_calls)), "Duplicate agent assignment detected!"

    # Verify borrowers assigned to calls are all distinct
    borrower_ids_in_calls = [c.borrower_id for c in calls]
    assert len(borrower_ids_in_calls) == len(set(borrower_ids_in_calls)), "Duplicate borrower assignment detected!"


def test_separate_processes_serialize_agent_and_borrower_reservations(tmp_path):
    database_path = tmp_path / "process-contention.sqlite3"
    ready_dir = tmp_path / "ready"
    ready_dir.mkdir()
    project_root = Path(__file__).resolve().parents[2]
    script = """
import asyncio
import os
import sys
import time
from pathlib import Path
from backend.app.models.enums import ProviderName
from backend.app.services.dialer_orchestrator import DialerOrchestrator
from backend.app.storage.memory_store import MemoryStore

index = sys.argv[1]
ready_dir = Path(os.environ["SMARTDIALER_READY_DIR"])
store = MemoryStore()
(ready_dir / f"ready_{index}").write_text("ready")
deadline = time.monotonic() + 20
while not all((ready_dir / f"ready_{i}").exists() for i in ("0", "1")):
    if time.monotonic() > deadline:
        raise TimeoutError("other process did not finish store initialization")
    time.sleep(0.01)

class FastProvider:
    primary_provider_name = ProviderName.PROVIDER_A
    async def initiate_call_with_fallback(self, call_id, borrower_phone):
        await asyncio.sleep(0.05)
        return True, ProviderName.PROVIDER_A, "INITIATED", {}, False

asyncio.run(DialerOrchestrator(store=store, provider_manager=FastProvider()).run_progressive_cycle())
"""
    environment = os.environ.copy()
    environment["SMARTDIALER_DB_PATH"] = str(database_path)
    environment["SMARTDIALER_READY_DIR"] = str(ready_dir)

    processes = [
        subprocess.Popen(
            [sys.executable, "-c", script, str(index)],
            cwd=project_root,
            env=environment,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        for index in range(2)
    ]
    for process in processes:
        process.wait(timeout=30)
    assert [process.returncode for process in processes] == [0, 0]

    store = MemoryStore(str(database_path))
    calls = store.get_calls()
    assert len(calls) == 3
    assert len({call.agent_id for call in calls}) == 3
    assert len({call.borrower_id for call in calls}) == 3
