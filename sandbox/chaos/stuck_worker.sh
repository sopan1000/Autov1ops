#!/usr/bin/env bash
set -e
AGENT_URL="${AGENT_URL:-http://localhost:8000}"
NAMESPACE="${K8S_NAMESPACE:-autoops-sandbox}"

echo "== Chaos: stuck_worker (deadlocked worker) =="
# Fixture-only scenario: a deadlocked worker with no recent deploy. The right answer is a
# restart, not a rollback.
echo "Fixture-only scenario (the sandbox worker has no lock to deadlock)."

echo "Notifying AutoOps..."
curl -s -X POST "$AGENT_URL/alerts" -H "Content-Type: application/json" \
  -d '{"scenario": "stuck_worker"}' | python3 -m json.tool
