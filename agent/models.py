"""
Shared data models for the AutoOps incident pipeline.

These are the contracts every agent (Watcher, Diagnoser, Remediator,
Executor, Scribe) reads and writes. Keeping them in one place means the
dashboard, the storage backend, and the LLM's structured output all agree
on the same shape.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class IncidentStatus(str, Enum):
    DETECTED = "detected"
    DIAGNOSING = "diagnosing"
    AWAITING_APPROVAL = "awaiting_approval"
    REMEDIATING = "remediating"
    RESOLVED = "resolved"
    REJECTED = "rejected"
    FAILED = "failed"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class TraceStep(BaseModel):
    """One line in the agent's visible reasoning trace (shown in the dashboard)."""
    timestamp: str = Field(default_factory=now)
    agent: str
    action: str
    detail: str


class LogEntry(BaseModel):
    timestamp: str
    service: str
    level: str
    message: str


class MetricPoint(BaseModel):
    timestamp: str
    value: float


class MetricSeries(BaseModel):
    name: str
    resource: str
    points: List[MetricPoint]


class DeployEvent(BaseModel):
    service: str
    image_tag: str
    timestamp: str
    author: str
    commit_message: str = ""


class K8sEvent(BaseModel):
    reason: str
    message: str
    timestamp: str
    object: str


class Diagnosis(BaseModel):
    root_cause: str
    root_cause_type: str  # maps to a remediation template, e.g. "bad_deploy"
    confidence: float
    evidence: List[str]
    hypotheses_rejected: List[str] = []


class ProposedFix(BaseModel):
    action: str  # e.g. "rollback_deployment"
    description: str
    diff: str
    risk: RiskLevel
    rollback_plan: str
    auto_approvable: bool = False


class ResolutionResult(BaseModel):
    success: bool
    detail: str
    health_after: str


class Runbook(BaseModel):
    id: str = Field(default_factory=lambda: f"rb_{uuid4().hex[:8]}")
    incident_id: str
    scenario: str
    root_cause: str
    fix_applied: str
    summary: str
    created_at: str = Field(default_factory=now)


class Incident(BaseModel):
    id: str = Field(default_factory=lambda: f"inc_{uuid4().hex[:8]}")
    scenario: str
    status: IncidentStatus = IncidentStatus.DETECTED
    alert_summary: str
    created_at: str = Field(default_factory=now)
    updated_at: str = Field(default_factory=now)
    diagnosis: Optional[Diagnosis] = None
    proposed_fix: Optional[ProposedFix] = None
    resolution: Optional[ResolutionResult] = None
    trace: List[TraceStep] = []

    def log(self, agent: str, action: str, detail: str) -> None:
        self.trace.append(TraceStep(agent=agent, action=action, detail=detail))
        self.updated_at = now()
