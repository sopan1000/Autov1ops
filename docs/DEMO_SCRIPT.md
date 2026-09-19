# 3-minute demo video script

Required by the submission rules: a public YouTube/Vimeo/Drive link, ~3
minutes, showing the solution in action. Record with `scripts/demo.sh`
running in one pane and the dashboard on screen.

## Beat sheet

**0:00–0:20 — The problem**
"When something breaks in production, an on-call engineer spends the
first 30 to 60 minutes doing the same manual investigation every time:
read the logs, check what deployed recently, compare metrics, guess,
try a fix, write it up after. AutoOps does that investigation
automatically."

**0:20–0:50 — Architecture, fast**
Show the pipeline diagram (README). "Five agents built on Gemini and
Google's Agent Development Kit, deployed on Cloud Run: a Watcher that
catches the alert, a Diagnoser that reads logs, metrics, deploy history,
and cluster events, a Remediator that proposes a specific fix from a
fixed, reviewable set of actions - never a free-form command - and only
after a human approves it, an Executor applies it and a Scribe writes
the postmortem."

**0:50–2:20 — Live break-and-fix (the core of the video)**
Run `./sandbox/chaos/bad_deploy.sh` (or `db_exhaustion.sh` - pick
whichever reads best on camera) with the dashboard visible.
- Show the incident appear within seconds.
- Point at the reasoning trace: "it's not just summarizing - it read
  these specific log lines, checked the deploy that went out 12 minutes
  ago, and connected the two."
- Show the proposed fix and risk rating.
- Click Approve on camera.
- Show it resolve, and the runbook get written.

**2:20–2:45 — The learning loop**
Trigger the *same* scenario again (or narrate this from the runbook
list): "the next time this happens, the Diagnoser already has this
runbook - it gets faster and more confident over time, which is the
scalability story: this isn't a one-off script, it's a system that
compounds."

**2:45–3:00 — Close**
"Built for Future of Work & Enterprise Productivity. [Team name],
AI Builder Cup 2026."

## Filming notes

- Rehearse the exact click sequence at least twice before recording -
  the dashboard's 2-second polling means a click-to-update lag of up to
  ~2s; don't narrate over dead air, cut to it.
- Have `scripts/reset_demo.sh` run right before recording so the
  dashboard starts empty.
- Record a fallback take with `MOCK_TOOLS=true` even if you deploy to
  real GCP for judging - it removes all live-demo risk (network, quota,
  a stale cluster) from the one artifact you can't re-record after
  the deadline.
