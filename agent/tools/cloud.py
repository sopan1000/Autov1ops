"""
Real implementations of the tool interfaces, calling actual GCP services.
These are only imported/instantiated when MOCK_TOOLS=false, so the
google-cloud-* SDKs are optional dependencies for local dev.

Swap-in is the whole point: agents/diagnoser.py never knows whether it's
talking to Mock* or Cloud* — see tools/__init__.py.
"""
from __future__ import annotations

import os
import subprocess
from datetime import datetime, timedelta, timezone
from typing import List

from ..models import DeployEvent, K8sEvent, LogEntry, MetricPoint, MetricSeries
from .base import DeployHistorySource, K8sStateSource, LogSource, MetricsSource

GCP_PROJECT = os.getenv("GCP_PROJECT", "")
NAMESPACE = os.getenv("K8S_NAMESPACE", "autoops-sandbox")
GITHUB_REPO = os.getenv("GITHUB_REPO", "")  # e.g. "your-org/autoops"


class CloudLogSource(LogSource):
    """Cloud Logging. Requires roles/logging.viewer on the agent's service account."""

    def query_logs(self, scenario: str, service: str = "", minutes: int = 30) -> List[LogEntry]:
        from google.cloud import logging as cloud_logging

        client = cloud_logging.Client(project=GCP_PROJECT)
        since = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()
        filter_str = f'timestamp>="{since}"'
        if service:
            filter_str += f' AND resource.labels.container_name="{service}"'

        entries = []
        for entry in client.list_entries(filter_=filter_str, page_size=200):
            entries.append(LogEntry(
                timestamp=entry.timestamp.isoformat() if entry.timestamp else "",
                service=service or "unknown",
                level=str(entry.severity or "DEFAULT"),
                message=str(entry.payload),
            ))
        return entries


class CloudMetricsSource(MetricsSource):
    """Cloud Monitoring. Requires roles/monitoring.viewer."""

    def get_metrics(self, scenario: str, metric: str = "", minutes: int = 30) -> List[MetricSeries]:
        from google.cloud import monitoring_v3

        client = monitoring_v3.MetricServiceClient()
        project_name = f"projects/{GCP_PROJECT}"
        now = datetime.now(timezone.utc)
        interval = monitoring_v3.TimeInterval(
            end_time={"seconds": int(now.timestamp())},
            start_time={"seconds": int((now - timedelta(minutes=minutes)).timestamp())},
        )
        metric_filter = f'metric.type="{metric}"' if metric else 'metric.type starts_with "custom.googleapis.com"'
        results = client.list_time_series(
            request={
                "name": project_name,
                "filter": metric_filter,
                "interval": interval,
                "view": monitoring_v3.ListTimeSeriesRequest.TimeSeriesView.FULL,
            }
        )
        series = []
        for ts in results:
            points = [MetricPoint(timestamp=p.interval.end_time.isoformat(), value=p.value.double_value)
                      for p in ts.points]
            series.append(MetricSeries(name=ts.metric.type, resource=str(ts.resource.labels), points=points))
        return series


class GitHubDeployHistorySource(DeployHistorySource):
    """Recent deploys, inferred from git commit/tag history via the GitHub API."""

    def get_recent_deploys(self, scenario: str, service: str = "") -> List[DeployEvent]:
        import requests

        token = os.getenv("GITHUB_TOKEN", "")
        headers = {"Authorization": f"token {token}"} if token else {}
        url = f"https://api.github.com/repos/{GITHUB_REPO}/commits"
        resp = requests.get(url, headers=headers, params={"per_page": 10}, timeout=10)
        resp.raise_for_status()
        deploys = []
        for c in resp.json():
            deploys.append(DeployEvent(
                service=service or "unknown",
                image_tag=c["sha"][:7],
                timestamp=c["commit"]["author"]["date"],
                author=c["commit"]["author"]["name"],
                commit_message=c["commit"]["message"],
            ))
        return deploys


class KubectlStateSource(K8sStateSource):
    """
    Reads live cluster state via kubectl, and applies remediations the same
    way. Requires the agent's service account to have Workload Identity
    bound with namespace-scoped RBAC (see infra/terraform/iam.tf) — kept
    deliberately narrow: this account can only touch autoops-sandbox.
    """

    def get_events(self, scenario: str, namespace: str = NAMESPACE) -> List[K8sEvent]:
        out = subprocess.run(
            ["kubectl", "get", "events", "-n", namespace, "-o", "json"],
            capture_output=True, text=True, timeout=15,
        )
        if out.returncode != 0:
            return []
        import json as _json
        events = []
        for item in _json.loads(out.stdout).get("items", []):
            events.append(K8sEvent(
                reason=item.get("reason", ""),
                message=item.get("message", ""),
                timestamp=item.get("lastTimestamp", ""),
                object=item.get("involvedObject", {}).get("name", ""),
            ))
        return events

    def apply_action(self, scenario: str, action: str, diff: str) -> str:
        # Deliberately an allowlist, not "run whatever the model says": the
        # Remediator can only ever request one of these four verbs. See
        # agents/remediator.py for where the allowlist is enforced.
        if action == "rollback_deployment":
            target = diff.strip()  # e.g. "deployment/worker"
            cmd = ["kubectl", "rollout", "undo", target, "-n", NAMESPACE]
        elif action == "restart_pods":
            cmd = ["kubectl", "rollout", "restart", diff.strip(), "-n", NAMESPACE]
        elif action == "scale_replicas":
            cmd = ["kubectl", "scale", diff.strip(), "-n", NAMESPACE]
        elif action == "revert_config":
            cmd = ["kubectl", "apply", "-f", diff.strip(), "-n", NAMESPACE]
        else:
            raise ValueError(f"Action '{action}' is not on the remediation allowlist")

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            raise RuntimeError(f"kubectl command failed: {result.stderr}")
        return result.stdout
