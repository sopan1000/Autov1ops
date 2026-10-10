# 3-minute demo video script

Required by the submission rules: a public YouTube, Vimeo or Drive link,
about 3 minutes. Record against the **deployed Cloud Run URL with Gemini on**
(header badge green), not localhost.

## Beat sheet

**0:00–0:20: The problem (your own story)**
"I'm a DevOps engineer. When production breaks, the first 30 to 60 minutes
of every incident are the same manual detective work: read the logs, check
what deployed, compare graphs, guess, fix, write it up. AutoOps does that
part." Add one sourced industry statistic on downtime cost or MTTR here.

**0:20–0:45: How it works**
Show the pipeline diagram (docs/ARCHITECTURE.md). "Gemini agents built on
Google's Agent Development Kit, running on Cloud Run. An investigator that
chooses which logs, metrics and deploys to examine; a diagnoser; and a
planner that picks a fix from a fixed safe list. AI proposes, a human
approves, nothing runs without a yes."

**0:45–1:40: Break something**
Click **Simulate incident → API error rate spike**.
- Point at the **lifecycle rail**: alert to proposed fix in seconds.
- Open the **Investigation** tab: point at the **tool calls**. "It decided to
  check deploys, then logs, then connection metrics."
- Read the root cause: the *worker* leaked connections and took down the
  *api*. "It found the upstream cause, not the symptom."
- Show the fix, the risk and **Ruled out**. Click **Approve**.
- Show the resolution verified and the postmortem written. Point at the timer.

**1:40–2:20: The unseen incident (your strongest moment)**
Simulate **Checkout returning 502s** (tagged "Needs Gemini"). "We never wrote a rule for this one." Show Gemini
diagnosing the expired client certificate from the deploy history and TLS
errors, and choosing to roll back the api. Optional: show the same scenario
with Gemini off, where it simply escalates to a human. That contrast is the
whole case for Gen AI here.

**Optional, if time allows: knowing when not to act**
Simulate **Checkout returning 503s**. AutoOps finds that the payment provider
is down, nothing on your side changed, and escalates without touching
anything. "Most AI ops tools would roll something back here. Ours knows
there's nothing safe to change."

**2:20–2:40: Ask AutoOps**
Type "Why not just restart the api?" and show the answer: a restart would
remount the same expired certificate.

**2:40–3:00: Safety and close**
"Allowlisted actions only, human approval, verified recovery, automatic
fallback when the model is unavailable, and runbooks that make the next
incident faster. Built for Future of Work & Enterprise Productivity.
[Team name], AI Builder Cup 2026."

## Filming notes

- Run `scripts/gemini_smoke_test.py` first and only record once it passes 5/5.
- Gemini takes several seconds per incident. The dashboard shows an
  "investigating…" card, but cut the waiting in editing rather than talking over it.
- Start from an empty dashboard: run `scripts/reset_demo.sh` locally, or on
  Cloud Run delete the `incidents` and `runbooks` collections in Firestore.
- Record one backup take locally (`docker-compose up` with `USE_REAL_GEMINI=true`
  and an AI Studio key) in case Cloud Run has issues on recording day.
- Gemini's wording changes between runs. Rehearse with the real output, and
  don't script lines that quote it word for word.
