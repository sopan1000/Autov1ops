"""Shared, versioned contracts for the AutoOps incident pipeline."""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


# Default Gemini model. gemini-2.5-flash is closed to new API users (Oct 2026).
DEFAULT_GEMINI_MODEL = "gemini-3.8-flash"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class IncidentStatus(str, Enum):
    DETECTED = "detected"
    DIAGNOSING = "diagnosing"
    AWAITING_APPROVAL = "awaiting_approval"
    REMEDIATING = "remediating"
    VERIFYING = "verifying"
    RESOLVED = "resolved"
    ESCALATED = "escalated"  # no safe automated fix exists; handed to a human
    REJECTED = "rejected"
    FAILED = "failed"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class TraceStep(BaseModel):
    model_config = ConfigDict(extra="forbid")
    timestamp: str = Field(default_factory=now)
    agent: str = Field(min_length=1, max_length=64)
    action: str = Field(min_length=1, max_length=128)
    detail: str = Field(min_length=1, max_length=4000)


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
    root_cause: str = Field(min_length=1, max_length=4000)
    # Free-form category label (e.g. "bad_deploy", "tls_cert_expiry"). Gemini may
    # name failure types the offline heuristic has never seen; fix selection is
    # driven by the remediation planner, not by this label.
    root_cause_type: str = Field(min_length=1, max_length=64)
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: List[str] = Field(default_factory=list, max_length=20)
    hypotheses_rejected: List[str] = Field(default_factory=list, max_length=20)


class ProposedFix(BaseModel):
    """A safe remediation intent. `target` is data, never an executable command."""
    action: str
    target: str
    description: str
    diff: str
    risk: RiskLevel
    rollback_plan: str
    auto_approvable: bool = False
    fix_id: str = ""                 # key into remediator.FIX_CATALOG
    justification: str = ""          # why the planner chose this fix
    alternatives_rejected: List[str] = Field(default_factory=list)


class ResolutionResult(BaseModel):
    success: bool
    detail: str
    health_after: str
    verification_attempts: int = 0
    verified_at: Optional[str] = None


class QAEntry(BaseModel):
    question: str
    answer: str
    engine: str
    asked_at: str = Field(default_factory=now)


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
    source_event_id: Optional[str] = None
    created_at: str = Field(default_factory=now)
    updated_at: str = Field(default_factory=now)
    diagnosis: Optional[Diagnosis] = None
    proposed_fix: Optional[ProposedFix] = None
    resolution: Optional[ResolutionResult] = None
    trace: List[TraceStep] = Field(default_factory=list)
    ai_engine: str = ""              # which engine diagnosed this incident (shown in the dashboard)
    postmortem: str = ""
    qa: List[QAEntry] = Field(default_factory=list)

    def log(self, agent: str, action: str, detail: str) -> None:
        self.trace.append(TraceStep(agent=agent, action=action, detail=detail))
        self.updated_at = now()
