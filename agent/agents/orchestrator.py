"""
Orchestrator: wires the five agents into the two flows the API exposes -
handle_alert (Watcher -> Diagnoser -> Remediator, stops at "awaiting
approval") and handle_approval (Executor -> Scribe, or a rejection).
Kept as a SequentialAgent-style plain function rather than a framework
object so it's trivial to read; swapping this for google-adk's
SequentialAgent/LlmAgent classes is a drop-in change once the team wants
ADK's session/tracing features specifically.
"""
from ..models import IncidentStatus
from ..store import get_store
from . import diagnoser, executor, remediator, scribe, watcher


def handle_alert(scenario: str, alert_summary: str = ""):
    store = get_store()
    incident = watcher.watch(scenario, alert_summary)
    store.save_incident(incident)

    incident = diagnoser.run(incident, store)
    incident = remediator.run(incident, store)
    store.save_incident(incident)
    return incident


def handle_approval(incident_id: str, approved: bool):
    store = get_store()
    incident = store.get_incident(incident_id)
    if not incident:
        raise ValueError(f"No incident found with id '{incident_id}'")

    if not approved:
        incident.status = IncidentStatus.REJECTED
        incident.log("orchestrator", "rejected", "Fix rejected by on-call engineer; awaiting manual intervention")
        store.save_incident(incident)
        return incident

    incident.log("orchestrator", "approved", "Fix approved by on-call engineer")
    incident = executor.run(incident, store)
    incident = scribe.run(incident, store)
    store.save_incident(incident)
    return incident
