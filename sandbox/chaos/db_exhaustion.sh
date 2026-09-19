#!/usr/bin/env bash
set -e
AGENT_URL="${AGENT_URL:-http://localhost:8000}"
NAMESPACE="${K8S_NAMESPACE:-autoops-sandbox}"

echo "== Chaos: db_exhaustion =="
if command -v kubectl &>/dev/null && kubectl config current-context &>/dev/null 2>&1; then
  echo "Live kubectl context found - deploying the batch-jobs image with LEAK_DB_CONNECTIONS=true..."
  kubectl set image "deployment/worker" "worker=gcr.io/${GCP_PROJECT:-your-project}/autoops-sandbox-worker:v2.5-batch-jobs" -n "$NAMESPACE"
  kubectl set env "deployment/worker" LEAK_DB_CONNECTIONS=true -n "$NAMESPACE"
else
  echo "No live kubectl context - running against the fixture-driven pipeline only."
fi

echo "Notifying AutoOps..."
curl -s -X POST "$AGENT_URL/alerts" -H "Content-Type: application/json" \
  -d '{"scenario": "db_exhaustion"}' | python3 -m json.tool
