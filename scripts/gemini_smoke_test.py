"""
Run every scenario through the real Gemini pipeline and check the result.

Usage (from the repo root), with ONE of:
  # Quickest: an AI Studio key (https://aistudio.google.com/apikey)
  GOOGLE_API_KEY=... python scripts/gemini_smoke_test.py
  # Or Vertex AI with your gcloud login
  gcloud auth application-default login
  GCP_PROJECT=your-project GCP_LOCATION=us-central1 python scripts/gemini_smoke_test.py

Optional: GEMINI_MODEL=gemini-3.5-flash-lite (default), GEMINI_DIAGNOSIS_MODEL=gemini-3.8-flash (stronger diagnosis step)

Run a subset to save quota:  python scripts/gemini_smoke_test.py cert_expiry oom_leak

Free tier tips: each incident needs about 4 Gemini requests. If you see 429
RESOURCE_EXHAUSTED, check your limits at https://aistudio.google.com/rate-limit
and set GEMINI_RPM to your requests-per-minute limit, or wait for the daily
quota to reset (midnight Pacific time).

Exits non-zero if any scenario fell back to the offline engine or picked a
different fix than expected. Run it before recording the demo video.
"""
import os
import sys
import tempfile
import time
from pathlib import Path

EXPECTED_FIX = {
    "bad_deploy": "rollback_worker",
    "oom_leak": "rollback_worker",
    "db_exhaustion": "rollback_worker",
    "bad_config": "restore_api_config",
    "cert_expiry": "rollback_api",       # outside the offline engine's rules
    "vendor_outage": "escalate",         # external outage: nothing safe to change
    "stuck_worker": "restart_worker",    # wedged process, no bad deploy
    "poisoned_logs": "rollback_worker",  # guardrails demo: secrets masked, injection ignored
}


def main() -> int:
    # Configure before importing the agent: tool selection is read at import time.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    os.environ["USE_REAL_GEMINI"] = "true"
    os.environ.setdefault("MOCK_TOOLS", "true")
    os.environ["STORE_BACKEND"] = "local"
    os.environ["LOCAL_DB_PATH"] = str(Path(tempfile.mkdtemp()) / "smoke.json")
    from agent.agents import orchestrator

    selected = sys.argv[1:] or list(EXPECTED_FIX)
    unknown = [s for s in selected if s not in EXPECTED_FIX]
    if unknown:
        print(f"Unknown scenario(s): {', '.join(unknown)}. Choose from: {', '.join(EXPECTED_FIX)}")
        return 2

    failures = 0
    for scenario in selected:
        expected = EXPECTED_FIX[scenario]
        start = time.time()
        inc = orchestrator.handle_alert(scenario)
        took = time.time() - start
        fell_back = inc.ai_engine.startswith("offline")
        fix = inc.proposed_fix.fix_id if inc.proposed_fix else "none"
        ok = not fell_back and fix == expected
        g = inc.guardrails
        if scenario == "poisoned_logs":   # must mask secrets and flag the injection
            ok = ok and sum(g.masked.values()) >= 8 and bool(g.injection_flags)
        failures += 0 if ok else 1
        print(f"\n[{'PASS' if ok else 'FAIL'}] {scenario}  ({took:.1f}s, engine: {inc.ai_engine})")
        if fell_back:
            err = next((t.detail for t in inc.trace if t.action == "gemini_unavailable"), "")
            print(f"   fell back to offline engine: {err}")
        if inc.diagnosis:
            print(f"   root cause ({inc.diagnosis.confidence:.0%}): {inc.diagnosis.root_cause}")
        print(f"   fix: {fix} (expected {expected})")
        if inc.proposed_fix and inc.proposed_fix.justification:
            print(f"   why: {inc.proposed_fix.justification}")
        tools = [t.detail.split("(")[0] for t in inc.trace if t.action == "tool_call"]
        print(f"   tools used: {', '.join(tools) or 'none'}")
        if g.masked or g.injection_flags:
            print(f"   guardrails: {sum(g.masked.values())} values masked {dict(g.masked)}, "
                  f"{len(g.injection_flags)} injection line(s) flagged")
        calls = next((t.detail for t in inc.trace if t.action == "gemini_calls"), "")
        if calls:
            print(f"   {calls}")
        if fell_back and "429" in err:
            print("   -> quota hit: see https://aistudio.google.com/rate-limit, then set GEMINI_RPM or wait")

    print(f"\n{len(selected) - failures}/{len(selected)} scenarios passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
