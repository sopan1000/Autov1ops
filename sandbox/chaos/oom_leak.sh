#!/usr/bin/env bash
set -e
AGENT_URL="${AGENT_URL:-http://localhost:8000}"
NAMESPACE="${K8S_NAMESPACE:-autoops-sandbox}"

echo "== Chaos: oom_leak =="
if command -v kubectl &>/dev/null && kubectl config current-context &>/dev/null 2>&1; then
  echo "Live kubectl context found - deploying the cache-experiment image with LEAK_MEMORY=true..."
  kubectl set image "deployment/worker" "worker=gcr.io/${GCP_PROJECT:-your-project}/autoops-sandbox-worker:v3.0-cache-experiment" -n "$NAMESPACE"
  kubectl set env "deployment/worker" LEAK_MEMORY=true -n "$NAMESPACE"
else
  echo "No live kubectl context - running against the fixture-driven pipeline only."
fi

echo "Notifying AutoOps..."
curl -s -X POST "$AGENT_URL/alerts" -H "Content-Type: application/json" \
  -d '{"scenario": "oom_leak"}' | python3 -m json.tool
