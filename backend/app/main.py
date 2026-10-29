from datetime import datetime
import uuid
from typing import List, Dict, Any, Optional
from fastapi import FastAPI, Header, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from backend.app.models.enums import AgentState, CallState, ProviderName, ProviderEventType
from backend.app.models.agent import Agent, AgentStateUpdate
from backend.app.models.borrower import Borrower
from backend.app.models.call import Call
from backend.app.models.dialer import ProgressiveDialRequest, PredictiveDialRequest, DialCycleResult
from backend.app.models.provider_event import ProviderWebhookRequest, ProviderWebhookResponse
from backend.app.models.metrics import SystemMetrics

from backend.app.storage.memory_store import MemoryStore
from backend.app.services.safety_controller import SafetyController
from backend.app.services.predictive_pacing import PredictivePacingEngine
from backend.app.services.dialer_orchestrator import (
    DialerOrchestrator,
    DialRequestConflict,
)
from backend.app.services.event_processor import EventProcessor
from backend.app.services.metrics_service import MetricsService
from backend.app.services.scenario_runner import ScenarioRunner
from backend.app.providers.provider_manager import ProviderManager
from backend.app.state_machines.agent_state_machine import AgentStateMachine
from backend.app.state_machines.call_state_machine import CallStateMachine

app = FastAPI(
    title="CredResolve SmartDialer API",
    description=(
        "SmartDialer: Production-grade progressive & predictive outbound dialing engine "
        "with strict safety bounds, idempotent telecom event ingestion, and outage fallback."
    ),
    version="1.0.0",
)

# Enable CORS for React/Vite frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Core singletons
store = MemoryStore.get_instance()
safety_controller = SafetyController(store)
provider_manager = ProviderManager.get_instance()
pacing_engine = PredictivePacingEngine(store, provider_manager)
dialer_orchestrator = DialerOrchestrator(
    store=store,
    safety_controller=safety_controller,
    pacing_engine=pacing_engine,
    provider_manager=provider_manager,
)
event_processor = EventProcessor(store)
metrics_service = MetricsService(store, provider_manager)
scenario_runner = ScenarioRunner(store, provider_manager)


# ---------------- Health & Diagnostics ----------------
@app.get("/health", tags=["Health"])
async def health_check():
    return {
        "status": "ok",
        "service": "SmartDialer",
        "timestamp": datetime.utcnow().isoformat(),
        "storage": "sqlite-durable-cross-process-transactional",
        "version": "1.0.0",
    }


# ---------------- Entities: Agents ----------------
@app.get("/agents", response_model=List[Agent], tags=["Agents"])
async def list_agents():
    return store.get_agents()


@app.get("/agents/{agent_id}", response_model=Agent, tags=["Agents"])
async def get_agent(agent_id: str):
    agent = store.get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found.")
    return agent


@app.post("/agents/{agent_id}/state", response_model=Agent, tags=["Agents"])
async def update_agent_state(agent_id: str, req: AgentStateUpdate):
    async with store.atomic():
        agent = store.get_agent(agent_id)
        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found.")

        active_call = next(
            (call for call in store.get_active_calls() if call.agent_id == agent_id),
            None,
        )
        if active_call:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Agent '{agent_id}' cannot change state while handling "
                    f"active call '{active_call.id}'."
                )
            )

        valid, reason = AgentStateMachine.validate_transition(agent.state, req.state)
        if not valid:
            raise HTTPException(status_code=400, detail=reason)

        agent.state = req.state
        if req.state in (AgentState.AVAILABLE, AgentState.OFFLINE, AgentState.PAUSED):
            agent.current_call_id = None

        return store.update_agent(agent)


# ---------------- Entities: Borrowers ----------------
@app.get("/borrowers", response_model=List[Borrower], tags=["Borrowers"])
async def list_borrowers():
    return store.get_borrowers()


# ---------------- Entities: Calls ----------------
@app.get("/calls", response_model=List[Call], tags=["Calls"])
async def list_calls():
    return store.get_calls()


@app.get("/calls/{call_id}", response_model=Call, tags=["Calls"])
async def get_call(call_id: str):
    call = store.get_call(call_id)
    if not call:
        raise HTTPException(status_code=404, detail=f"Call '{call_id}' not found.")
    return call


# ---------------- Metrics ----------------
@app.get("/metrics", response_model=SystemMetrics, tags=["Metrics"])
async def get_metrics():
    return metrics_service.get_system_metrics()


# ---------------- Providers ----------------
@app.get("/providers", tags=["Providers"])
async def list_providers():
    return provider_manager.get_provider_statuses()


class ProviderConfigRequest(BaseModel):
    simulate_timeout: Optional[bool] = None
    simulate_failure: Optional[bool] = None
    simulate_duplicate: Optional[bool] = None
    simulate_out_of_order: Optional[bool] = None
    manual_unhealthy: Optional[bool] = None


@app.post("/providers/configure", tags=["Providers"])
async def configure_provider_b(cfg: ProviderConfigRequest):
    provider_b = provider_manager.provider_b
    provider_b.configure_simulation(
        simulate_timeout=cfg.simulate_timeout,
        simulate_failure=cfg.simulate_failure,
        simulate_duplicate=cfg.simulate_duplicate,
        simulate_out_of_order=cfg.simulate_out_of_order,
    )
    if cfg.manual_unhealthy is not None:
        provider_b.set_healthy(not cfg.manual_unhealthy)

    return {
        "success": True,
        "provider": "PROVIDER_B",
        "current_status": provider_manager.get_provider_statuses()[1],
    }


class PrimaryProviderRequest(BaseModel):
    provider: ProviderName


@app.post("/providers/primary", tags=["Providers"])
async def set_primary_provider(req: PrimaryProviderRequest):
    provider_manager.set_primary_provider(req.provider)
    return {"success": True, "primary_provider": req.provider.value}


# ---------------- Dialer Endpoints ----------------
@app.post("/dialer/progressive/run", response_model=DialCycleResult, tags=["Dialer"])
async def run_progressive_dialer(
    req: Optional[ProgressiveDialRequest] = None,
    idempotency_key: Optional[str] = Header(
        default=None, alias="Idempotency-Key", min_length=1, max_length=128
    ),
):
    max_calls = req.max_calls if req else None
    try:
        return await dialer_orchestrator.run_progressive_cycle(
            max_calls=max_calls, idempotency_key=idempotency_key
        )
    except (DialRequestConflict, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/dialer/predictive/run", response_model=DialCycleResult, tags=["Dialer"])
async def run_predictive_dialer(
    req: Optional[PredictiveDialRequest] = None,
    idempotency_key: Optional[str] = Header(
        default=None, alias="Idempotency-Key", min_length=1, max_length=128
    ),
):
    req = req or PredictiveDialRequest()
    try:
        return await dialer_orchestrator.run_predictive_cycle(
            target_answer_rate=req.target_answer_rate,
            max_pacing_ratio=req.max_pacing_ratio or 2.0,
            allow_fallback=req.allow_fallback,
            idempotency_key=idempotency_key,
        )
    except (DialRequestConflict, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


# ---------------- Event Ingestion ----------------
@app.post("/events/provider", response_model=ProviderWebhookResponse, tags=["Events"])
async def ingest_provider_event(event: ProviderWebhookRequest):
    return await event_processor.process_event(event)


class ProgressCallRequest(BaseModel):
    event_type: ProviderEventType
    reason: Optional[str] = None


@app.post("/calls/{call_id}/progress", response_model=ProviderWebhookResponse, tags=["Events"])
async def progress_call(call_id: str, req: ProgressCallRequest):
    """Convenience simulation route for frontend demo buttons to progress calls through states."""
    event = ProviderWebhookRequest(
        event_id=f"evt_{uuid.uuid4().hex[:12]}",
        call_id=call_id,
        provider=ProviderName.PROVIDER_A,
        event_type=req.event_type,
        timestamp=datetime.utcnow(),
        reason=req.reason,
    )
    return await event_processor.process_event(event)


# ---------------- Simulation Reset ----------------
@app.post("/simulation/reset", tags=["Simulation"])
async def reset_simulation():
    async with store.atomic():
        store.seed_defaults()
    # Reset provider counters & simulation states
    provider_manager.provider_a.consecutive_failures = 0
    provider_manager.provider_a.set_healthy(True)
    provider_manager.provider_b.consecutive_failures = 0
    provider_manager.provider_b.set_healthy(True)
    provider_manager.provider_b.configure_simulation(
        simulate_timeout=False,
        simulate_failure=False,
        simulate_duplicate=False,
        simulate_out_of_order=False,
    )
    provider_manager.set_primary_provider(ProviderName.PROVIDER_A)

    return {
        "success": True,
        "message": "Simulation reset successfully to seed state.",
        "metrics": metrics_service.get_system_metrics(),
    }


@app.post("/simulation/scenarios/{scenario_id}", tags=["Simulation"])
async def run_simulation_scenario(scenario_id: str):
    try:
        return await scenario_runner.run(scenario_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
