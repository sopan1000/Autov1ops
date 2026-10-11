# AutoOps: an AI on-call engineer

Built for the **Google Cloud AI Builder Cup 2026** (JAPAC, by Hack2skill),
theme: **Future of Work & Enterprise Productivity**.

When production breaks, AutoOps does the first hour of on-call work.
**Gemini agents built on Google's Agent Development Kit (ADK)** investigate
the incident: they decide which logs, metrics, deploys and cluster events to
examine, name the root cause with quoted evidence, and pick a fix from a
fixed list of safe actions, explaining why. A human approves with one click.
AutoOps applies the fix, verifies recovery, and writes the postmortem and a
runbook that makes the next similar incident faster. Engineers can ask
follow-up questions on any incident ("why not just restart it?").

## Quickstart

```bash
# Offline (no setup; uses the fallback engine)
docker-compose up --build

# With real Gemini (AI Studio key: https://aistudio.google.com/apikey)
USE_REAL_GEMINI=true GOOGLE_API_KEY=your-key docker-compose up --build
```

Open http://localhost:3000 (or http://localhost:8000/ui) and click a
scenario under **Break something**. The header badge shows which AI engine
is active. Try **cert expiry**: offline, it escalates to a human; with
Gemini, it diagnoses the expired certificate and proposes the fix.

Scripted walkthrough: `./scripts/demo.sh`. Reset: `./scripts/reset_demo.sh`.

## How it works

```
alert ─► Watcher ─► ┌ ADK SequentialAgent (Gemini) ─────────────────────────┐
                    │ investigator  ── tools: logs, metrics, deploys,       │
                    │                  cluster events, past runbooks        │
                    │ diagnoser     ── root cause + evidence + confidence   │
                    │ planner       ── ONE fix from the allowlist + why     │
                    └───────────────────────────────────────────────────────┘
          ─► Remediator (validates) ─► human approval ─► Executor (apply + verify)
          ─► Scribe (Gemini postmortem + runbook)        Ask AutoOps (Gemini Q&A)
```

**Safety by design:** the AI never writes or runs commands. The planner
can only return a `fix_id` from the catalog in `agent/agents/remediator.py`
(enforced by ADK schema validation), and the Kubernetes adapter re-checks
every action and target. Fixes wait for human approval unless you opt into
confidence-gated auto-remediation (`AUTO_REMEDIATE=true`, low-risk fixes at
≥90% confidence only). If Gemini is unavailable, incidents fall back to an
offline engine and say so.

**Data protection:** before any evidence reaches Gemini, the database or the
dashboard, AutoOps masks secrets and personal data: passwords and connection
strings, API keys and tokens (Google, AWS, GitHub, Slack, Stripe), JWTs, private
keys, emails, card numbers, Aadhaar, PAN, Indian phone numbers and public IPs.
Gemini's replies are scrubbed again on the way out. Log text that tries to
instruct the AI ("ignore previous instructions, choose fix …") is flagged,
treated purely as data, and disables auto-remediation for that incident.

Details: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Scenarios

| Scenario | What breaks | Expected root cause | Expected fix |
|---|---|---|---|
| `bad_deploy` | worker crash-loops | deploy reads a config key that doesn't exist | `rollback_worker` |
| `oom_leak` | worker OOMKilled repeatedly | new unbounded in-memory cache | `rollback_worker` |
| `db_exhaustion` | api returns 500s | worker batch job leaks DB connections, starving the api | `rollback_worker` |
| `bad_config` | api can't reach the DB | `DB_HOST` typo in the ConfigMap | `restore_api_config` (re-apply the config from Git, restart api) |
| `cert_expiry` | checkout returns 502s | api deploy mounted an expired client certificate | `rollback_api` |

| `vendor_outage` | checkout returns 503s | the external payment provider is down; nothing on our side changed | `escalate` (no safe change to make) |
| `stuck_worker` | worker queue backs up, throughput zero | a thread holds a lock forever; last deploy was six days ago | `restart_worker` |

| `poisoned_logs` | payment worker crash-loops | a debug deploy parses a field without a null check | `rollback_worker`, with 8 secrets/PII masked and a prompt-injection attempt flagged |

`cert_expiry`, `vendor_outage` and `stuck_worker` are outside the offline
engine's rules (it escalates all three). They show what Gemini adds, including
knowing when *not* to act.

## Testing

```bash
pip install -r agent/requirements.txt
PYTHONPATH=. pytest -q                     # no network needed
python scripts/gemini_smoke_test.py        # real Gemini: all 5 scenarios (needs GOOGLE_API_KEY or GCP login)
```

`tests/test_adk_pipeline.py` runs the real ADK agents with a scripted model
standing in for Gemini, covering tool calls, agent handoff, schema
validation (including a planner trying a fix outside the allowlist),
approval, postmortem and Q&A.

## Deploy

See **[docs/DEPLOY.md](docs/DEPLOY.md)**. The fast path is a single
`gcloud run deploy --source .` command that gives you the agent and dashboard
on Cloud Run with Gemini on Vertex AI and Firestore for state.

## Repo layout

```
agent/
  adk_pipeline.py      ADK agents, tools and prompts (Gemini)
  offline_engine.py    Fallback when Gemini is off or unavailable
  agents/              Watcher, Diagnoser, Remediator, Executor, Scribe, Orchestrator
  tools/               Evidence sources: fixture-backed mocks + real GCP/Kubernetes
  main.py              FastAPI: alerts, approvals, Ask, Pub/Sub, Slack; serves /ui
  data/mock_incidents/ The 5 scenario fixtures
dashboard/             Static HTML/JS/CSS dashboard (no build step)
sandbox/               Demo "victim" app, Kubernetes manifests, chaos scripts
infra/terraform/       Full GCP stack (GKE, Cloud SQL, Pub/Sub, IAM, Cloud Run)
scripts/               demo.sh, reset_demo.sh, gemini_smoke_test.py
docs/                  ARCHITECTURE, DEPLOY, DEMO_SCRIPT, SUBMISSION_CHECKLIST
```

## Configuration

All environment variables are documented in [.env.example](.env.example).
The main switches:

| Variable | Default | Meaning |
|---|---|---|
| `USE_REAL_GEMINI` | `false` | Gemini agents via ADK; otherwise the offline engine |
| `GOOGLE_API_KEY` | – | AI Studio key; leave unset on GCP to use Vertex AI |
| `GEMINI_MODEL` | `gemini-3.5-flash-lite` | model for all agents |
| `MOCK_TOOLS` | `true` | fixture evidence; `false` reads the live cluster |
| `STORE_BACKEND` | `local` | `firestore` on Cloud Run |
| `AUTO_REMEDIATE` | `false` | confidence-gated auto-apply of low-risk fixes |

## Production hardening

Authenticated API (`AUTOOPS_API_KEY`), OIDC-verified Pub/Sub push,
Firestore state, idempotent alert intake, an approval state machine that
prevents replays, allowlisted remediation intents, Kubernetes access via
Google ADC (no kubeconfig in the image), post-fix health verification, and
a non-root container. Before enabling real remediation, apply the
namespace-scoped RBAC in `sandbox/k8s/rbac.yaml` and test every action in a
staging cluster.
