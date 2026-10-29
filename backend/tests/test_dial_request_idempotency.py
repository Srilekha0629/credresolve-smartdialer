import asyncio

import pytest
from fastapi.testclient import TestClient

from backend.app.models.enums import ProviderName
from backend.app.services.dialer_orchestrator import DialerOrchestrator
from backend.app.storage.memory_store import MemoryStore


def test_api_replays_completed_dial_request_without_creating_another_batch(client: TestClient):
    headers = {"Idempotency-Key": "progressive-demo-request-1"}
    payload = {"max_calls": 2}

    first = client.post("/dialer/progressive/run", json=payload, headers=headers)
    replay = client.post("/dialer/progressive/run", json=payload, headers=headers)

    assert first.status_code == replay.status_code == 200
    assert first.json() == replay.json()
    assert len(MemoryStore.get_instance().get_calls()) == 2


def test_api_rejects_reuse_of_key_with_different_request(client: TestClient):
    headers = {"Idempotency-Key": "predictive-demo-request-1"}

    first = client.post(
        "/dialer/progressive/run", json={"max_calls": 1}, headers=headers
    )
    conflict = client.post(
        "/dialer/progressive/run", json={"max_calls": 2}, headers=headers
    )

    assert first.status_code == 200
    assert conflict.status_code == 409
    assert "different dial request" in conflict.json()["detail"]
    assert len(MemoryStore.get_instance().get_calls()) == 1


def test_simulation_reset_does_not_make_a_completed_request_replayable(client: TestClient):
    headers = {"Idempotency-Key": "reset-stable-request-1"}
    first = client.post(
        "/dialer/progressive/run", json={"max_calls": 1}, headers=headers
    )
    reset = client.post("/simulation/reset")
    replay = client.post(
        "/dialer/progressive/run", json={"max_calls": 1}, headers=headers
    )

    assert first.status_code == reset.status_code == replay.status_code == 200
    assert replay.json() == first.json()
    assert MemoryStore.get_instance().get_calls() == []


@pytest.mark.asyncio
async def test_completed_dial_request_replays_after_store_restart(tmp_path):
    class ImmediateProvider:
        primary_provider_name = ProviderName.PROVIDER_A

        async def initiate_call_with_fallback(self, call_id, borrower_phone):
            return True, ProviderName.PROVIDER_A, "INITIATED", {}, False

    database_path = tmp_path / "idempotent-request.sqlite3"
    first_store = MemoryStore(str(database_path))
    first_result = await DialerOrchestrator(
        store=first_store, provider_manager=ImmediateProvider()
    ).run_progressive_cycle(max_calls=1, idempotency_key="persisted-request-1")

    class MustNotDispatchProvider:
        primary_provider_name = ProviderName.PROVIDER_A

        async def initiate_call_with_fallback(self, call_id, borrower_phone):
            raise AssertionError("A persisted completed request must not be dispatched again.")

    restarted_store = MemoryStore(str(database_path))
    replay = await DialerOrchestrator(
        store=restarted_store, provider_manager=MustNotDispatchProvider()
    ).run_progressive_cycle(max_calls=1, idempotency_key="persisted-request-1")

    assert replay.call_ids == first_result.call_ids
    assert len(restarted_store.get_calls()) == 1


def test_concurrent_retries_share_one_in_flight_dial_batch():
    class GatedProvider:
        primary_provider_name = ProviderName.PROVIDER_A

        def __init__(self):
            self.started = asyncio.Event()
            self.release = asyncio.Event()

        async def initiate_call_with_fallback(self, call_id, borrower_phone):
            self.started.set()
            await self.release.wait()
            return True, ProviderName.PROVIDER_A, "INITIATED", {}, False

    async def run_concurrent_retries():
        store = MemoryStore.get_instance()
        provider = GatedProvider()
        orchestrator = DialerOrchestrator(store=store, provider_manager=provider)

        first = asyncio.create_task(
            orchestrator.run_progressive_cycle(
                max_calls=1, idempotency_key="concurrent-job-1"
            )
        )
        await provider.started.wait()
        retry = asyncio.create_task(
            orchestrator.run_progressive_cycle(
                max_calls=1, idempotency_key="concurrent-job-1"
            )
        )
        await asyncio.sleep(0.1)
        assert len(store.get_calls()) == 1

        provider.release.set()
        first_result, retry_result = await asyncio.gather(first, retry)

        assert first_result.call_ids == retry_result.call_ids
        assert first_result.calls_initiated == retry_result.calls_initiated == 1
        assert len(store.get_calls()) == 1

    asyncio.run(run_concurrent_retries())
