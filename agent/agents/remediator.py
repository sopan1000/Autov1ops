"""
Remediator: turns a Diagnosis into a concrete, reviewable fix. Actions are
deliberately limited to a small allowlist (see FIX_TEMPLATES) rather than
letting the model invent arbitrary commands - this is the single biggest
reason a human on-call engineer would trust this system in production, and
it's worth saying explicitly in the pitch: the LLM proposes, it never
executes, and even what it can propose is constrained.
"""
from ..models import Incident, IncidentStatus, ProposedFix, RiskLevel

FIX_TEMPLATES = {
    "bad_deploy": dict(
        action="rollback_deployment",
        target="deployment/worker",
        risk=RiskLevel.LOW,
        description="Roll worker back to the last known-good image.",
        rollback_plan="If the rollback itself regresses health, re-apply the previous rollback (kubectl rollout undo again) and page the on-call engineer.",
        auto_approvable=True,
    ),
    "oom_leak": dict(
        action="rollback_deployment",
        target="deployment/worker",
        risk=RiskLevel.LOW,
        description="Roll back the deploy that introduced the unbounded memory growth.",
        rollback_plan="If memory is still climbing after rollback, scale replicas down to 1 and escalate - this indicates a leak outside the reverted change.",
        auto_approvable=True,
    ),
    "db_exhaustion": dict(
        action="rollback_deployment",
        target="deployment/worker",
        risk=RiskLevel.MEDIUM,
        description="Roll back the leaking deploy, then restart api pods to release the connections they're already holding.",
        rollback_plan="If connections stay pinned near the max after restart, manually terminate idle Cloud SQL sessions via `gcloud sql operations` and escalate.",
        auto_approvable=False,
    ),
    "bad_config": dict(
        action="revert_config",
        target="sandbox/k8s/configmap.yaml",
        risk=RiskLevel.LOW,
        description="Revert the ConfigMap to its last known-good value and let the readiness probe trigger a fresh rollout.",
        rollback_plan="If pods still fail readiness after the revert, the ConfigMap history is inspected manually - this suggests a second, unrelated change.",
        auto_approvable=True,
    ),
}

DEFAULT_TEMPLATE = dict(
    action="restart_pods",
    target="deployment/worker",
    risk=RiskLevel.MEDIUM,
    description="Root cause did not match a known template; restarting pods as a conservative first step.",
    rollback_plan="If the restart does not restore health, escalate immediately - this incident needs human investigation.",
    auto_approvable=False,
)


def run(incident: Incident, store) -> Incident:
    if not incident.diagnosis:
        incident.log("remediator", "skipped", "No diagnosis available; cannot propose a fix")
        incident.status = IncidentStatus.FAILED
        return incident

    template = FIX_TEMPLATES.get(incident.diagnosis.root_cause_type, DEFAULT_TEMPLATE)

    diff = f"kubectl rollout undo {template['target']}" if template["action"] == "rollback_deployment" \
        else f"kubectl apply -f {template['target']}" if template["action"] == "revert_config" \
        else f"kubectl rollout restart {template['target']}"

    fix = ProposedFix(
        action=template["action"],
        description=template["description"],
        diff=diff,
        risk=template["risk"],
        rollback_plan=template["rollback_plan"],
        auto_approvable=template["auto_approvable"],
    )
    incident.proposed_fix = fix
    incident.status = IncidentStatus.AWAITING_APPROVAL
    incident.log(
        "remediator", "fix_proposed",
        f"Proposed '{fix.action}' (risk: {fix.risk.value}) - {fix.description}",
    )
    if fix.auto_approvable:
        incident.log("remediator", "auto_approvable", "This fix qualifies for auto-approval under policy, but still awaits explicit sign-off in this demo")
    return incident
