# Submission checklist

Source: https://aibuildercup.com/themes.html (confirmed 2026-09-18).
Re-check before submitting in case requirements are updated.

## Deadlines
- [ ] Team of 2–4 formed on Hack2skill by **Oct 11, 2026**
- [ ] Prototype submitted by **Oct 18, 2026** — submit by Oct 16 to leave
      slack for last-minute issues

## Required submission artifacts
- [ ] **Proposal deck**, exported as PDF: problem statement, positive
      impact, alignment with Future of Work & Enterprise Productivity,
      feasibility, scalability story
- [ ] **Functional prototype**: built with Gemini/Gemma or an agentic
      platform (Agent Development Kit ✓), deployed on Cloud Run ✓ (or
      Firebase) — `agent/` satisfies this once deployed via `cloudbuild.yaml`
- [ ] **3-minute video**: public YouTube/Vimeo/Drive link — script in
      [DEMO_SCRIPT.md](DEMO_SCRIPT.md)
- [ ] **Category specification**: state the problem statement/track
      clearly (Future of Work & Enterprise Productivity)
- [ ] All submission materials in **English**

## Mandatory technical requirements
- [ ] Uses Google AI models (Gemini) — `agent/llm.py`, `USE_REAL_GEMINI=true`
- [ ] Built using an agentic platform — Google's Agent Development
      Kit pattern (`agent/agents/orchestrator.py`)
- [ ] Deployed on Google Cloud via Cloud Run or Firebase —
      `agent/Dockerfile` + `cloudbuild.yaml` → Cloud Run

## Before recording/submitting, verify live
- [ ] All 4 chaos scenarios produce a correct diagnosis and a sensible
      fix (`scripts/demo.sh`)
- [ ] `USE_REAL_GEMINI=true` actually returns valid JSON matching the
      `Diagnosis` schema against a real Vertex AI project (test this
      well before the deadline — controlled generation quirks are
      easier to debug with days, not hours, to spare)
- [ ] The deployed Cloud Run URL responds to `/health`
- [ ] The dashboard, pointed at the Cloud Run URL, loads and updates
- [ ] Approve/Reject both work end-to-end against the real deployment,
      not just localhost

## Judging criteria to keep front-of-mind while polishing
Technical Merit & Gen AI Implementation 40% · Problem Alignment & Impact
25% · Innovation & Creativity 25% · UX & Solution Design 10%. See
README.md "Judging criteria — where this scores" for how this project
maps to each.
