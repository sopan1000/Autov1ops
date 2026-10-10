"""
Offline engine: what AutoOps falls back to when Gemini is disabled or
unreachable. It keeps the demo and local development working with no
network access, and it is labelled as such everywhere it appears.

It pattern-matches known failure signatures in the same evidence the
Gemini investigator would see. It cannot handle failure types outside its
four signatures (try the cert_expiry scenario): those are escalated to a
human. That gap is exactly what the Gemini pipeline (agent/adk_pipeline.py)
closes.
"""
from __future__ import annotations

import re

from .models import Diagnosis, Incident

ENGINE_LABEL = "offline heuristic (Gemini disabled)"

_SIGNATURES = [
    {
        "type": "oom_leak",
        "patterns": [r"OOMKilled", r"out of memory", r"memory_usage_bytes"],
        "label": "repeated OOMKilled events with a climbing memory metric",
    },
    {
        "type": "db_exhaustion",
        "patterns": [r"remaining connection slots", r"could not obtain connection", r"db_active_connections"],
        "label": "database connection pool exhaustion",
    },
    {
        "type": "bad_config",
        "patterns": [r"could not translate host name", r"ConfigMap .* updated", r"config-only"],
        "label": "a config value changed just before the failures started",
    },
    {
        "type": "bad_deploy",
        "patterns": [r"CrashLoopBackOff", r"KeyError", r"Unhandled exception"],
        "label": "a new deploy immediately followed by crashing/erroring pods",
    },
]


def diagnose(context: str) -> Diagnosis:
    scores = []
    for sig in _SIGNATURES:
        hits = [p for p in sig["patterns"] if re.search(p, context, re.IGNORECASE)]
        if hits:
            scores.append((sig, hits))

    if not scores:
        return Diagnosis(
            root_cause="No known failure signature matched the available signals.",
            root_cause_type="unknown",
            confidence=0.2,
            evidence=["No log/metric pattern in the known signature set was found."],
            hypotheses_rejected=[],
        )

    scores.sort(key=lambda s: len(s[1]), reverse=True)
    best_sig, best_hits = scores[0]
    rejected = [f"Considered {s['label']} - fewer matching signals" for s, _ in scores[1:]]

    evidence = []
    lines = context.splitlines()
    for pattern in best_hits:
        line = next((ln.strip() for ln in lines if re.search(pattern, ln, re.IGNORECASE)), "")
        if line:
            evidence.append(line[:300])

    confidence = min(0.95, 0.55 + 0.12 * len(best_hits))

    return Diagnosis(
        root_cause=f"Offline heuristic matched a known signature: {best_sig['label']}. Enable Gemini for a specific root cause.",
        root_cause_type=best_sig["type"],
        confidence=round(confidence, 2),
        evidence=evidence or [f"Matched signature: {best_sig['label']}"],
        hypotheses_rejected=rejected,
    )



def postmortem(incident: Incident) -> str:
    d, f, r = incident.diagnosis, incident.proposed_fix, incident.resolution
    return (
        f"## Summary\n{incident.alert_summary}\n\n"
        f"## Root cause\n{d.root_cause}\n\n"
        f"## Resolution\n{f.description} ({f.diff}). {r.detail}. Health after: {r.health_after}.\n\n"
        f"_Template postmortem from the offline engine. Enable Gemini for a full write-up._"
    )


def answer(incident: Incident, question: str) -> str:
    parts = ["Gemini is disabled, so this is a summary of the incident record rather than an answer to your exact question."]
    if incident.diagnosis:
        parts.append(f"Root cause: {incident.diagnosis.root_cause}")
        if incident.diagnosis.evidence:
            parts.append("Evidence: " + " | ".join(incident.diagnosis.evidence[:3]))
    if incident.proposed_fix:
        parts.append(f"Chosen fix: {incident.proposed_fix.fix_id} - {incident.proposed_fix.justification}")
    return "\n".join(parts)
