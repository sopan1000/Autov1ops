#!/usr/bin/env bash
# Clears the local incident/runbook store so you can re-run the demo from
# a blank slate. Only touches the local-mode JSON file - safe to run
# anytime before a rehearsal or the real thing.
set -e
DB_PATH="${LOCAL_DB_PATH:-agent/data/db.json}"
rm -f "$DB_PATH"
echo "Cleared $DB_PATH - next incident will start a fresh dashboard."
