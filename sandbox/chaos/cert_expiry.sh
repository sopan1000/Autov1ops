#!/usr/bin/env bash
set -e
AGENT_URL="${AGENT_URL:-http://localhost:8000}"
NAMESPACE="${K8S_NAMESPACE:-autoops-sandbox}"

echo "== Chaos: cert_expiry (unseen incident type) =="
# The sandbox api has no real mTLS dependency, so this scenario always runs
# from fixture data, even when a live cluster is configured. Its purpose is
# to show an incident type the offline engine has never seen: with Gemini
# off it escalates; with Gemini on it should diagnose the expired cert and
# choose rollback_api.
echo "Fixture-only scenario (the sandbox app has no TLS dependency to break)."

echo "Notifying AutoOps..."
curl -s -X POST "$AGENT_URL/alerts" -H "Content-Type: application/json" \
  -d '{"scenario": "cert_expiry"}' | python3 -m json.tool
