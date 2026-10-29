import os
import shutil
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from backend.app.storage.memory_store import MemoryStore
from backend.app.providers.provider_manager import ProviderManager
from backend.app.models.enums import ProviderName
from backend.app.services.event_processor import EventProcessor
from backend.app.services.metrics_service import MetricsService
from backend.app.services.predictive_pacing import PredictivePacingEngine
from backend.app.services.safety_controller import SafetyController
from backend.app.services.scenario_runner import ScenarioRunner
from backend.app.services.dialer_orchestrator import DialerOrchestrator

_test_database_directory = tempfile.mkdtemp(prefix="smartdialer-pytest-bootstrap-")
_previous_database_path = os.environ.get("SMARTDIALER_DB_PATH")
os.environ["SMARTDIALER_DB_PATH"] = os.path.join(
    _test_database_directory, "bootstrap.sqlite3"
)
from backend.app import main as main_module

if _previous_database_path is None:
    os.environ.pop("SMARTDIALER_DB_PATH", None)
else:
    os.environ["SMARTDIALER_DB_PATH"] = _previous_database_path

app = main_module.app
_bootstrap_services = {
    name: getattr(main_module, name)
    for name in (
        "store",
        "safety_controller",
        "pacing_engine",
        "provider_manager",
        "dialer_orchestrator",
        "event_processor",
        "metrics_service",
        "scenario_runner",
    )
}


def pytest_unconfigure(config):
    shutil.rmtree(_test_database_directory)


@pytest.fixture(autouse=True)
def reset_store_before_each_test(tmp_path, monkeypatch):
    """Keep every test isolated from the user's persistent demo database."""
    store = MemoryStore(str(tmp_path / "smartdialer-test.sqlite3"))
    monkeypatch.setattr(MemoryStore, "_instance", store)
    pm = ProviderManager()
    pm.set_primary_provider(ProviderName.PROVIDER_A)
    monkeypatch.setattr(ProviderManager, "_instance", pm)

    main_module.store = store
    main_module.safety_controller = SafetyController(store)
    main_module.pacing_engine = PredictivePacingEngine(store, pm)
    main_module.provider_manager = pm
    main_module.dialer_orchestrator = DialerOrchestrator(
        store=store,
        safety_controller=main_module.safety_controller,
        pacing_engine=main_module.pacing_engine,
        provider_manager=pm,
    )
    main_module.event_processor = EventProcessor(store)
    main_module.metrics_service = MetricsService(store, pm)
    main_module.scenario_runner = ScenarioRunner(store, pm)
    try:
        yield
    finally:
        for name, service in _bootstrap_services.items():
            setattr(main_module, name, service)


@pytest.fixture
def tmp_path():
    """Provide isolated temporary paths without pytest's global temp pruning."""
    path = Path(tempfile.mkdtemp(prefix="smartdialer-test-"))
    try:
        yield path
    finally:
        shutil.rmtree(path)


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def store():
    return MemoryStore.get_instance()


@pytest.fixture
def provider_manager():
    return ProviderManager.get_instance()
