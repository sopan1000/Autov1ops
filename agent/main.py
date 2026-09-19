"""
FastAPI app: the single Cloud Run service that hosts the whole agent
pipeline. Endpoints:

  POST /alerts                    -> trigger Watcher -> Diagnoser -> Remediator
  GET  /incidents                 -> list incidents (newest first)
  GET  /incidents/{id}            -> one incident, with its full trace
  POST /incidents/{id}/approve    -> Executor -> Scribe (or reject)
  GET  /runbooks                  -> the accumulated runbook library
  POST /slack/interactions        -> Slack button webhook
  GET  /health                    -> readiness probe + current mode
"""
from __future__ import annotations

import os

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .agents import orchestrator
from .agents.watcher import SCENARIO_ALERTS
from .slack_utils import build_incident_blocks, parse_interaction, verify_signature
from .store import get_store

app = FastAPI(title="AutoOps Agent API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten to the dashboard's origin before a real prod deploy
    allow_methods=["*"],
    allow_headers=["*"],
)


class AlertRequest(BaseModel):
    scenario: str
    alert_summary: str = ""


class ApprovalRequest(BaseModel):
    approved: bool = True


@app.get("/health")
def health():
    return {
        "status": "ok",
        "mock_tools": os.getenv("MOCK_TOOLS", "true"),
        "use_real_gemini": os.getenv("USE_REAL_GEMINI", "false"),
        "store_backend": os.getenv("STORE_BACKEND", "local"),
    }


@app.get("/scenarios")
def scenarios():
    """What the chaos scripts / dashboard can trigger."""
    return SCENARIO_ALERTS


@app.post("/alerts")
def create_alert(req: AlertRequest):
    if req.scenario not in SCENARIO_ALERTS:
        raise HTTPException(400, f"Unknown scenario '{req.scenario}'. Options: {list(SCENARIO_ALERTS)}")
    return orchestrator.handle_alert(req.scenario, req.alert_summary)


@app.get("/incidents")
def list_incidents():
    return get_store().list_incidents()


@app.get("/incidents/{incident_id}")
def get_incident(incident_id: str):
    incident = get_store().get_incident(incident_id)
    if not incident:
        raise HTTPException(404, "Incident not found")
    return incident


@app.post("/incidents/{incident_id}/approve")
def approve(incident_id: str, req: ApprovalRequest):
    try:
        return orchestrator.handle_approval(incident_id, req.approved)
    except ValueError as exc:
        raise HTTPException(404, str(exc))


@app.get("/runbooks")
def list_runbooks():
    return get_store().list_runbooks()


@app.post("/slack/interactions")
async def slack_interactions(request: Request):
    body = await request.body()
    if not verify_signature(request.headers, body):
        raise HTTPException(401, "Invalid Slack signature")
    parsed = parse_interaction(body)
    try:
        orchestrator.handle_approval(parsed["incident_id"], parsed["action"] == "approve")
    except ValueError as exc:
        raise HTTPException(404, str(exc))
    return {"ok": True}


@app.get("/slack/preview/{incident_id}")
def slack_preview(incident_id: str):
    """Not a real Slack endpoint - lets you eyeball the Block Kit payload
    that WOULD be posted, without a Slack app configured."""
    incident = get_store().get_incident(incident_id)
    if not incident:
        raise HTTPException(404, "Incident not found")
    return {"blocks": build_incident_blocks(incident)}
