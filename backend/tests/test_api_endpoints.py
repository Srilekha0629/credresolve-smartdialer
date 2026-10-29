import pytest
from fastapi.testclient import TestClient


def test_health_endpoint(client: TestClient):
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["service"] == "SmartDialer"


def test_list_agents_endpoint(client: TestClient):
    response = client.get("/agents")
    assert response.status_code == 200
    agents = response.json()
    assert len(agents) == 5
    assert any(a["name"] == "Sarah Jenkins" for a in agents)


def test_list_borrowers_endpoint(client: TestClient):
    response = client.get("/borrowers")
    assert response.status_code == 200
    borrowers = response.json()
    assert len(borrowers) == 12


def test_metrics_endpoint(client: TestClient):
    response = client.get("/metrics")
    assert response.status_code == 200
    data = response.json()
    assert data["total_agents"] == 5
    assert "AVAILABLE" in data["agents_by_state"]
    assert data["total_borrowers"] == 12
    assert data["average_call_setup_seconds"] > 0
    assert data["pacing_suggested_multiplier"] >= 0

    client.post("/dialer/progressive/run")
    updated_metrics = client.get("/metrics").json()
    assert updated_metrics["pacing_suggested_multiplier"] == 0


def test_list_providers_endpoint(client: TestClient):
    response = client.get("/providers")
    assert response.status_code == 200
    providers = response.json()
    assert len(providers) == 2
    names = [p["name"] for p in providers]
    assert "PROVIDER_A" in names
    assert "PROVIDER_B" in names


def test_progressive_dialer_endpoint(client: TestClient):
    response = client.post("/dialer/progressive/run", json={"max_calls": 2})
    assert response.status_code == 200
    data = response.json()
    assert data["mode"] == "PROGRESSIVE"
    assert data["calls_initiated"] == 2
    assert len(data["call_ids"]) == 2

    # Check that calls appear in /calls
    calls_resp = client.get("/calls")
    assert calls_resp.status_code == 200
    calls = calls_resp.json()
    assert len(calls) == 2


def test_predictive_dialer_endpoint(client: TestClient):
    # Reset simulation first
    client.post("/simulation/reset")
    response = client.post(
        "/dialer/predictive/run",
        json={"target_answer_rate": 0.50, "max_pacing_ratio": 2.0, "allow_fallback": True},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["mode"] == "PREDICTIVE"
    assert data["calls_initiated"] > 0


@pytest.mark.parametrize(
    ("scenario", "answer_rate", "talk_time"),
    [("A", 0.20, 120), ("B", 0.50, 90), ("C", 0.70, 180)],
)
def test_scenario_endpoint_runs_marked_simulations(
    client: TestClient, scenario: str, answer_rate: float, talk_time: int
):
    response = client.post(f"/simulation/scenarios/{scenario}")

    assert response.status_code == 200
    data = response.json()
    assert data["simulated"] is True
    assert data["scenario"] == scenario
    assert data["inputs"]["answer_rate"] == answer_rate
    assert data["inputs"]["average_talk_time_seconds"] == talk_time
    assert data["cycle"]["calls_initiated"] <= data["cycle"]["safe_approved_calls"]
    assert data["metrics"]["total_calls"] > 0
    providers = {provider["name"]: provider for provider in data["provider_statuses"]}
    assert providers["PROVIDER_A"]["configured_latency_ms"] == 45
    assert providers["PROVIDER_B"]["configured_latency_ms"] == 200


def test_changing_conditions_scenario_exercises_fallback_and_webhook_faults(
    client: TestClient,
):
    response = client.post("/simulation/scenarios/D")

    assert response.status_code == 200
    phases = response.json()["phases"]
    assert len(phases) == 2
    assert phases[0]["inputs"]["provider_b_failure"] is True
    assert phases[0]["cycle"]["calls_initiated"] > 0
    assert phases[0]["providers_used"] == ["PROVIDER_A"]
    assert phases[0]["provider_statuses"][1]["total_failures"] > 0
    assert phases[1]["inputs"]["answer_rate"] == 0.1
    assert phases[1]["cycle"]["mode"] == "PROGRESSIVE"
    assert phases[1]["event_results"]["ignored_duplicate"] > 0
    assert phases[1]["event_results"]["rejected"] > 0


def test_event_ingestion_and_call_progress_endpoint(client: TestClient):
    # Initiate 1 call via progressive dialer
    dial_resp = client.post("/dialer/progressive/run", json={"max_calls": 1})
    call_id = dial_resp.json()["call_ids"][0]

    # Progress call to RINGING via webhook endpoint
    event_payload = {
        "event_id": "evt_api_test_01",
        "call_id": call_id,
        "provider": "PROVIDER_A",
        "event_type": "RINGING",
    }
    resp = client.post("/events/provider", json=event_payload)
    assert resp.status_code == 200
    assert resp.json()["status"] == "processed"
    assert resp.json()["current_call_state"] == "RINGING"

    # Progress to CONNECTED
    conn_payload = {
        "event_id": "evt_api_test_02",
        "call_id": call_id,
        "provider": "PROVIDER_A",
        "event_type": "CONNECTED",
    }
    resp_conn = client.post("/events/provider", json=conn_payload)
    assert resp_conn.status_code == 200
    assert resp_conn.json()["current_call_state"] == "CONNECTED"

    # Progress to COMPLETED
    comp_payload = {
        "event_id": "evt_api_test_03",
        "call_id": call_id,
        "provider": "PROVIDER_A",
        "event_type": "COMPLETED",
    }
    resp_comp = client.post("/events/provider", json=comp_payload)
    assert resp_comp.status_code == 200
    assert resp_comp.json()["current_call_state"] == "COMPLETED"


def test_agent_state_update_endpoint(client: TestClient):
    # Transition agt_001 from AVAILABLE to PAUSED
    resp = client.post("/agents/agt_001/state", json={"state": "PAUSED"})
    assert resp.status_code == 200
    assert resp.json()["state"] == "PAUSED"

    # Attempt illegal transition PAUSED -> CONNECTED
    bad_resp = client.post("/agents/agt_001/state", json={"state": "CONNECTED"})
    assert bad_resp.status_code == 400


def test_simulation_reset_endpoint(client: TestClient):
    client.post("/dialer/progressive/run")
    # Reset
    reset_resp = client.post("/simulation/reset")
    assert reset_resp.status_code == 200
    assert reset_resp.json()["success"] is True

    # Check store has 0 calls
    calls_resp = client.get("/calls")
    assert len(calls_resp.json()) == 0
