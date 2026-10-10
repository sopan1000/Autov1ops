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
    """GKE state/remediation using the Kubernetes API and Google ADC.

    This avoids shipping gcloud/kubectl into the production container. The
    Cloud Run service account authenticates to the GKE API and Kubernetes RBAC
    restricts it to the AutoOps namespace.
    """
    ALLOWED_TARGETS = {"deployment/worker", "deployment/api", "configmap/api-config"}
    # Each action may only touch specific targets.
    ALLOWED_ACTIONS = {
        "rollback_deployment": {"deployment/worker", "deployment/api"},
        "restart_pods": {"deployment/worker", "deployment/api"},
        "restore_config": {"configmap/api-config"},
    }
    # A ConfigMap's health is judged by the deployment that consumes it.
    HEALTH_TARGET = {"configmap/api-config": "deployment/api"}
    CONFIG_CONSUMER = {"configmap/api-config": "api"}
    KNOWN_GOOD_CONFIG_PATH = os.getenv("KNOWN_GOOD_CONFIG_PATH", "sandbox/k8s/configmap.yaml")
    KNOWN_GOOD_CONFIG_REF = os.getenv("KNOWN_GOOD_CONFIG_REF", "main")

    def __init__(self):
        self.namespace = NAMESPACE
        self._api = None

    def _apps_api(self):
        if self._api:
            return self._api
        from google.auth import default
        from google.auth.transport.requests import Request
        from google.cloud import container_v1
        from kubernetes import client

        credentials, project = default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        credentials.refresh(Request())
        project_id = GCP_PROJECT or project
        container = container_v1.ClusterManagerClient(credentials=credentials)
        cluster = container.get_cluster(name=f"projects/{project_id}/locations/{os.getenv('GKE_LOCATION', os.getenv('GCP_LOCATION', 'us-central1'))}/clusters/{os.getenv('GKE_CLUSTER', 'autoops-sandbox')}")
        configuration = client.Configuration()
        configuration.host = f"https://{cluster.endpoint}"
        configuration.ssl_ca_cert = "/tmp/autoops-gke-ca.crt"
        with open(configuration.ssl_ca_cert, "wb") as fh:
            import base64
            fh.write(base64.b64decode(cluster.master_auth.cluster_ca_certificate))
        configuration.api_key = {"authorization": credentials.token}
        configuration.api_key_prefix = {"authorization": "Bearer"}
        self._api = client.AppsV1Api(client.ApiClient(configuration))
        return self._api

    def _core_api(self):
        from kubernetes import client
        apps = self._apps_api()
        return client.CoreV1Api(apps.api_client)

    def get_events(self, scenario: str, namespace: str = NAMESPACE) -> List[K8sEvent]:
        try:
            events = self._core_api().list_namespaced_event(namespace=namespace).items
        except Exception:
            return []
        return [K8sEvent(
            reason=e.reason or "",
            message=e.message or "",
            timestamp=(e.last_timestamp or e.event_time or datetime.now(timezone.utc)).isoformat(),
            object=e.involved_object.name or "",
        ) for e in events[-100:]]

    def _validate_target(self, target: str) -> str:
        target = target.strip()
        if target not in self.ALLOWED_TARGETS:
            raise ValueError(f"Target '{target}' is not on the remediation allowlist")
        return target

    def _known_good_configmap(self, name: str) -> dict:
        """Fetch the ConfigMap's known-good data from Git (the source of truth)."""
        import requests
        import yaml

        if not GITHUB_REPO:
            raise RuntimeError("GITHUB_REPO is not set; cannot fetch the known-good config from Git")
        token = os.getenv("GITHUB_TOKEN", "")
        headers = {"Accept": "application/vnd.github.raw+json"}
        if token:
            headers["Authorization"] = f"token {token}"
        url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{self.KNOWN_GOOD_CONFIG_PATH}"
        resp = requests.get(url, headers=headers, params={"ref": self.KNOWN_GOOD_CONFIG_REF}, timeout=10)
        resp.raise_for_status()
        for doc in yaml.safe_load_all(resp.text):
            if doc and doc.get("kind") == "ConfigMap" and doc.get("metadata", {}).get("name") == name:
                data = doc.get("data") or {}
                if not data or not all(isinstance(v, str) for v in data.values()):
                    raise RuntimeError(f"Known-good ConfigMap '{name}' in Git has no valid string data")
                return data
        raise RuntimeError(f"ConfigMap '{name}' not found in {self.KNOWN_GOOD_CONFIG_PATH}@{self.KNOWN_GOOD_CONFIG_REF}")

    def _restart(self, deployment_name: str) -> None:
        import time
        body = {"spec": {"template": {"metadata": {"annotations": {"autoops/restarted-at": str(time.time())}}}}}
        self._apps_api().patch_namespaced_deployment(deployment_name, self.namespace, body)

    def apply_action(self, scenario: str, action: str, target: str) -> str:
        target = self._validate_target(target)
        if target not in self.ALLOWED_ACTIONS.get(action, set()):
            raise ValueError(f"Action '{action}' is not allowed on '{target}'")
        name = target.split("/", 1)[1]
        if action == "restore_config":
            data = self._known_good_configmap(name)
            self._core_api().patch_namespaced_config_map(name, self.namespace, {"data": data})
            consumer = self.CONFIG_CONSUMER[target]
            self._restart(consumer)
            return (f"Restored {target} from {self.KNOWN_GOOD_CONFIG_PATH}@{self.KNOWN_GOOD_CONFIG_REF} "
                    f"({', '.join(sorted(data))}) and restarted deployment/{consumer}")
        api = self._apps_api()
        if action == "rollback_deployment":
            deployment = api.read_namespaced_deployment(name, self.namespace)
            selector = ",".join(f"{k}={v}" for k, v in (deployment.spec.selector.match_labels or {}).items())
            replicasets = api.list_namespaced_replica_set(self.namespace, label_selector=selector).items
            current_revision = int((deployment.metadata.annotations or {}).get("deployment.kubernetes.io/revision", "0"))
            candidates = []
            for rs in replicasets:
                owner = next((o for o in (rs.metadata.owner_references or []) if o.kind == "Deployment" and o.uid == deployment.metadata.uid), None)
                if not owner:
                    continue
                revision = int((rs.metadata.annotations or {}).get("deployment.kubernetes.io/revision", "0"))
                if revision < current_revision:
                    candidates.append((revision, rs))
            if not candidates:
                raise RuntimeError(f"No previous ReplicaSet found for {target}")
            previous_revision, previous_rs = max(candidates, key=lambda item: item[0])
            template = previous_rs.spec.template
            body = {"spec": {"template": template.to_dict()}}
            api.patch_namespaced_deployment(name, self.namespace, body)
            return f"Rolled {target} back to ReplicaSet revision {previous_revision}"
        if action == "restart_pods":
            self._restart(name)
            return f"Restart requested for {target}"
        raise ValueError(f"Action '{action}' is not enabled in production")

    def verify_health(self, scenario: str, target: str, timeout_seconds: int = 90):
        target = self.HEALTH_TARGET.get(target.strip(), target)
        target = self._validate_target(target)
        name = target.split("/", 1)[1]
        api = self._apps_api()
        import time
        deadline = time.time() + timeout_seconds
        attempts = 0
        while time.time() < deadline:
            attempts += 1
            obj = api.read_namespaced_deployment(name, self.namespace)
            status = obj.status
            desired = obj.spec.replicas or 0
            ready = status.ready_replicas or 0
            updated = status.updated_replicas or 0
            unavailable = status.unavailable_replicas or 0
            healthy = desired > 0 and ready == desired and updated == desired and unavailable == 0
            detail = f"deployment desired={desired}, ready={ready}, updated={updated}, unavailable={unavailable}"
            if healthy:
                return {"healthy": True, "detail": detail, "attempts": attempts}
            time.sleep(3)
        return {"healthy": False, "detail": "Timed out waiting for healthy deployment", "attempts": attempts}
