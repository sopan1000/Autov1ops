# Architecture

## The pipeline

```
Cloud Monitoring alert ─► Pub/Sub ─► /events/pubsub   (or POST /alerts from a chaos script)
                                         │
                                     Watcher: creates the incident
                                         │
          ┌──────────────── ADK SequentialAgent (Gemini) ────────────────┐
          │ investigator         tools: query_logs, get_metrics,          │
          │   (LlmAgent + tools)  get_recent_deploys, get_cluster_events,  │
          │                       search_runbooks  → findings              │
          │ diagnoser            structured output: root cause, type,      │
          │   (LlmAgent)          confidence, evidence, rejected hypotheses│
          │ remediation_planner  structured output: ONE fix_id from the    │
          │   (LlmAgent)          allowlisted catalog + justification      │
          └───────────────────────────────────────────────────────────────┘
                                         │
                                Remediator: validates fix_id, builds the fix
                                         │
                       human approval (dashboard / Slack), or escalation
                                         │
                       Executor: applies fix, verifies deployment health
                                         │
                       Scribe (Gemini): postmortem + runbook for next time

Ask AutoOps (Gemini): answers follow-up questions on any incident.
```

Code: `agent/adk_pipeline.py` (agents, tools, prompts),
`agent/agents/*.py` (stages), `agent/agents/orchestrator.py` (flows).

## Design principles

1. **The agent decides what to look at.** The investigator is an ADK
   `LlmAgent` with tools, not a prompt stuffed with every log line. It
   chooses which evidence to pull and in what order, and each call shows up
   in the incident's reasoning trace (`tool_call` / `tool_result` steps).

2. **Structured outputs between agents.** The diagnoser and planner use ADK
   `output_schema` (Pydantic models), so ADK validates their output before
   anything downstream uses it. Agents hand results to each other through
   ADK session state (`output_key` → the next agent's instruction).

3. **AI proposes; it never executes or writes commands.** The planner's
   `fix_id` field is a `Literal` of the catalog keys in
   `agent/agents/remediator.py`. A value outside the catalog fails schema
   validation (covered by `tests/test_adk_pipeline.py`). Each catalog entry
   maps to an action/target pair that the Kubernetes adapter checks again
   against its own allowlist before doing anything. `escalate` is always an
   option, so when no safe fix applies the system hands off instead of guessing.

4. **Humans approve by default.** Fixes wait in `awaiting_approval`.
   Optional policy (`AUTO_REMEDIATE=true`) auto-applies only fixes that are
   marked low-risk, chosen by Gemini (never the offline engine), at or above
   `AUTO_REMEDIATE_MIN_CONFIDENCE` (default 0.9).

5. **Degrade, don't fail.** If Gemini is disabled or errors (quota,
   network, bad output), the incident falls back to the offline engine
   (`agent/offline_engine.py`), and both the trace and the dashboard say so.
   The offline engine pattern-matches four known signatures and escalates
   anything else, which is exactly what the `cert_expiry` scenario shows.

6. **Mock and real tools share one interface.** Each evidence source is an
   interface in `agent/tools/base.py` with a fixture-backed `Mock*` class and
   a real GCP class in `agent/tools/cloud.py`. `MOCK_TOOLS` picks the set in
   one place (`agent/tools/__init__.py`), and no agent code branches on it.

## Data protection and prompt-injection guardrails

`agent/guardrails.py` sits between production data and everything else.

- **Masking.** Every tool result is masked inside the tool, before ADK hands it
  to Gemini. The same masking runs on the offline engine's evidence, on alert
  text from the API or Pub/Sub, and on engineers' Ask questions. It covers private
  keys, JWTs, Google/AWS/GitHub/Slack/Stripe keys, credentials in connection
  strings and `key=value` pairs, emails, card numbers (Luhn-checked), Aadhaar
  (Verhoeff-checked), PAN, Indian phone numbers and public IPs. Internal IPs,
  timestamps, metric values and job IDs are left alone, because engineers need them.
- **Output scrubbing.** An ADK `after_model_callback` scrubs every Gemini reply
  before ADK records it, so nothing sensitive can pass between agents or into
  storage even if a model echoed it. Every trace line is scrubbed as it is written.
- **Prompt injection.** Prompts tell every agent that tool data is untrusted and
  never to follow instructions inside it. Lines that look like instructions to the
  AI are flagged on the incident, shown to the engineer, and block auto-remediation.
  The fix allowlist still bounds what any injected text could achieve.
- **Visibility.** Each incident records what was masked (`guardrails.masked`) and
  any flagged lines (`guardrails.injection_flags`). The dashboard shows both.

`tests/test_guardrails.py` proves that no raw secret from the `poisoned_logs`
scenario reaches the model, storage or an Ask answer. For production, Google
Cloud Sensitive Data Protection or Model Armor could replace or back up the
regex rules.

## Testing the AI wiring without Gemini

`tests/test_adk_pipeline.py` runs the real ADK agents with a scripted model
in place of Gemini. Everything else is real: tool execution against fixture
data, session-state handoff between agents, schema validation, remediation,
execution and postmortem. Reasoning quality against real Gemini is checked
by `scripts/gemini_smoke_test.py`.

## Storage

`agent/store.py` defines `IncidentStore` with two implementations:
- `LocalJSONStore`: one JSON file (`agent/data/db.json`), process-local lock.
  For local dev and `docker-compose up` only.
- `FirestoreStore`: collections `incidents` and `runbooks`. Use it on Cloud Run
  (`STORE_BACKEND=firestore`), where container disks don't persist.

## Why GKE for the sandbox but Cloud Run for the agent

The sandbox app needs to visibly crash-loop, get OOMKilled and be rolled
back, which is a more literal demonstration on Kubernetes. The agent is a
stateless FastAPI service, so Cloud Run is the simpler, cheaper and
rule-compliant choice for it. It also serves the dashboard at `/ui`.

## Production control points

1. **Ingress**: Cloud Monitoring → Pub/Sub → `/events/pubsub`, verified with a
   Pub/Sub OIDC token whose audience is a fixed Cloud Run custom audience.
   Human/API traffic is protected with `AUTOOPS_API_KEY`, or put behind IAP.
2. **Idempotency**: Pub/Sub message IDs are stored as `source_event_id`;
   redeliveries return the existing incident.
3. **Remediation boundary**: see principle 3.
4. **Approval state machine**: only `awaiting_approval` incidents can be
   approved or rejected; terminal incidents can't be executed again.
5. **Recovery verification**: a fix only counts once the target deployment
   reports the desired number of ready, updated replicas.
6. **Runtime identity**: Google ADC and the Kubernetes API, with no kubeconfig
   or `kubectl` in the image.

### Dashboard authentication

For a public demo, the API runs without `AUTOOPS_API_KEY` and only on
fixture data (see docs/DEPLOY.md). For real use, put the dashboard behind
an identity-aware proxy (IAP or an authenticated backend) rather than
embedding a key in browser JavaScript.

## Known limitations

- The offline engine only knows four failure signatures; it's a fallback,
  not the product.
- `LocalJSONStore` has no real concurrency control.
- In fixture mode, applying a fix and verifying health are simulated; with
  `MOCK_TOOLS=false` both run against the real cluster.
- Live-cluster mode depends on how Cloud Monitoring alerts are labelled
  (the Pub/Sub message must carry a `scenario` attribute).
