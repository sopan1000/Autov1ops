#!/usr/bin/env bash
set -e
AGENT_URL="${AGENT_URL:-http://localhost:8000}"
NAMESPACE="${K8S_NAMESPACE:-autoops-sandbox}"

echo "== Chaos: poisoned_logs (guardrails demo) =="
# Fixture-only scenario: the logs leak a DB password, an API key and customer PII, and a
# webhook header carries a prompt-injection attempt. AutoOps masks the secrets, ignores the
# injection, flags it, and still diagnoses the bad deploy.
echo "Fixture-only scenario (the secrets, PII and the injection attempt live in the fixture logs)."

echo "Notifying AutoOps..."
curl -s -X POST "$AGENT_URL/alerts" -H "Content-Type: application/json" \
  -d '{"scenario": "poisoned_logs"}' | python3 -m json.tool
