"""Apply an approved remediation and verify the workload actually recovered."""
from ..models import Incident, IncidentStatus, ResolutionResult, now
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
        result = k8s_source.apply_action(incident.scenario, fix.action, fix.target)
        incident.log("executor", "apply_result", result or "Remediation command completed")
        incident.status = IncidentStatus.VERIFYING
        incident.log("executor", "health_check", f"Verifying {fix.target} recovery")

        verification = k8s_source.verify_health(incident.scenario, fix.target)
        incident.resolution = ResolutionResult(
            success=bool(verification["healthy"]),
            detail=result or "Remediation command completed",
            health_after=verification["detail"],
            verification_attempts=int(verification.get("attempts", 1)),
            verified_at=now() if verification["healthy"] else None,
        )
        if verification["healthy"]:
            incident.status = IncidentStatus.RESOLVED
            incident.log("executor", "resolved", "Post-remediation health verification passed.")
        else:
            incident.status = IncidentStatus.FAILED
            incident.log("executor", "verification_failed", "Remediation completed but recovery was not verified; escalating to on-call.")
    except Exception as exc:  # noqa: BLE001
        incident.resolution = ResolutionResult(success=False, detail=str(exc), health_after="unknown")
        incident.status = IncidentStatus.FAILED
        incident.log("executor", "failed", f"Remediation failed: {exc}. Escalating to human on-call.")
    return incident
