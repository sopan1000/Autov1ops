"""
Single place that decides mock vs. real tools, so nothing else in the
codebase has an if/else on MOCK_TOOLS. Set MOCK_TOOLS=false and fill in
GCP_PROJECT / GITHUB_REPO / kubectl context to point this at a real
cluster; everything else (agents, API routes, dashboard) is unchanged.
"""
import os

from .base import (
    MockDeployHistorySource,
    MockK8sStateSource,
    MockLogSource,
    MockMetricsSource,
    MockRunbookSearch,
)

MOCK_TOOLS = os.getenv("MOCK_TOOLS", "true").lower() == "true"

if MOCK_TOOLS:
    log_source = MockLogSource()
    metrics_source = MockMetricsSource()
    deploy_source = MockDeployHistorySource()
    k8s_source = MockK8sStateSource()
else:
    from .cloud import CloudLogSource, CloudMetricsSource, GitHubDeployHistorySource, KubectlStateSource
    log_source = CloudLogSource()
    metrics_source = CloudMetricsSource()
    deploy_source = GitHubDeployHistorySource()
    k8s_source = KubectlStateSource()

runbook_search = MockRunbookSearch()  # search logic is identical either way; it queries the store, not GCP
