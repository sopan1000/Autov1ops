"""
Orchestrator: wires the stages into the flows the API exposes.

  handle_alert     Watcher -> diagnosis pipeline (ADK/Gemini or offline)
                   -> Remediator. Stops at "awaiting approval" unless the
                   optional confidence-gated auto-remediation policy applies.
  handle_approval  Executor -> Scribe, or a rejection.
  handle_question  Ask AutoOps: answers a follow-up question on an incident.
"""
from __future__ import annotations

import os

from .. import offline_engine
from ..models import IncidentStatus, QAEntry
from ..store import get_store
from . import diagnoser, executor, remediator, scribe, watcher


class IncidentNotFoundError(ValueError):
    """No incident exists with the given id (maps to 404). Subclasses
    ValueError so existing `except ValueError` callers keep working."""


class InvalidIncidentStateError(ValueError):
    """The incident is not in a state that allows this operation (maps to 409)."""


def _auto_remediation_allowed(incident) -> bool:
    """Optional policy: apply low-risk fixes without a human when Gemini is
    very confident. Off by default so the demo shows the approval step."""
    if os.getenv("AUTO_REMEDIATE", "false").lower() != "true":
        return False
    threshold = float(os.getenv("AUTO_REMEDIATE_MIN_CONFIDENCE", "0.9"))
    fix, diag = incident.proposed_fix, incident.diagnosis
    return bool(fix and diag and fix.auto_approvable and diag.confidence >= threshold
                and incident.ai_engine != offline_engine.ENGINE_LABEL)


def handle_alert(scenario: str, alert_summary: str = "", source_event_id: str | None = None, model=None):
    store = get_store()
    if source_event_id:
        existing = store.find_by_source_event_id(source_event_id)
        if existing:
            existing.log("orchestrator", "deduplicated", f"Duplicate source event {source_event_id} ignored")
            store.save_incident(existing)
            return existing
    incident = watcher.watch(scenario, alert_summary, source_event_id)
    store.save_incident(incident)

    try:
        incident, plan = diagnoser.run(incident, store, model=model)
        incident = remediator.run(incident, store, plan)
    except Exception as exc:  # noqa: BLE001 - an incident must be persisted even when a dependency fails
        incident.status = IncidentStatus.FAILED
        incident.log("orchestrator", "pipeline_failed", f"Incident pipeline failed: {exc}")
    store.save_incident(incident)

    if incident.status == IncidentStatus.AWAITING_APPROVAL and _auto_remediation_allowed(incident):
        incident.log("orchestrator", "auto_approved",
                     f"Auto-approved by policy: low-risk fix at {incident.diagnosis.confidence:.0%} confidence")
        store.save_incident(incident)
        return handle_approval(incident.id, True, model=model, approver="policy")
    return incident


def handle_approval(incident_id: str, approved: bool, model=None, approver: str = "on-call engineer"):
    store = get_store()
    incident = store.get_incident(incident_id)
    if not incident:
        raise IncidentNotFoundError(f"No incident found with id '{incident_id}'")
    if incident.status != IncidentStatus.AWAITING_APPROVAL:
        raise InvalidIncidentStateError(
            f"Incident '{incident_id}' is not awaiting approval (status={incident.status.value})"
        )

    if not approved:
        incident.status = IncidentStatus.REJECTED
        incident.log("orchestrator", "rejected", f"Fix rejected by {approver}; awaiting manual intervention")
        store.save_incident(incident)
        return incident

    if approver != "policy":
        incident.log("orchestrator", "approved", f"Fix approved by {approver}")
    incident = executor.run(incident, store)
    incident = scribe.run(incident, store, model=model)
    store.save_incident(incident)
    return incident


def handle_question(incident_id: str, question: str, model=None):
    store = get_store()
    incident = store.get_incident(incident_id)
    if not incident:
        raise IncidentNotFoundError(f"No incident found with id '{incident_id}'")

    answer, engine = "", offline_engine.ENGINE_LABEL
    if diagnoser.gemini_enabled() or model is not None:
        try:
            from .. import adk_pipeline
            adk_pipeline.configure_gemini_env()
            record = incident.model_dump_json(exclude={"qa"})
            answer = adk_pipeline.answer_question(record, question, model=model)
            engine = adk_pipeline.engine_label() if model is None else "test model via ADK"
        except Exception as exc:  # noqa: BLE001
            incident.log("ask_autoops", "gemini_unavailable", f"Gemini failed ({type(exc).__name__}); answered offline")
    if not answer:
        answer, engine = offline_engine.answer(incident, question), offline_engine.ENGINE_LABEL

    incident.qa.append(QAEntry(question=question[:1000], answer=answer[:4000], engine=engine))
    store.save_incident(incident)
    return incident.qa[-1]
