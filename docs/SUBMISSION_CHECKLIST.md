# Submission checklist

Source: https://aibuildercup.com/themes.html (confirmed 2026-09-18).
Re-check before submitting in case requirements have changed.

## Deadlines
- [ ] Team of 2–4 formed on Hack2skill by **Oct 11, 2026**
- [ ] Prototype submitted by **Oct 18, 2026**. Aim for Oct 16.

## Mandatory technical requirements
- [ ] **Google AI model**: Gemini, via `agent/adk_pipeline.py` with `USE_REAL_GEMINI=true`
- [ ] **Agentic platform**: Google Agent Development Kit (ADK) `LlmAgent`s in a `SequentialAgent`
- [ ] **Deployed on Cloud Run**: `gcloud run deploy --source .` (docs/DEPLOY.md)

## Required submission artifacts
- [ ] **Proposal deck as PDF**: problem, impact, alignment with Future of Work &
      Enterprise Productivity, feasibility, scalability
- [ ] **Working prototype link**: the Cloud Run URL (it opens the dashboard at `/ui`)
- [ ] **3-minute video**, public YouTube/Vimeo/Drive link. Script: [DEMO_SCRIPT.md](DEMO_SCRIPT.md)
- [ ] **Category stated**: Future of Work & Enterprise Productivity
- [ ] Everything in **English**

## Verify before recording and submitting
- [ ] `PYTHONPATH=. pytest -q` passes
- [ ] `scripts/gemini_smoke_test.py` passes 8/8 against real Gemini
- [ ] Deployed `/health` shows `"ai_engine": "<model> via ADK"`, not "offline"
- [ ] On the deployed dashboard, every scenario diagnoses correctly with no
      `gemini unavailable` step in its trace
- [ ] `cert_expiry` gets `rollback_api` with Gemini on
- [ ] `poisoned_logs` shows "8 sensitive values masked" and the prompt-injection banner
- [ ] Approve, Reject and Ask AutoOps all work on the deployed URL
- [ ] The incident list survives a redeploy (proves Firestore is in use)
- [ ] The GitHub repo `main` branch contains this code (not the original scaffold)

## After judging
- [ ] Remove public access or delete the Cloud Run service (docs/DEPLOY.md)

## Judging weights
Technical Merit & Gen AI Implementation 40% · Problem Alignment & Impact 25% ·
Innovation & Creativity 25% · UX & Solution Design 10%.
