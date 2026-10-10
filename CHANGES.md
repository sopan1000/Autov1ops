# Changes since the production-hardened version

## Gemini + Agent Development Kit (the main change)
- New `agent/adk_pipeline.py`: an ADK `SequentialAgent` of three Gemini
  `LlmAgent`s. The investigator has tools and chooses its own evidence; the
  diagnoser and remediation planner return structured outputs.
- The remediation planner picks a fix from `FIX_CATALOG` and justifies it;
  ADK schema validation rejects anything outside the catalog. A new `escalate`
  option and `escalated` status cover cases with no safe automated fix.
- The Scribe writes postmortems with Gemini. New Ask AutoOps endpoint:
  `POST /incidents/{id}/ask`.
- `agent/llm.py` replaced by `agent/offline_engine.py`, a clearly labelled
  fallback used when Gemini is off or fails. Each incident records which
  engine handled it (`ai_engine`).
- Optional confidence-gated auto-remediation (`AUTO_REMEDIATE`, off by default).
- New unseen-incident scenario `cert_expiry` (fixture + chaos script).

## Dashboard
- Engine badge, diagnosis/resolution timers, tool calls in a timeline,
  justification and ruled-out fixes, postmortem, Ask box, "investigating…" state.
- Cards only redraw when their incident changes, so typing and open panels
  survive the refresh.
- Served by the agent at `/ui`, so one Cloud Run URL is the whole demo.

## Deploy fixes
- Terraform: `PUBSUB_AUDIENCE` referenced the Cloud Run service from inside
  itself (Terraform rejects that). It now uses a fixed custom audience. Added
  `gemini_model` and `public_demo` variables. Not run through `terraform
  validate` (Terraform couldn't be downloaded in the build environment).
- `cloudbuild.yaml`: the `$SHORT_SHA` tag was empty on manual submits,
  `--set-env-vars` would have wiped the service's env vars, and `gcr.io` is
  retired for new projects. It now uses Artifact Registry and `$BUILD_ID`,
  and keeps existing env vars.
- Dockerfile moved to the repo root for `gcloud run deploy --source .`.
- Dependencies: `google-genai==0.3.0` (incompatible with ADK) replaced by
  `google-adk==2.11.0`; FastAPI, Pydantic and related pins raised to versions
  ADK requires. The full set installs cleanly on Python 3.11 and 3.13.

## Docs and tests
- New `docs/DEPLOY.md` and `scripts/gemini_smoke_test.py`. Rewrote the README,
  ARCHITECTURE, DEMO_SCRIPT and SUBMISSION_CHECKLIST.
- New `tests/test_adk_pipeline.py` (5 tests), which drives the real ADK agents
  with a scripted model. 9 tests in total.

## Not verified here (no Google Cloud credentials in the build environment)
- Real Gemini output quality: run `scripts/gemini_smoke_test.py`.
- The Cloud Run deploy, Firestore and Terraform: follow `docs/DEPLOY.md`.
