"""
Diagnoser stage. Two engines behind one entry point:

  - Gemini via ADK (USE_REAL_GEMINI=true): the investigator agent chooses
    which tools to call, the diagnoser agent writes a structured root
    cause, and the remediation planner picks a fix from the allowlist.
    See agent/adk_pipeline.py.
  - Offline heuristic (default, or automatic fallback if Gemini errors):
    gathers all evidence up front and pattern-matches known signatures.

Returns the incident plus a remediation plan (empty for offline mode, in
which case the remediator applies its offline rule).
"""
from __future__ import annotations

import os
from typing import Optional, Tuple

from .. import offline_engine
from ..models import Diagnosis, Incident, IncidentStatus
from ..tools import deploy_source, k8s_source, log_source, metrics_source, runbook_search


def gemini_enabled() -> bool:
    return os.getenv("USE_REAL_GEMINI", "false").lower() == "true"


def run(incident: Incident, store, model=None) -> Tuple[Incident, Optional[dict]]:
    incident.status = IncidentStatus.DIAGNOSING
    if gemini_enabled() or model is not None:
        try:
            return _run_gemini(incident, store, model)
        except Exception as exc:  # noqa: BLE001 - any Gemini/ADK failure falls back, never blocks the incident
            incident.log("diagnoser", "gemini_unavailable",
                         f"Gemini pipeline failed ({type(exc).__name__}: {str(exc)[:300]}); falling back to offline engine")
    return _run_offline(incident, store), None


def _run_gemini(incident: Incident, store, model) -> Tuple[Incident, dict]:
    from .. import adk_pipeline  # imported lazily so offline mode never needs Gemini credentials

    adk_pipeline.configure_gemini_env()
    incident.log("investigator", "start", f"ADK pipeline started on {adk_pipeline.engine_label()}")
    result = adk_pipeline.investigate(incident.scenario, incident.alert_summary, store, model=model)
    incident.ai_engine = adk_pipeline.engine_label() if model is None else "test model via ADK"

    for agent, action, detail in result["trace"]:
        incident.log(agent, action, detail)
    if result["findings"]:
        incident.log("investigator", "findings", result["findings"][:4000])
    incident.log("diagnoser", "gemini_calls", f"{result['gemini_calls']} Gemini requests for this incident")

    d = result["diagnosis"]
    incident.diagnosis = Diagnosis(
        root_cause=d["root_cause"][:4000],
        root_cause_type=(d["root_cause_type"] or "unknown")[:64],
        confidence=d["confidence"],
        evidence=[e[:1000] for e in d["evidence"]][:20],
        hypotheses_rejected=[h[:1000] for h in d["hypotheses_rejected"]][:20],
    )
    _log_diagnosis(incident)
    return incident, result["plan"]


def _run_offline(incident: Incident, store) -> Incident:
    incident.ai_engine = offline_engine.ENGINE_LABEL
    incident.log("diagnoser", "gather_context",
                 "Querying logs, metrics, deploy history, and cluster events for the affected service")
    logs = log_source.query_logs(incident.scenario)
    metrics = metrics_source.get_metrics(incident.scenario, metric="")
    deploys = deploy_source.get_recent_deploys(incident.scenario)
    k8s_events = k8s_source.get_events(incident.scenario)
    past_runbooks = runbook_search.search(incident.alert_summary, store)
    incident.log("diagnoser", "tool_result",
                 f"Retrieved {len(logs)} log lines, {len(metrics)} metric series, "
                 f"{len(deploys)} deploy events, {len(k8s_events)} cluster events")
    if past_runbooks:
        incident.log("diagnoser", "runbook_match",
                     f"Found {len(past_runbooks)} related past incident(s) in the runbook library")

    context = _build_context(incident, logs, metrics, deploys, k8s_events, past_runbooks)
    incident.diagnosis = offline_engine.diagnose(context)
    _log_diagnosis(incident)
    return incident


def _log_diagnosis(incident: Incident) -> None:
    d = incident.diagnosis
    incident.log("diagnoser", "diagnosis", f"Root cause ({d.confidence:.0%} confidence): {d.root_cause}")
    for evidence in d.evidence:
        incident.log("diagnoser", "evidence", evidence)
    for hypothesis in d.hypotheses_rejected:
        incident.log("diagnoser", "hypothesis_rejected", hypothesis)


def _build_context(incident, logs, metrics, deploys, k8s_events, past_runbooks) -> str:
    lines = [f"ALERT: {incident.alert_summary}", ""]

    lines.append("RECENT LOGS:")
    for l in logs:
        lines.append(f"  [{l.timestamp}] {l.service} {l.level}: {l.message}")

    lines.append("")
    lines.append("METRICS:")
    for series in metrics:
        pts = ", ".join(f"{p.timestamp}={p.value}" for p in series.points)
        lines.append(f"  {series.name} ({series.resource}): {pts}")

    lines.append("")
    lines.append("RECENT DEPLOYS:")
    for d in deploys:
        lines.append(f"  [{d.timestamp}] {d.service} -> {d.image_tag} by {d.author}: {d.commit_message}")

    lines.append("")
    lines.append("CLUSTER EVENTS:")
    for e in k8s_events:
        lines.append(f"  [{e.timestamp}] {e.reason} on {e.object}: {e.message}")

    if past_runbooks:
        lines.append("")
        lines.append("RELATED PAST INCIDENTS:")
        for rb in past_runbooks:
            lines.append(f"  - {rb.scenario}: {rb.root_cause} (fix: {rb.fix_applied})")

    return "\n".join(lines)
