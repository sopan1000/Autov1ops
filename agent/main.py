"""AutoOps API: authenticated incident intake, approval, and observability."""
from __future__ import annotations

import base64
import json
import os
import secrets
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .agents import orchestrator
from .agents.watcher import SCENARIO_ALERTS
from .slack_utils import build_incident_blocks, parse_interaction, verify_signature
from .store import get_store

app = FastAPI(title="AutoOps Agent API", version="1.0.0")

allowed_origins = [x.strip() for x in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",") if x.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
)

API_KEY = os.getenv("AUTOOPS_API_KEY", "")
PUBSUB_AUDIENCE = os.getenv("PUBSUB_AUDIENCE", "")


class AlertRequest(BaseModel):
    scenario: str = Field(min_length=1, max_length=64)
    alert_summary: str = Field(default="", max_length=2000)
    source_event_id: Optional[str] = Field(default=None, max_length=256)


class ApprovalRequest(BaseModel):
    approved: bool = True


class QuestionRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)


class PubSubMessage(BaseModel):
    data: Optional[str] = None
    messageId: Optional[str] = None
    attributes: dict[str, str] = Field(default_factory=dict)


class PubSubEnvelope(BaseModel):
    message: PubSubMessage
    subscription: Optional[str] = None


def require_api_key(authorization: Optional[str] = Header(default=None)) -> None:
    """Optional local-dev auth; mandatory when AUTOOPS_API_KEY is configured."""
    if not API_KEY:
        return
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    supplied = authorization.removeprefix("Bearer ").strip()
    if not secrets.compare_digest(supplied, API_KEY):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")


def _decode_pubsub_data(data: Optional[str]) -> dict:
    if not data:
        return {}
    try:
        return json.loads(base64.b64decode(data).decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(400, "Invalid Pub/Sub message data") from exc


def _verify_pubsub_oidc(request: Request) -> None:
    """Verify the push identity when an audience is configured."""
    if not PUBSUB_AUDIENCE:
        raise HTTPException(503, "PUBSUB_AUDIENCE is not configured")
    auth = request.headers.get("authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(401, "Missing Pub/Sub identity token")
    try:
        from google.oauth2 import id_token
        from google.auth.transport import requests as google_requests
        id_token.verify_oauth2_token(auth.removeprefix("Bearer "), google_requests.Request(), audience=PUBSUB_AUDIENCE)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(401, "Invalid Pub/Sub identity token") from exc


@app.get("/health")
def health():
    gemini = os.getenv("USE_REAL_GEMINI", "false").lower() == "true"
    model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    return {
        "status": "ok",
        "service": "autoops-agent",
        "store_backend": os.getenv("STORE_BACKEND", "local"),
        "ai_engine": f"{model} via ADK" if gemini else "offline heuristic (Gemini disabled)",
        "auto_remediate": os.getenv("AUTO_REMEDIATE", "false").lower() == "true",
    }


@app.get("/ready")
def ready():
    try:
        get_store().list_incidents()
        return {"status": "ready"}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(503, "Store unavailable") from exc


@app.get("/scenarios", dependencies=[Depends(require_api_key)])
def scenarios():
    return SCENARIO_ALERTS


def _create_alert(req: AlertRequest):
    if req.scenario not in SCENARIO_ALERTS:
        raise HTTPException(400, f"Unknown scenario '{req.scenario}'. Options: {list(SCENARIO_ALERTS)}")
    # source_event_id can be used by a persistent store for deduplication.
    # The local demo has no durable uniqueness index, so only accept it as metadata for now.
    return orchestrator.handle_alert(req.scenario, req.alert_summary, req.source_event_id)


@app.post("/alerts", dependencies=[Depends(require_api_key)])
def create_alert(req: AlertRequest):
    return _create_alert(req)


@app.post("/events/pubsub")
def pubsub_event(request: Request, envelope: PubSubEnvelope):
    _verify_pubsub_oidc(request)
    payload = _decode_pubsub_data(envelope.message.data)
    # Cloud Monitoring notification payloads vary by configuration. Keep the
    # contract explicit: the publisher must provide a scenario attribute or payload field.
    scenario = envelope.message.attributes.get("scenario") or payload.get("scenario")
    if not scenario:
        raise HTTPException(400, "Pub/Sub event missing scenario")
    summary = envelope.message.attributes.get("alert_summary") or payload.get("alert_summary", "")
    return _create_alert(AlertRequest(scenario=scenario, alert_summary=summary, source_event_id=envelope.message.messageId))


@app.get("/incidents", dependencies=[Depends(require_api_key)])
def list_incidents():
    return get_store().list_incidents()


@app.get("/incidents/{incident_id}", dependencies=[Depends(require_api_key)])
def get_incident(incident_id: str):
    incident = get_store().get_incident(incident_id)
    if not incident:
        raise HTTPException(404, "Incident not found")
    return incident


@app.post("/incidents/{incident_id}/approve", dependencies=[Depends(require_api_key)])
def approve(incident_id: str, req: ApprovalRequest):
    try:
        return orchestrator.handle_approval(incident_id, req.approved)
    except orchestrator.IncidentNotFoundError as exc:
        raise HTTPException(404, str(exc))
    except orchestrator.InvalidIncidentStateError as exc:
        raise HTTPException(409, str(exc))


@app.post("/incidents/{incident_id}/ask", dependencies=[Depends(require_api_key)])
def ask(incident_id: str, req: QuestionRequest):
    """Ask AutoOps a follow-up question about an incident."""
    try:
        return orchestrator.handle_question(incident_id, req.question)
    except orchestrator.IncidentNotFoundError as exc:
        raise HTTPException(404, str(exc))


@app.get("/runbooks", dependencies=[Depends(require_api_key)])
def list_runbooks():
    return get_store().list_runbooks()


@app.post("/slack/interactions")
async def slack_interactions(request: Request):
    body = await request.body()
    if not verify_signature(request.headers, body):
        raise HTTPException(401, "Invalid Slack signature")
    try:
        parsed = parse_interaction(body)
        orchestrator.handle_approval(parsed["incident_id"], parsed["action"] == "approve")
    except (ValueError, KeyError, IndexError) as exc:
        raise HTTPException(400, "Invalid or stale Slack interaction") from exc
    return {"ok": True}


@app.get("/slack/preview/{incident_id}", dependencies=[Depends(require_api_key)])
def slack_preview(incident_id: str):
    incident = get_store().get_incident(incident_id)
    if not incident:
        raise HTTPException(404, "Incident not found")
    return {"blocks": build_incident_blocks(incident)}


# Serve the dashboard from the same service, so one Cloud Run URL is the whole demo.
_DASHBOARD_DIR = Path(__file__).resolve().parent.parent / "dashboard"
if _DASHBOARD_DIR.is_dir():
    app.mount("/ui", StaticFiles(directory=_DASHBOARD_DIR, html=True), name="dashboard")

    @app.get("/", include_in_schema=False)
    def root():
        return RedirectResponse("/ui/")
