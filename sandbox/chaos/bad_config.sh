#!/usr/bin/env bash
set -e
AGENT_URL="${AGENT_URL:-http://localhost:8000}"
NAMESPACE="${K8S_NAMESPACE:-autoops-sandbox}"

echo "== Chaos: bad_config =="
if command -v kubectl &>/dev/null && kubectl config current-context &>/dev/null 2>&1; then
  echo "Live kubectl context found - introducing a DB_HOST typo into the ConfigMap..."
  kubectl set env "deployment/api" --from="configmap/api-config" -n "$NAMESPACE" 2>/dev/null || true
  kubectl patch configmap api-config -n "$NAMESPACE" --type merge -p '{"data":{"DB_HOST":"cloudsql-primry"}}'
  kubectl rollout restart "deployment/api" -n "$NAMESPACE"
else
  echo "No live kubectl context - running against the fixture-driven pipeline only."
fi

echo "Notifying AutoOps..."
curl -s -X POST "$AGENT_URL/alerts" -H "Content-Type: application/json" \
  -d '{"scenario": "bad_config"}' | python3 -m json.tool
