"""
Scribe: after a verified resolution, writes the postmortem (Gemini when
enabled, a template otherwise) and saves a runbook. The investigator
searches runbooks on the next incident, which is the "gets smarter over
time" loop.
"""
from __future__ import annotations

from .. import guardrails, offline_engine
from ..models import Incident, Runbook
from .diagnoser import gemini_enabled


def run(incident: Incident, store, model=None) -> Incident:
    if incident.status.value != "resolved":
        incident.log("scribe", "skipped", "Runbook is only created after verified resolution")
        return incident
    if not (incident.diagnosis and incident.proposed_fix and incident.resolution):
        incident.log("scribe", "skipped", "Incident is missing diagnosis, fix, or resolution - nothing to write up")
        return incident

    text = ""
    if gemini_enabled() or model is not None:
        try:
            from .. import adk_pipeline
            adk_pipeline.configure_gemini_env()
            record = incident.model_dump_json(exclude={"qa", "postmortem"})
            text = adk_pipeline.write_postmortem(record, model=model)
        except Exception as exc:  # noqa: BLE001
            incident.log("scribe", "gemini_unavailable", f"Postmortem via Gemini failed ({type(exc).__name__}); using template")
    incident.postmortem = guardrails.scrub(text or offline_engine.postmortem(incident))

    runbook = Runbook(
        incident_id=incident.id,
        scenario=incident.scenario,
        root_cause=incident.diagnosis.root_cause,
        fix_applied=incident.proposed_fix.description,
        summary=incident.postmortem[:8000],
    )
    store.save_runbook(runbook)
    incident.log("scribe", "postmortem_written", f"Postmortem written; runbook {runbook.id} saved for future incidents")
    return incident
