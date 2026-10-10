"""
Watcher: the entry point of the pipeline. In production this is invoked by
a Pub/Sub push subscription wired to a Cloud Monitoring alert policy (see
infra/terraform/pubsub.tf). Its only job is to turn an alert into an
Incident record so the rest of the pipeline has something to work with.
"""
from ..models import Incident, IncidentStatus

SCENARIO_ALERTS = {
    "bad_deploy": "worker service: 5xx-equivalent job failure rate spiking above 90%",
    "oom_leak": "worker service: pod restart count spiking, memory usage near container limit",
    "db_exhaustion": "api service: elevated error rate, DB connection pool near capacity",
    "bad_config": "api service: requests failing at the database layer since the last config change",
    # Not one of the offline engine's known signatures - shows what Gemini adds.
    "cert_expiry": "api service: checkout error rate 74%, mostly 502s on POST /checkout",
    # Rollback is the wrong answer for these two.
    "vendor_outage": "api service: checkout error rate 68%, mostly 503s on POST /checkout",
    "stuck_worker": "worker service: job queue depth 4,200 and climbing, throughput dropped to zero",
}


def watch(scenario: str, alert_summary: str = "", source_event_id: str | None = None) -> Incident:
    summary = alert_summary or SCENARIO_ALERTS.get(scenario, f"Unrecognized scenario '{scenario}'")
    incident = Incident(scenario=scenario, alert_summary=summary, source_event_id=source_event_id, status=IncidentStatus.DETECTED)
    incident.log("watcher", "alert_received", f"Alert received via Pub/Sub: {summary}")
    return incident
