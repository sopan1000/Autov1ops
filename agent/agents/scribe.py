"""
Scribe: writes the postmortem and saves a runbook once an incident is
resolved. The runbook is indexed (via RunbookSearch, see tools/base.py)
so the Diagnoser can cite it on the next similar incident - this is the
"gets smarter over time" part of the pitch.
"""
from ..llm import summarize_for_runbook
from ..models import Incident, Runbook


def run(incident: Incident, store) -> Incident:
    if not (incident.diagnosis and incident.proposed_fix and incident.resolution):
        incident.log("scribe", "skipped", "Incident is missing diagnosis, fix, or resolution - nothing to write up")
        return incident

    summary = summarize_for_runbook(
        incident.diagnosis, incident.proposed_fix.description, incident.resolution.detail
    )
    runbook = Runbook(
        incident_id=incident.id,
        scenario=incident.scenario,
        root_cause=incident.diagnosis.root_cause,
        fix_applied=incident.proposed_fix.description,
        summary=summary,
    )
    store.save_runbook(runbook)
    incident.log("scribe", "runbook_written", f"Runbook {runbook.id} saved for future incidents of this type")
    return incident
