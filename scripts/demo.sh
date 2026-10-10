#!/usr/bin/env bash
# Scripted walkthrough for the live demo / recorded video. Fires each
# chaos scenario with a pause in between so there's time to talk over it.
# Run `docker-compose up` (or a local uvicorn) first.
set -e
AGENT_URL="${AGENT_URL:-http://localhost:8000}"
export AGENT_URL

pause() { echo; read -r -p "-- press enter to continue --" _ || sleep "${1:-3}"; }

echo "############################################"
echo "  AutoOps live demo"
echo "  Agent: $AGENT_URL"
echo "############################################"

curl -s "$AGENT_URL/health" | python3 -m json.tool
pause

echo
echo ">>> Scenario 1/5: bad_deploy (a code deploy references a config key that doesn't exist)"
bash "$(dirname "$0")/../sandbox/chaos/bad_deploy.sh"
pause

echo
echo ">>> Scenario 2/5: oom_leak (an unbounded cache eats the container's memory limit)"
bash "$(dirname "$0")/../sandbox/chaos/oom_leak.sh"
pause

echo
echo ">>> Scenario 3/5: db_exhaustion (a leaky batch job starves the API of DB connections)"
bash "$(dirname "$0")/../sandbox/chaos/db_exhaustion.sh"
pause

echo
echo ">>> Scenario 4/5: bad_config (a ConfigMap typo breaks DB connectivity)"
bash "$(dirname "$0")/../sandbox/chaos/bad_config.sh"
pause

echo
echo ">>> Scenario 5/5: cert_expiry - an incident type the offline engine has never seen"
echo "    Gemini off: escalates to a human. Gemini on: diagnoses the expired cert and picks rollback_api."
bash "$(dirname "$0")/../sandbox/chaos/cert_expiry.sh"

echo
echo "Open the dashboard to approve each fix and watch it resolve:"
echo "  http://localhost:3000  (or $AGENT_URL/ui)"
echo
echo "Runbook library after this run:"
curl -s "$AGENT_URL/runbooks" | python3 -c "
import json, sys
for rb in json.load(sys.stdin):
    print(f\"  - {rb['scenario']}: {rb['fix_applied']}\")
"
