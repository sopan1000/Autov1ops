# AutoOps — an AI on-call engineer

Built for the **Google Cloud AI Builder Cup 2026** (JAPAC, by Hack2skill),
theme: **Future of Work & Enterprise Productivity**.

AutoOps watches a production system, diagnoses incidents the way an SRE
would (reading logs, metrics, deploy history, and cluster events), proposes
a specific fix with a risk rating, waits for a human's one-click approval,
applies it, verifies recovery, and writes the postmortem — building a
runbook library that makes the next similar incident faster to resolve.

**This repo runs completely locally with zero GCP setup.** Every "cloud
tool" (Cloud Logging, Monitoring, GitHub, kubectl) has a mock implementation
that reads realistic fixture data, and the diagnosis step has a genuine
rule-based fallback when no Gemini API key is configured. Flip a couple of
env vars and the exact same code talks to real GCP. See "Going to real GCP"
below.

## Quickstart (2 minutes, no GCP account needed)

```bash
docker-compose up --build
```

- Agent API: http://localhost:8000 (try http://localhost:8000/health)
- Dashboard: http://localhost:3000

Then, in another terminal, break something:

```bash
export AGENT_URL=http://localhost:8000
./sandbox/chaos/bad_deploy.sh
```

Open the dashboard, watch the incident appear with a live reasoning trace,
click **Approve**, and watch it resolve. Or run the full scripted walkthrough:

```bash
./scripts/demo.sh
```

Reset between rehearsals with `./scripts/reset_demo.sh`.

## Architecture

```
 Cloud Monitoring alert
         │  (Pub/Sub push, in prod)
         ▼
   ┌─────────────┐
   │   Watcher    │  creates the Incident record
   └──────┬──────┘
          ▼
   ┌─────────────┐   tools: Cloud Logging, Cloud Monitoring,
   │  Diagnoser   │◄──GitHub (deploy history), kubectl (cluster
   │  (Gemini)    │   events), Vertex AI Search (past runbooks)
   └──────┬──────┘
          ▼
   ┌─────────────┐
   │ Remediator   │  proposes a fix from a fixed, reviewable allowlist
   └──────┬──────┘   (rollback / restart / scale / config-revert)
          ▼
   ┌─────────────┐
   │ Human review │  Slack (or dashboard) — Approve / Reject
   └──────┬──────┘
          ▼
   ┌─────────────┐
   │  Executor    │  applies the fix, verifies health, auto-rolls-back
   └──────┬──────┘   on regression
          ▼
   ┌─────────────┐
   │   Scribe     │  writes the postmortem, saves a runbook for next time
   └─────────────┘
```

Everything above the "Human review" line only ever *proposes*; nothing
touches production without explicit approval, and even what it can propose
is limited to four allowlisted actions (see `agent/agents/remediator.py`).
That's the safety story that makes this plausible for an actual enterprise
to adopt, not just a hackathon toy.

Full technical detail: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Repo layout

```
agent/            The agent pipeline - a single FastAPI service (Cloud Run)
  models.py         Shared data models (Incident, Diagnosis, ProposedFix, ...)
  store.py          Storage: local JSON (demo) or Firestore (prod)
  llm.py            Gemini call (real) + heuristic fallback (offline demo)
  tools/            Cloud Logging/Monitoring/GitHub/kubectl - mock + real
  agents/           Watcher, Diagnoser, Remediator, Executor, Scribe
  main.py           FastAPI routes + Slack webhook
  data/mock_incidents/   4 realistic incident fixtures used in mock mode
sandbox/           The "victim" app AutoOps watches over
  api/, worker/       Minimal FastAPI/stdlib services with fault hooks
  k8s/                Kubernetes manifests (GKE Autopilot target)
  chaos/              Scripts that trigger each of the 4 incident scenarios
infra/terraform/   GKE, Cloud SQL, Pub/Sub, IAM, Cloud Run - real GCP deploy
dashboard/         Static HTML/JS/CSS - live incident feed, no build step
docs/              Architecture deep-dive, demo video script, submission checklist
scripts/           demo.sh (scripted walkthrough), reset_demo.sh
```

## The 4 incident scenarios

| Scenario | What breaks | Root cause AutoOps finds | Proposed fix |
|---|---|---|---|
| `bad_deploy` | worker crash-loops | deploy references a config key that was never added | roll back deployment |
| `oom_leak` | worker OOMKilled repeatedly | new deploy added an unbounded in-memory cache | roll back deployment |
| `db_exhaustion` | api returns 500s | a leaky batch job never releases DB connections | roll back + restart api |
| `bad_config` | api can't reach the DB | a ConfigMap typo in `DB_HOST` | revert the ConfigMap |

Trigger any of them: `./sandbox/chaos/<scenario>.sh`

## Going to real GCP

The same code runs against a real cluster and real Gemini. Nothing in
`agent/agents/` or `agent/main.py` changes - only environment variables and
which classes `agent/tools/__init__.py` selects.

1. **Provision infra**
   ```bash
   cd infra/terraform
   terraform init
   terraform apply -var="project_id=YOUR_PROJECT_ID"
   ```
2. **Deploy the sandbox app** to the GKE cluster Terraform created:
   ```bash
   kubectl apply -f sandbox/k8s/
   # build + push sandbox/api and sandbox/worker images first (see their Dockerfiles)
   ```
3. **Bind Workload Identity** so the agent's GSA can act as a namespace-scoped KSA:
   ```bash
   kubectl create rolebinding autoops-agent-editor \
     --role=edit --serviceaccount=autoops-sandbox:autoops-agent -n autoops-sandbox
   ```
4. **Build and deploy the agent** to Cloud Run:
   ```bash
   gcloud builds submit --config cloudbuild.yaml .
   ```
5. **Flip the switches** (already set by `cloudbuild.yaml`, or manually):
   `MOCK_TOOLS=false`, `STORE_BACKEND=firestore`, `USE_REAL_GEMINI=true`,
   plus `GCP_PROJECT`, `GITHUB_REPO`, `GITHUB_TOKEN`.
6. **Point the dashboard** at the Cloud Run URL: edit `dashboard/config.js`
   or set `window.AUTOOPS_API_URL` before `app.js` loads, then deploy
   `dashboard/` to Firebase Hosting.
7. **Wire the alert policy**: a Cloud Monitoring alert policy (on the
   metrics `sandbox/api` and `sandbox/worker` emit) with a notification
   channel publishing to the `autoops-incidents` Pub/Sub topic Terraform
   created - that topic already push-subscribes to the deployed agent's
   `/alerts` endpoint.

Full env var reference: [.env.example](.env.example).

## Team

| Area | Owner |
|---|---|
| Agents (`agent/agents/`, `agent/llm.py`) | Agents lead |
| Infra (`sandbox/`, `infra/`, chaos scripts) | Platform/infra |
| Dashboard + Slack integration | Frontend/integrations |
| Pitch, demo video, submission, QA across all 4 scenarios | Product/pitch |

## Judging criteria — where this scores

- **Technical Merit & Gen AI Implementation (40%)** — Gemini performs real
  multi-source reasoning (logs + metrics + deploys + cluster events →
  root cause with cited evidence and rejected hypotheses), not a
  summarization wrapper. `USE_REAL_GEMINI=true` swaps in the live model
  with controlled generation (`response_schema`) — see `agent/llm.py`.
- **Problem Alignment & Impact (25%)** — directly cuts the most painful,
  repetitive part of on-call work; the runbook library gives a concrete,
  compounding scalability story.
- **Innovation & Creativity (25%)** — the human-approval gate and
  allowlisted-actions design is the differentiator from "AI ops" demos
  that just auto-execute; it's what makes this enterprise-credible.
- **UX & Solution Design (10%)** — one dashboard, one Slack message, one
  click. The agent's reasoning is visible, not a black box.

Submission checklist: [docs/SUBMISSION_CHECKLIST.md](docs/SUBMISSION_CHECKLIST.md).
Demo video script: [docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md).
