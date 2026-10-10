#!/usr/bin/env bash
set -e
AGENT_URL="${AGENT_URL:-http://localhost:8000}"
NAMESPACE="${K8S_NAMESPACE:-autoops-sandbox}"

echo "== Chaos: vendor_outage (external outage) =="
# Fixture-only scenario: an external provider outage. The right answer is to escalate: no
# allowlisted action can fix someone else's outage.
echo "Fixture-only scenario (the sandbox has no external payment provider to break)."

echo "Notifying AutoOps..."
curl -s -X POST "$AGENT_URL/alerts" -H "Content-Type: application/json" \
  -d '{"scenario": "vendor_outage"}' | python3 -m json.tool
