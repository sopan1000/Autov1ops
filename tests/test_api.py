import os

os.environ["MOCK_TOOLS"] = "true"
os.environ["STORE_BACKEND"] = "local"
os.environ["USE_REAL_GEMINI"] = "false"
os.environ["LOCAL_DB_PATH"] = "/tmp/autoops-test-db.json"
os.environ.pop("AUTOOPS_API_KEY", None)
os.environ["PUBSUB_AUDIENCE"] = "test-audience"

from fastapi.testclient import TestClient
from agent.main import app
from agent.store import LocalJSONStore


def setup_function():
    path = "/tmp/autoops-test-db.json"
    try:
        os.remove(path)
    except FileNotFoundError:
        pass


def test_create_incident_and_idempotency():
    client = TestClient(app)
    first = client.post("/alerts", json={"scenario": "bad_deploy", "source_event_id": "evt-1"})
    assert first.status_code == 200
    first_id = first.json()["id"]
    second = client.post("/alerts", json={"scenario": "bad_deploy", "source_event_id": "evt-1"})
    assert second.status_code == 200
    assert second.json()["id"] == first_id


def test_approval_is_not_repeatable():
    client = TestClient(app)
    created = client.post("/alerts", json={"scenario": "bad_deploy"}).json()
    incident_id = created["id"]
    approved = client.post(f"/incidents/{incident_id}/approve", json={"approved": True})
    assert approved.status_code == 200
    again = client.post(f"/incidents/{incident_id}/approve", json={"approved": True})
    assert again.status_code == 409


def test_unknown_scenario_rejected():
    client = TestClient(app)
    response = client.post("/alerts", json={"scenario": "does_not_exist"})
    assert response.status_code == 400


def test_approve_nonexistent_incident_returns_404():
    client = TestClient(app)
    response = client.post("/incidents/inc_does_not_exist/approve", json={"approved": True})
    assert response.status_code == 404
