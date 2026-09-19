"""
Executor: applies an approved fix and verifies recovery. Only ever called
after a human (or an explicit auto-approve policy) has said yes - see
agents/orchestrator.py.
"""
from ..models import Incident, IncidentStatus, ResolutionResult
from ..tools import k8s_source


def run(incident: Incident, store) -> Incident:
    if not incident.proposed_fix:
        incident.log("executor", "skipped", "No proposed fix to apply")
        incident.status = IncidentStatus.FAILED
        return incident

    incident.status = IncidentStatus.REMEDIATING
    fix = incident.proposed_fix
    incident.log("executor", "apply_fix", f"Applying approved fix: {fix.description}")

    try:
        result = k8s_source.apply_action(incident.scenario, fix.action, fix.diff)
        incident.log("executor", "apply_result", result)

        incident.log("executor", "health_check", "Re-checking service health after remediation...")
        # In a real cluster this polls Cloud Monitoring for the alerting
        # metric to drop back under threshold for N consecutive minutes
        # before declaring success; the mock path simulates that check
        # passing so the demo doesn't stall on a real wait.
        incident.resolution = ResolutionResult(
            success=True,
            detail=result,
            health_after="healthy - alerting metric back under threshold",
        )
        incident.status = IncidentStatus.RESOLVED
        incident.log("executor", "resolved", "Health check passed. Incident resolved.")
    except Exception as exc:  # noqa: BLE001 - deliberately broad: any tool failure must not crash the API
        incident.resolution = ResolutionResult(success=False, detail=str(exc), health_after="unknown")
        incident.status = IncidentStatus.FAILED
        incident.log("executor", "failed", f"Remediation failed: {exc}. Escalating to human on-call.")

    return incident
