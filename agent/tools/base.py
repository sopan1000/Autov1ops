"""
Tool interfaces the Diagnoser agent calls. Every tool has two
implementations:

  - a Mock* class that reads from agent/data/mock_incidents/<scenario>.json
    so the full pipeline runs with zero GCP dependencies (this is what the
    hackathon demo and local dev use)
  - a Cloud* class that calls the real GCP API (Cloud Logging, Cloud
    Monitoring, GitHub, GKE)

Which set gets used is decided once, in tools/__init__.py, based on the
MOCK_TOOLS env var. The agent code never imports Mock* or Cloud* directly.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import List

from ..models import DeployEvent, K8sEvent, LogEntry, MetricSeries, MetricPoint, Runbook

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "data" / "mock_incidents"


def _load_fixture(scenario: str) -> dict:
    path = FIXTURE_DIR / f"{scenario}.json"
    with open(path) as f:
        return json.load(f)


class LogSource:
    def query_logs(self, scenario: str, service: str = "", minutes: int = 30) -> List[LogEntry]:
        raise NotImplementedError


class MetricsSource:
    def get_metrics(self, scenario: str, metric: str, minutes: int = 30) -> List[MetricSeries]:
        raise NotImplementedError


class DeployHistorySource:
    def get_recent_deploys(self, scenario: str, service: str = "") -> List[DeployEvent]:
        raise NotImplementedError


class K8sStateSource:
    def get_events(self, scenario: str, namespace: str = "autoops-sandbox") -> List[K8sEvent]:
        raise NotImplementedError

    def apply_action(self, scenario: str, action: str, diff: str) -> str:
        """Applies a remediation. Mock version simulates success; the real
        version shells out to kubectl / triggers Cloud Build."""
        raise NotImplementedError


class RunbookSearch:
    def search(self, query: str, store) -> List[Runbook]:
        raise NotImplementedError


class MockLogSource(LogSource):
    def query_logs(self, scenario: str, service: str = "", minutes: int = 30) -> List[LogEntry]:
        data = _load_fixture(scenario)
        logs = [LogEntry(**l) for l in data.get("logs", [])]
        if service:
            logs = [l for l in logs if l.service == service]
        return logs


class MockMetricsSource(MetricsSource):
    def get_metrics(self, scenario: str, metric: str = "", minutes: int = 30) -> List[MetricSeries]:
        data = _load_fixture(scenario)
        series = []
        for m in data.get("metrics", []):
            if metric and m["name"] != metric:
                continue
            series.append(MetricSeries(
                name=m["name"],
                resource=m["resource"],
                points=[MetricPoint(**p) for p in m["points"]],
            ))
        return series


class MockDeployHistorySource(DeployHistorySource):
    def get_recent_deploys(self, scenario: str, service: str = "") -> List[DeployEvent]:
        data = _load_fixture(scenario)
        deploys = [DeployEvent(**d) for d in data.get("deploys", [])]
        if service:
            deploys = [d for d in deploys if d.service == service]
        return deploys


class MockK8sStateSource(K8sStateSource):
    def get_events(self, scenario: str, namespace: str = "autoops-sandbox") -> List[K8sEvent]:
        data = _load_fixture(scenario)
        return [K8sEvent(**e) for e in data.get("k8s_events", [])]

    def apply_action(self, scenario: str, action: str, diff: str) -> str:
        # Simulated apply: in local/demo mode there's no real cluster to
        # mutate, so we just report success. The real K8sStateSource in
        # cloud.py shells out to kubectl for real.
        return f"[mock] applied '{action}' successfully (dry-run in local mode)"


class MockRunbookSearch(RunbookSearch):
    def search(self, query: str, store) -> List[Runbook]:
        query_terms = set(query.lower().split())
        results = []
        for rb in store.list_runbooks():
            haystack = f"{rb.scenario} {rb.root_cause} {rb.summary}".lower()
            if query_terms & set(haystack.split()):
                results.append(rb)
        return results[:3]
