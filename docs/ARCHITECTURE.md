# Architecture

## Design principles

1. **Mock and real tools share one interface.** Every external dependency
   (logs, metrics, deploy history, cluster state) is an abstract class in
   `agent/tools/base.py`, with a `Mock*` implementation reading fixture
   JSON and a `Cloud*` implementation in `agent/tools/cloud.py` calling the
   real GCP API. `agent/tools/__init__.py` picks one set based on
   `MOCK_TOOLS`. No agent code branches on this - it just calls
   `log_source.query_logs(...)` and gets an answer either way. This is
   what makes the demo runnable offline and the real deployment a config
   change, not a rewrite.

2. **The LLM call is isolated to one file.** `agent/llm.py` is the only
   place that imports a Gemini client. `diagnose(context: str) -> Diagnosis`
   either calls Gemini on Vertex AI with controlled generation (a JSON
   `response_schema`, so the output is guaranteed to parse into the
   `Diagnosis` model) or falls back to a heuristic scanner that pattern-
   matches the same context text for known failure signatures. This isn't
   a stub that reads the fixture's answer key - it genuinely scans
   `context` for strings like `OOMKilled` or `remaining connection slots`,
   so the demo's control flow is identical to the real-Gemini path.

3. **Remediation is an allowlist, not free-form execution.** The
   Remediator can only ever propose one of four actions (`rollback_deployment`,
   `restart_pods`, `scale_replicas`, `revert_config`), each with a fixed
   `kubectl` command shape. The LLM's job is choosing *which* template
   fits and writing the human-readable description - it does not generate
   arbitrary shell commands. This is a deliberate, defensible safety
   boundary worth stating explicitly in the pitch.

4. **Nothing executes without approval.** `agents/executor.py` is only
   ever called from `orchestrator.handle_approval(incident_id, approved=True)`.
   The dashboard and the Slack webhook are the only two callers of that
   function outside tests.

## Data flow, one incident at a time

1. `POST /alerts {"scenario": "oom_leak"}` (from a chaos script, or in
   prod from a Pub/Sub push subscription behind a Cloud Monitoring alert
   policy).
2. `watcher.watch()` creates an `Incident` with `status=detected` and logs
   the first trace step.
3. `diagnoser.run()`:
   - calls all four tool sources for the scenario's logs/metrics/deploys/
     cluster events, plus `runbook_search` against past incidents,
   - builds one text context block from all of it,
   - calls `llm.diagnose(context)`, which returns a `Diagnosis` (root
     cause, type, confidence, evidence, rejected hypotheses),
   - logs each piece to the incident's trace (this is what the dashboard's
     "agent reasoning trace" panel renders).
4. `remediator.run()` maps `diagnosis.root_cause_type` to a fix template,
   producing a `ProposedFix` with a `diff` (the literal command), a `risk`
   level, and a `rollback_plan`. Status moves to `awaiting_approval`.
5. The incident is now visible in the dashboard (and, in prod, posted to
   Slack via `slack_utils.build_incident_blocks`). A human clicks Approve
   or Reject.
6. On approval, `POST /incidents/{id}/approve` calls
   `orchestrator.handle_approval`, which runs `executor.run()` (applies
   the fix via `k8s_source.apply_action`, checks health, sets
   `resolved`/`failed`) and then `scribe.run()` (writes a `Runbook` to the
   store).
7. The next incident's `diagnoser.run()` searches the runbook library
   first - if a past incident matches, its summary is included in the
   LLM's context, which is the "gets smarter over time" story.

## Storage

`agent/store.py` defines `IncidentStore` with two implementations:
- `LocalJSONStore` - a single JSON file (`agent/data/db.json`), guarded by
  a process-local lock. Used for `docker-compose up` and local dev. Not
  meant to survive real concurrent load; it's a demo/dev convenience.
- `FirestoreStore` - real Firestore collections `incidents` and
  `runbooks`. Selected with `STORE_BACKEND=firestore`. This is what the
  dashboard would use `onSnapshot` real-time listeners against in a
  production deployment (the current dashboard polls instead, to avoid
  requiring Firebase SDK setup for the local demo).

## Why GKE for the sandbox but Cloud Run for the agent

The sandbox app needs to visibly crash-loop, get OOMKilled, and be rolled
back via `kubectl rollout undo` - that's a much more convincing, literal
demonstration on Kubernetes than it would be simulating the same on Cloud
Run. The agent itself has no such requirement - it's a stateless FastAPI
service reacting to HTTP requests - so Cloud Run is the simpler, cheaper,
and (per the hackathon rules) compliant choice for it specifically.

## Known limitations (worth stating honestly in the pitch)

- The heuristic diagnoser is a reasonable stand-in for the demo but is
  not a substitute for the real Gemini call in `USE_REAL_GEMINI=true` mode -
  it can't handle incident shapes outside its four known signatures.
- `LocalJSONStore` has no real concurrency control; fine for a demo, not
  for production incident volume.
- The Executor's health check after applying a fix is currently a fixed
  "assume success" in mock mode; the real `KubectlStateSource` path would
  need an actual polling loop against Cloud Monitoring before declaring
  victory - noted as a near-term hardening item, not implemented here due
  to hackathon time constraints.
