"""
Diagnoser: the core of AutoOps. Gathers evidence from logs, metrics,
deploy history, cluster events, and past runbooks, then asks the LLM
layer (agent/llm.py) to produce a structured root-cause Diagnosis.
"""
from ..llm import diagnose as llm_diagnose
from ..models import Incident, IncidentStatus
from ..tools import deploy_source, k8s_source, log_source, metrics_source, runbook_search


def run(incident: Incident, store) -> Incident:
    incident.status = IncidentStatus.DIAGNOSING
    incident.log("diagnoser", "gather_context",
                 "Querying logs, metrics, deploy history, and cluster events for the affected service")

    logs = log_source.query_logs(incident.scenario)
    metrics = metrics_source.get_metrics(incident.scenario, metric="")
    deploys = deploy_source.get_recent_deploys(incident.scenario)
    k8s_events = k8s_source.get_events(incident.scenario)
    past_runbooks = runbook_search.search(incident.alert_summary, store)

    incident.log(
        "diagnoser", "tool_result",
        f"Retrieved {len(logs)} log lines, {len(metrics)} metric series, "
        f"{len(deploys)} deploy events, {len(k8s_events)} cluster events",
    )
    if past_runbooks:
        incident.log(
            "diagnoser", "runbook_match",
            f"Found {len(past_runbooks)} related past incident(s) in the runbook library",
        )

    context = _build_context(incident, logs, metrics, deploys, k8s_events, past_runbooks)
    diagnosis = llm_diagnose(context)
    incident.diagnosis = diagnosis

    incident.log(
        "diagnoser", "diagnosis",
        f"Root cause ({diagnosis.confidence:.0%} confidence): {diagnosis.root_cause}",
    )
    for evidence in diagnosis.evidence:
        incident.log("diagnoser", "evidence", evidence)
    for hypothesis in diagnosis.hypotheses_rejected:
        incident.log("diagnoser", "hypothesis_rejected", hypothesis)

    return incident


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
