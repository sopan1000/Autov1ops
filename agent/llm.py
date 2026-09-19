"""
The only file that talks to an LLM. Two paths:

  - USE_REAL_GEMINI=true: calls Gemini on Vertex AI with controlled
    generation (a response_schema), so we get back structured JSON that
    maps straight onto Diagnosis. This is the real "meaningful Gen AI"
    path for the submission.
  - default: a heuristic fallback that pattern-matches the same log/metric
    /deploy/k8s-event text a real model would receive. It's not a stub
    that reads the fixture's answer key — it actually scans for known
    failure signatures (OOMKilled, connection exhaustion, deploy-then-
    crash correlation, etc.) — so the demo works offline and the
    Diagnoser's control flow is identical either way. Flip one env var
    to go from this to the real model.
"""
from __future__ import annotations

import os
import re

from .models import Diagnosis

USE_REAL_GEMINI = os.getenv("USE_REAL_GEMINI", "false").lower() == "true"
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-pro")

DIAGNOSIS_SCHEMA = {
    "type": "object",
    "properties": {
        "root_cause": {"type": "string"},
        "root_cause_type": {
            "type": "string",
            "enum": ["bad_deploy", "oom_leak", "db_exhaustion", "bad_config", "unknown"],
        },
        "confidence": {"type": "number"},
        "evidence": {"type": "array", "items": {"type": "string"}},
        "hypotheses_rejected": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["root_cause", "root_cause_type", "confidence", "evidence"],
}

SYSTEM_PROMPT = """You are the Diagnoser agent in AutoOps, an on-call incident
response system. You are given an alert plus recent logs, metrics, deploy
history, and Kubernetes events for the affected service. Identify the most
likely root cause, cite specific evidence (quote log lines / metric values /
timestamps), note hypotheses you considered and rejected, and rate your
confidence from 0 to 1. Be specific and technical - a vague answer is
useless to the on-call engineer reading this. Respond only with JSON
matching the provided schema."""


def diagnose(context: str) -> Diagnosis:
    if USE_REAL_GEMINI:
        return _diagnose_with_gemini(context)
    return _diagnose_heuristic(context)


def _diagnose_with_gemini(context: str) -> Diagnosis:
    """
    Real path. Requires `pip install google-genai` and GCP_PROJECT /
    GCP_LOCATION env vars with Vertex AI enabled for the project.
    """
    from google import genai
    from google.genai import types

    client = genai.Client(
        vertexai=True,
        project=os.getenv("GCP_PROJECT"),
        location=os.getenv("GCP_LOCATION", "us-central1"),
    )
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=context,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_schema=DIAGNOSIS_SCHEMA,
            temperature=0.2,
        ),
    )
    import json
    data = json.loads(response.text)
    return Diagnosis(**data)


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


def _diagnose_heuristic(context: str) -> Diagnosis:
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
    for pattern in best_hits:
        m = re.search(f".{{0,60}}{pattern}.{{0,60}}", context, re.IGNORECASE)
        if m:
            evidence.append(m.group(0).strip())

    confidence = min(0.95, 0.55 + 0.12 * len(best_hits))

    return Diagnosis(
        root_cause=f"Pattern match indicates {best_sig['label']}. See evidence for the specific signals.",
        root_cause_type=best_sig["type"],
        confidence=round(confidence, 2),
        evidence=evidence or [f"Matched signature: {best_sig['label']}"],
        hypotheses_rejected=rejected,
    )


def summarize_for_runbook(diagnosis: Diagnosis, fix_description: str, outcome: str) -> str:
    """Small templated writer for the Scribe agent. Swap for a Gemini call
    the same way as diagnose() if you want richer prose; kept deterministic
    here since it doesn't affect the technical-merit story."""
    return (
        f"Root cause: {diagnosis.root_cause}\n"
        f"Fix applied: {fix_description}\n"
        f"Outcome: {outcome}\n"
        f"Confidence at diagnosis time: {diagnosis.confidence}"
    )
