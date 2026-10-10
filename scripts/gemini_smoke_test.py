"""
Run every scenario through the real Gemini pipeline and check the result.

Usage (from the repo root), with ONE of:
  # Quickest: an AI Studio key (https://aistudio.google.com/apikey)
  GOOGLE_API_KEY=... python scripts/gemini_smoke_test.py
  # Or Vertex AI with your gcloud login
  gcloud auth application-default login
  GCP_PROJECT=your-project GCP_LOCATION=us-central1 python scripts/gemini_smoke_test.py

Optional: GEMINI_MODEL=gemini-3.8-flash (default), GEMINI_DIAGNOSIS_MODEL=<a Pro model listed in AI Studio>

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
    "bad_config": "restart_api",
    "cert_expiry": "rollback_api",  # the unseen incident type
}


def main() -> int:
    # Configure before importing the agent: tool selection is read at import time.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    os.environ["USE_REAL_GEMINI"] = "true"
    os.environ.setdefault("MOCK_TOOLS", "true")
    os.environ["STORE_BACKEND"] = "local"
    os.environ["LOCAL_DB_PATH"] = str(Path(tempfile.mkdtemp()) / "smoke.json")
    from agent.agents import orchestrator

    failures = 0
    for scenario, expected in EXPECTED_FIX.items():
        start = time.time()
        inc = orchestrator.handle_alert(scenario)
        took = time.time() - start
        fell_back = inc.ai_engine.startswith("offline")
        fix = inc.proposed_fix.fix_id if inc.proposed_fix else "none"
        ok = not fell_back and fix == expected
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

    print(f"\n{len(EXPECTED_FIX) - failures}/{len(EXPECTED_FIX)} scenarios passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
