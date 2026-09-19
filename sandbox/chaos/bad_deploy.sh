#!/usr/bin/env bash
set -e
AGENT_URL="${AGENT_URL:-http://localhost:8000}"
NAMESPACE="${K8S_NAMESPACE:-autoops-sandbox}"

echo "== Chaos: bad_deploy =="
if command -v kubectl &>/dev/null && kubectl config current-context &>/dev/null 2>&1; then
  echo "Live kubectl context found - deploying worker:v2.3-broken and removing FEATURE_X_FLAG..."
  kubectl set image "deployment/worker" "worker=gcr.io/${GCP_PROJECT:-your-project}/autoops-sandbox-worker:v2.3-broken" -n "$NAMESPACE"
  kubectl set env "deployment/worker" FEATURE_X_FLAG- -n "$NAMESPACE"
else
  echo "No live kubectl context - running against the fixture-driven pipeline only."
fi

echo "Notifying AutoOps..."
curl -s -X POST "$AGENT_URL/alerts" -H "Content-Type: application/json" \
  -d '{"scenario": "bad_deploy"}' | python3 -m json.tool
