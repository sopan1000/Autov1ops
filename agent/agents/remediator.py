"""
Remediator: turns a diagnosis into a concrete, reviewable fix.

Safety boundary: the AI never writes commands. The remediation planner
(Gemini, see agent/adk_pipeline.py) can only pick one fix_id from
FIX_CATALOG below, and must justify the choice. Every catalog entry maps to
an allowlisted action/target pair that the Kubernetes adapter validates
again before touching anything (agent/tools/cloud.py). "escalate" is always
available, so when no safe fix exists the system hands off to a human
instead of guessing.
"""
from __future__ import annotations

from typing import Optional

from ..models import Incident, IncidentStatus, ProposedFix, RiskLevel

FIX_CATALOG = {
    "rollback_worker": dict(
        action="rollback_deployment",
        target="deployment/worker",
        risk=RiskLevel.LOW,
        description="Roll the worker deployment back to its previous revision (image, env vars, mounted secrets). Does not undo edits to a ConfigMap's data.",
        rollback_plan="If health regresses after the rollback, roll forward again and page the on-call engineer.",
        auto_approvable=True,
        when="A recent worker deploy introduced the failure (crash loop, memory leak, connection leak).",
    ),
    "rollback_api": dict(
        action="rollback_deployment",
        target="deployment/api",
        risk=RiskLevel.LOW,
        description="Roll the api deployment back to its previous revision (image, env vars, mounted secrets). Does not undo edits to a ConfigMap's data.",
        rollback_plan="If health regresses after the rollback, roll forward again and page the on-call engineer.",
        auto_approvable=True,
        when="A recent api deploy (image, mounted secret or certificate change) introduced the failure.",
    ),
    "restart_api": dict(
        action="restart_pods",
        target="deployment/api",
        risk=RiskLevel.MEDIUM,
        description="Restart api pods to clear in-process state such as stuck connections. Pods reload the same config, so a restart alone does not fix a bad config value.",
        rollback_plan="If readiness stays unhealthy, stop automated remediation and inspect the configuration manually.",
        auto_approvable=False,
        when="The api is holding bad in-memory state (stuck connections) and nothing in its config or image is wrong.",
    ),
    "restore_api_config": dict(
        action="restore_config",
        target="configmap/api-config",
        risk=RiskLevel.LOW,
        description="Restore the api-config ConfigMap to the known-good version in Git, then restart the api to load it.",
        rollback_plan="If the api is still unhealthy, re-apply the previous ConfigMap values and escalate: the cause is not the config.",
        auto_approvable=True,
        when="A ConfigMap value (for example DB_HOST) was changed and the api broke right after.",
    ),
    "restart_worker": dict(
        action="restart_pods",
        target="deployment/worker",
        risk=RiskLevel.MEDIUM,
        description="Restart worker pods to clear stuck in-process state.",
        rollback_plan="If the worker fails again after restart, escalate - the cause is not transient.",
        auto_approvable=False,
        when="The worker is wedged or holding bad in-memory state with no recent bad deploy.",
    ),
    "escalate": dict(
        action="escalate",
        target="on-call",
        risk=RiskLevel.HIGH,
        description="No safe automated fix applies. Page the on-call engineer with the diagnosis attached.",
        rollback_plan="No automated change is made.",
        auto_approvable=False,
        when="Root cause is unclear, or the fix needs a change outside the allowlist (data, network, external vendor).",
    ),
}

# Offline mode (no Gemini): fix chosen from the heuristic's root-cause label.
OFFLINE_FIX_FOR_TYPE = {
    "bad_deploy": "rollback_worker",
    "oom_leak": "rollback_worker",
    "db_exhaustion": "rollback_worker",
    "bad_config": "restore_api_config",
}


def catalog_for_prompt() -> str:
    """Human-readable catalog for the planner prompt (no braces: ADK templating)."""
    lines = []
    for fix_id, t in FIX_CATALOG.items():
        lines.append(f"- {fix_id}: {t['description']} Use when: {t['when']} Risk: {t['risk'].value}.")
    return "\n".join(lines)


def _command_preview(action: str, target: str) -> str:
    if action == "rollback_deployment":
        return f"kubectl rollout undo {target}"
    if action == "restart_pods":
        return f"kubectl rollout restart {target}"
    if action == "restore_config":
        return "kubectl apply -f sandbox/k8s/configmap.yaml && kubectl rollout restart deployment/api"
    return "page on-call (no cluster change)"


def run(incident: Incident, store, plan: Optional[dict] = None) -> Incident:
    if not incident.diagnosis:
        incident.log("remediator", "skipped", "No diagnosis available; cannot propose a fix")
        incident.status = IncidentStatus.FAILED
        return incident

    plan = plan or {}
    fix_id = plan.get("fix_id") or OFFLINE_FIX_FOR_TYPE.get(incident.diagnosis.root_cause_type, "escalate")
    if fix_id not in FIX_CATALOG:
        incident.log("remediator", "rejected_plan", f"Planner proposed unknown fix '{fix_id}'; escalating instead")
        fix_id = "escalate"
    template = FIX_CATALOG[fix_id]

    justification = plan.get("justification") or (
        f"Offline rule: root cause '{incident.diagnosis.root_cause_type}' maps to '{fix_id}'."
    )
    fix = ProposedFix(
        fix_id=fix_id,
        action=template["action"],
        target=template["target"],
        description=template["description"],
        diff=_command_preview(template["action"], template["target"]),
        risk=template["risk"],
        rollback_plan=template["rollback_plan"],
        auto_approvable=template["auto_approvable"],
        justification=justification[:2000],
        alternatives_rejected=[a[:500] for a in plan.get("alternatives_rejected", [])][:5],
    )
    incident.proposed_fix = fix

    if fix_id == "escalate":
        incident.status = IncidentStatus.ESCALATED
        incident.log("remediator", "escalated", f"No safe automated fix. {justification}")
        return incident

    incident.status = IncidentStatus.AWAITING_APPROVAL
    incident.log("remediator", "fix_proposed", f"Proposed '{fix_id}' ({fix.action} on {fix.target}, risk: {fix.risk.value})")
    incident.log("remediator", "justification", justification)
    for alt in fix.alternatives_rejected:
        incident.log("remediator", "alternative_rejected", alt)
    return incident
