"""Kubernetes adapter tests with fake Kubernetes and GitHub clients (no cluster needed)."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent.tools import cloud

REPO_ROOT = Path(__file__).resolve().parent.parent


class FakeApps:
    def __init__(self):
        self.patches = []

    def patch_namespaced_deployment(self, name, namespace, body):
        self.patches.append((name, namespace, body))

    def read_namespaced_deployment(self, name, namespace):
        return SimpleNamespace(
            spec=SimpleNamespace(replicas=2),
            status=SimpleNamespace(ready_replicas=2, updated_replicas=2, unavailable_replicas=0),
        )


class FakeCore:
    def __init__(self):
        self.patches = []

    def patch_namespaced_config_map(self, name, namespace, body):
        self.patches.append((name, namespace, body))


@pytest.fixture
def adapter(monkeypatch):
    a = cloud.KubectlStateSource()
    a.apps, a.core = FakeApps(), FakeCore()
    monkeypatch.setattr(a, "_apps_api", lambda: a.apps)
    monkeypatch.setattr(a, "_core_api", lambda: a.core)
    monkeypatch.setattr(cloud, "GITHUB_REPO", "sopan1000/Autov1ops")
    manifest = (REPO_ROOT / "sandbox/k8s/configmap.yaml").read_text()
    calls = []

    def fake_get(url, headers=None, params=None, timeout=None):
        calls.append((url, params))
        return SimpleNamespace(text=manifest, raise_for_status=lambda: None)

    import requests
    monkeypatch.setattr(requests, "get", fake_get)
    a.github_calls = calls
    return a


def test_restore_config_applies_known_good_data_and_restarts_api(adapter):
    result = adapter.apply_action("bad_config", "restore_config", "configmap/api-config")
    name, ns, body = adapter.core.patches[0]
    assert (name, ns) == ("api-config", "autoops-sandbox")
    assert body == {"data": {"DB_HOST": "cloudsql-primary", "FEATURE_X_FLAG": "true"}}
    assert adapter.apps.patches[0][0] == "api"          # api restarted to load it
    assert adapter.github_calls[0][0].endswith("/contents/sandbox/k8s/configmap.yaml")
    assert adapter.github_calls[0][1] == {"ref": "main"}
    assert "restarted deployment/api" in result


@pytest.mark.parametrize("action,target", [
    ("rollback_deployment", "configmap/api-config"),
    ("restart_pods", "configmap/api-config"),
    ("restore_config", "deployment/api"),
    ("delete", "deployment/api"),
])
def test_actions_only_apply_to_their_allowed_targets(adapter, action, target):
    with pytest.raises(ValueError):
        adapter.apply_action("x", action, target)
    assert not adapter.core.patches and not adapter.apps.patches


def test_unknown_target_rejected(adapter):
    with pytest.raises(ValueError):
        adapter.apply_action("x", "restart_pods", "deployment/database")


def test_config_health_is_checked_on_its_consumer(adapter):
    result = adapter.verify_health("bad_config", "configmap/api-config", timeout_seconds=1)
    assert result["healthy"] is True


def test_restore_config_requires_github_repo(adapter, monkeypatch):
    monkeypatch.setattr(cloud, "GITHUB_REPO", "")
    with pytest.raises(RuntimeError, match="GITHUB_REPO"):
        adapter.apply_action("bad_config", "restore_config", "configmap/api-config")
    assert not adapter.core.patches
