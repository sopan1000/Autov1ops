"""
AutoOps agents built on Google's Agent Development Kit (ADK) and Gemini.

Incident pipeline (an ADK SequentialAgent):

  1. investigator         LlmAgent WITH TOOLS. Decides for itself which
                          evidence to pull (logs, metrics, deploys, cluster
                          events, past runbooks) and writes up findings.
  2. diagnoser            LlmAgent with a structured output schema. Turns the
                          findings into a root cause with cited evidence,
                          rejected hypotheses and a confidence score.
  3. remediation_planner  LlmAgent with a structured output schema. Picks ONE
                          fix from the allowlisted catalog (or "escalate") and
                          justifies it. It cannot invent commands.

Separate single-purpose agents:
  - scribe       writes the postmortem after a verified resolution
  - ask_autoops  answers an engineer's follow-up questions about an incident

Gemini access: set GOOGLE_API_KEY (AI Studio key, quickest for local tests)
or run on GCP with Vertex AI (GCP_PROJECT / GCP_LOCATION, uses the service
account). Pass a custom `model` (any ADK BaseLlm) to drive the agents from
tests without network access - see tests/test_adk_pipeline.py.
"""
from __future__ import annotations

import asyncio
import json
import os
import threading
from typing import Any, List, Literal, Union

from google.adk.agents import LlmAgent, SequentialAgent
from google.adk.models.base_llm import BaseLlm
from google.adk.runners import InMemoryRunner
from google.adk.tools import ToolContext
from google.genai import types
from pydantic import BaseModel, Field

from .agents.remediator import FIX_CATALOG, catalog_for_prompt
from .models import DEFAULT_GEMINI_MODEL
from .tools import deploy_source, k8s_source, log_source, metrics_source, runbook_search

APP_NAME = "autoops"
GEMINI_MODEL = os.getenv("GEMINI_MODEL", DEFAULT_GEMINI_MODEL)
GEMINI_DIAGNOSIS_MODEL = os.getenv("GEMINI_DIAGNOSIS_MODEL", GEMINI_MODEL)

ModelLike = Union[str, BaseLlm]


def configure_gemini_env() -> None:
    """Use Vertex AI on GCP unless an AI Studio API key is provided."""
    if os.getenv("GOOGLE_API_KEY"):
        os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "FALSE")
        return
    os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "TRUE")
    if os.getenv("GCP_PROJECT"):
        os.environ.setdefault("GOOGLE_CLOUD_PROJECT", os.environ["GCP_PROJECT"])
    os.environ.setdefault("GOOGLE_CLOUD_LOCATION", os.getenv("GCP_LOCATION", "us-central1"))


def engine_label() -> str:
    if GEMINI_DIAGNOSIS_MODEL != GEMINI_MODEL:
        return f"{GEMINI_DIAGNOSIS_MODEL} + {GEMINI_MODEL} via ADK"
    return f"{GEMINI_MODEL} via ADK"


# ---------------------------------------------------------------------------
# Structured outputs
# ---------------------------------------------------------------------------

class DiagnosisOutput(BaseModel):
    root_cause: str = Field(description="Specific, technical root cause. Name the service, change and mechanism.")
    root_cause_type: str = Field(description="Short snake_case category, e.g. bad_deploy, oom_leak, tls_cert_expiry.")
    confidence: float = Field(ge=0.0, le=1.0, description="0 to 1.")
    evidence: List[str] = Field(description="Quoted log lines, metric values or events with timestamps.")
    hypotheses_rejected: List[str] = Field(description="Other explanations considered, and why each was ruled out.")


FixId = Literal[tuple(FIX_CATALOG.keys())]  # type: ignore[valid-type]


class PlanOutput(BaseModel):
    fix_id: FixId = Field(description="Exactly one fix from the catalog.")
    justification: str = Field(description="Why this fix addresses the root cause, in two or three sentences.")
    alternatives_rejected: List[str] = Field(description="Other catalog fixes considered and why they were not chosen.")


# ---------------------------------------------------------------------------
# Tools for the investigator (closures over the incident store)
# ---------------------------------------------------------------------------

def _make_tools(store) -> list:
    def query_logs(service: str, tool_context: ToolContext) -> dict:
        """Fetch recent log lines. service: 'api', 'worker', or '' for all services."""
        logs = log_source.query_logs(tool_context.state["scenario"], service=service)
        return {"logs": [l.model_dump() for l in logs[-200:]]}

    def get_metrics(metric: str, tool_context: ToolContext) -> dict:
        """Fetch metric time series. metric: a metric name, or '' for every available series."""
        series = metrics_source.get_metrics(tool_context.state["scenario"], metric=metric)
        return {"metrics": [s.model_dump() for s in series]}

    def get_recent_deploys(service: str, tool_context: ToolContext) -> dict:
        """List recent deployments and config changes. service: 'api', 'worker', or '' for all."""
        deploys = deploy_source.get_recent_deploys(tool_context.state["scenario"], service=service)
        return {"deploys": [d.model_dump() for d in deploys]}

    def get_cluster_events(tool_context: ToolContext) -> dict:
        """List recent Kubernetes events (crash loops, OOM kills, failed probes) in the app namespace."""
        events = k8s_source.get_events(tool_context.state["scenario"])
        return {"events": [e.model_dump() for e in events]}

    def search_runbooks(query: str, tool_context: ToolContext) -> dict:
        """Search runbooks written for past incidents. Use keywords from the symptoms."""
        hits = runbook_search.search(query, store)
        return {"runbooks": [r.model_dump(include={"scenario", "root_cause", "fix_applied", "summary"}) for r in hits]}

    return [query_logs, get_metrics, get_recent_deploys, get_cluster_events, search_runbooks]


# ---------------------------------------------------------------------------
# Prompts (callables, so state values are inserted verbatim with no
# template parsing of braces inside log lines or JSON)
# ---------------------------------------------------------------------------

INVESTIGATOR_PROMPT = """You are the Investigator agent in AutoOps, an AI on-call engineer.
An alert has fired. Investigate it like a senior SRE:
- Pull evidence with your tools. Start broad (all logs, all metrics, recent deploys, cluster events),
  then narrow down. Always check recent deploys and config changes - most incidents follow a change.
- Search past runbooks for similar symptoms.
- Correlate timestamps: what changed just before the symptoms started?
- Do not stop at the first symptom; find the upstream cause (a failing api may be starved by the worker).
Finish with a concise findings report: timeline, key evidence quoted verbatim with timestamps,
your leading explanation, and alternatives you ruled out. Do not propose fixes."""


def _diagnoser_prompt(ctx) -> str:
    return (
        "You are the Diagnoser agent in AutoOps. Using ONLY the investigator's findings below, "
        "state the root cause precisely enough that an on-call engineer could act on it without "
        "re-investigating. Quote evidence verbatim with timestamps. Be honest about confidence: "
        "below 0.6 if the evidence is thin or contradictory.\n\n"
        f"ALERT: {ctx.state.get('alert', '')}\n\nINVESTIGATOR FINDINGS:\n{ctx.state.get('findings', '')}"
    )


def _planner_prompt(ctx) -> str:
    diagnosis = ctx.state.get("diagnosis", {})
    return (
        "You are the Remediation Planner agent in AutoOps. Choose exactly ONE fix from the catalog "
        "for the diagnosis below. You cannot run commands or invent fixes; the catalog is the only "
        "set of allowed actions. Prefer the smallest change that addresses the root cause, not the "
        "symptom. If no catalog fix addresses the root cause, or confidence is below 0.6, choose "
        "escalate.\n\nFIX CATALOG:\n"
        f"{catalog_for_prompt()}\n\nDIAGNOSIS:\n{json.dumps(diagnosis, indent=2, default=str)}"
    )


def build_incident_pipeline(store, model: ModelLike | None = None,
                            diagnosis_model: ModelLike | None = None) -> SequentialAgent:
    model = model or GEMINI_MODEL
    diagnosis_model = diagnosis_model or (model if not isinstance(model, str) else GEMINI_DIAGNOSIS_MODEL)
    investigator = LlmAgent(
        name="investigator",
        model=model,
        description="Gathers and correlates incident evidence using observability tools.",
        instruction=INVESTIGATOR_PROMPT,
        tools=_make_tools(store),
        output_key="findings",
        generate_content_config=types.GenerateContentConfig(temperature=0.2),
    )
    diagnoser = LlmAgent(
        name="diagnoser",
        model=diagnosis_model,
        description="Produces a structured root-cause diagnosis from the findings.",
        instruction=_diagnoser_prompt,
        include_contents="none",
        output_schema=DiagnosisOutput,
        output_key="diagnosis",
        generate_content_config=types.GenerateContentConfig(temperature=0.1),
    )
    planner = LlmAgent(
        name="remediation_planner",
        model=model,
        description="Chooses one allowlisted fix (or escalation) and justifies it.",
        instruction=_planner_prompt,
        include_contents="none",
        output_schema=PlanOutput,
        output_key="plan",
        generate_content_config=types.GenerateContentConfig(temperature=0.1),
    )
    return SequentialAgent(
        name="autoops_incident_pipeline",
        description="Investigate -> diagnose -> plan remediation.",
        sub_agents=[investigator, diagnoser, planner],
    )


# ---------------------------------------------------------------------------
# Running agents
# ---------------------------------------------------------------------------

AGENT_TIMEOUT_SECONDS = float(os.getenv("AGENT_TIMEOUT_SECONDS", "180"))

_loop: asyncio.AbstractEventLoop | None = None
_loop_lock = threading.Lock()


def _agent_loop() -> asyncio.AbstractEventLoop:
    """One long-lived event loop on a background thread for all agent runs.

    A fresh asyncio.run() per request closes its loop while the Gemini
    client still has HTTP connections to clean up, which floods the logs
    with "Event loop is closed" errors (notably on Windows). Keeping one loop
    alive avoids that and lets connections be reused.
    """
    global _loop
    with _loop_lock:
        if _loop is None or _loop.is_closed():
            _loop = asyncio.new_event_loop()
            threading.Thread(target=_loop.run_forever, name="autoops-adk-loop", daemon=True).start()
        return _loop


async def _run_agent_async(agent, state: dict, message: str):
    runner = InMemoryRunner(agent=agent, app_name=APP_NAME)
    try:
        session = await runner.session_service.create_session(app_name=APP_NAME, user_id="autoops", state=state)
        events = []
        async for event in runner.run_async(
            user_id="autoops",
            session_id=session.id,
            new_message=types.Content(role="user", parts=[types.Part(text=message)]),
        ):
            events.append(event)
        final = await runner.session_service.get_session(app_name=APP_NAME, user_id="autoops", session_id=session.id)
        return dict(final.state), events
    finally:
        await runner.close()


def _run_agent(agent, state: dict, message: str):
    """Run an agent from sync code (API handlers, scripts). Raises TimeoutError
    if Gemini doesn't finish in time; callers fall back to the offline engine."""
    future = asyncio.run_coroutine_threadsafe(_run_agent_async(agent, state, message), _agent_loop())
    try:
        return future.result(timeout=AGENT_TIMEOUT_SECONDS)
    except TimeoutError:
        future.cancel()
        raise TimeoutError(f"Gemini agents did not finish within {AGENT_TIMEOUT_SECONDS:.0f}s")


def _event_trace(events) -> List[tuple]:
    """Turn ADK events into (agent, action, detail) trace lines for the dashboard."""
    lines = []
    for ev in events:
        if not ev.content or not ev.content.parts:
            continue
        for part in ev.content.parts:
            if part.function_call:
                args = json.dumps(dict(part.function_call.args or {}), default=str)
                lines.append((ev.author, "tool_call", f"{part.function_call.name}({args})"))
            elif part.function_response:
                resp = part.function_response.response or {}
                sizes = ", ".join(f"{k}: {len(v)}" for k, v in resp.items() if isinstance(v, list))
                lines.append((ev.author, "tool_result", f"{part.function_response.name} returned {sizes or 'data'}"))
    return lines


def _as_dict(value: Any) -> dict:
    if isinstance(value, BaseModel):
        return value.model_dump()
    if isinstance(value, str):
        return json.loads(value)
    return dict(value or {})


def investigate(scenario: str, alert: str, store, model: ModelLike | None = None) -> dict:
    """Run the full ADK pipeline. Returns findings, diagnosis, plan and trace lines."""
    pipeline = build_incident_pipeline(store, model=model)
    state, events = _run_agent(pipeline, {"scenario": scenario, "alert": alert}, f"ALERT: {alert}")
    diagnosis = DiagnosisOutput(**_as_dict(state.get("diagnosis")))
    plan = PlanOutput(**_as_dict(state.get("plan")))
    return {
        "findings": str(state.get("findings", "")),
        "diagnosis": diagnosis.model_dump(),
        "plan": plan.model_dump(),
        "trace": _event_trace(events),
    }


def _single_turn_text(name: str, instruction: str, message: str, model: ModelLike | None) -> str:
    agent = LlmAgent(name=name, model=model or GEMINI_MODEL, instruction=instruction,
                     generate_content_config=types.GenerateContentConfig(temperature=0.3))
    _, events = _run_agent(agent, {}, message)
    texts = [p.text for ev in events if ev.content and ev.author == name
             for p in (ev.content.parts or []) if p.text]
    return "\n".join(texts).strip()


SCRIBE_PROMPT = """You are the Scribe agent in AutoOps. Write a blameless postmortem in Markdown with
these sections: Summary, Impact, Timeline, Root cause, Resolution, Detection and response
(what AutoOps did, and how long it took), Action items (2-4 concrete follow-ups to prevent
recurrence). Use only facts from the incident record provided. Be concise."""

ASK_PROMPT = """You are Ask AutoOps, answering an on-call engineer's question about one incident.
Answer from the incident record provided (evidence, diagnosis, chosen fix, rejected alternatives,
trace). Be direct and specific, quote evidence where it helps, and say plainly when the record
does not contain the answer. Keep answers under 150 words."""


def write_postmortem(incident_json: str, model: ModelLike | None = None) -> str:
    return _single_turn_text("scribe", SCRIBE_PROMPT, f"INCIDENT RECORD:\n{incident_json}", model)


def answer_question(incident_json: str, question: str, model: ModelLike | None = None) -> str:
    return _single_turn_text("ask_autoops", ASK_PROMPT,
                             f"INCIDENT RECORD:\n{incident_json}\n\nQUESTION: {question}", model)
