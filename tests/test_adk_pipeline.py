"""
End-to-end tests of the ADK pipeline with a scripted model standing in for
Gemini. Everything except the model is real: ADK agents, the
SequentialAgent, tool calls against fixture data, session state passing
between agents, structured-output validation, the remediator's allowlist,
the executor and the scribe.

This proves the wiring. It does not prove Gemini's reasoning quality -
run scripts/gemini_smoke_test.py against a real project for that.
"""
import json
import os

os.environ["MOCK_TOOLS"] = "true"
os.environ["STORE_BACKEND"] = "local"
os.environ["USE_REAL_GEMINI"] = "false"
os.environ["LOCAL_DB_PATH"] = "/tmp/autoops-adk-test-db.json"
os.environ.pop("AUTOOPS_API_KEY", None)

from typing import List

from google.adk.models.base_llm import BaseLlm, LlmCapabilities
from google.adk.models.llm_response import LlmResponse
from google.genai import types
from pydantic import Field

from agent.agents import orchestrator


def _system_text(req) -> str:
    si = req.config.system_instruction if req.config else None
    if si is None:
        return ""
    if isinstance(si, str):
        return si
    return "".join(p.text or "" for p in (si.parts or []))


class ScriptedGemini(BaseLlm):
    """Plays the role of Gemini for each AutoOps agent."""
    model: str = "scripted-gemini"
    plan_fix_id: str = "rollback_api"
    seen: List[str] = Field(default_factory=list)

    @property
    def capabilities(self) -> LlmCapabilities:
        return LlmCapabilities(output_schema_and_tools=False)

    async def generate_content_async(self, llm_request, stream=False):
        system = _system_text(llm_request)
        self.seen.append(system)
        if "Investigator agent" in system:
            tool_results = [p.function_response for c in llm_request.contents for p in (c.parts or []) if p.function_response]
            if not tool_results:
                parts = [
                    types.Part(function_call=types.FunctionCall(name="get_recent_deploys", args={"service": ""})),
                    types.Part(function_call=types.FunctionCall(name="query_logs", args={"service": "api"})),
                ]
            else:
                parts = [types.Part(text="FINDINGS: api:v4.2 deployed 21:01:50 mounting certs/2025-q4; "
                                         "from 21:03:41 POST /checkout fails TLS: certificate has expired.")]
        elif "Diagnoser agent" in system:
            parts = [types.Part(text=json.dumps({
                "root_cause": "api:v4.2 mounted an expired payments client certificate; mTLS to payments-gateway fails.",
                "root_cause_type": "tls_cert_expiry",
                "confidence": 0.91,
                "evidence": ["[21:03:41] certificate has expired", "[21:01:50] api:v4.2 rotate cert to certs/2025-q4"],
                "hypotheses_rejected": ["Gateway outage: other routes healthy, error is client-cert expiry"],
            }))]
        elif "Remediation Planner agent" in system:
            parts = [types.Part(text=json.dumps({
                "fix_id": self.plan_fix_id,
                "justification": "Rolling back the api restores the previous, valid certificate bundle.",
                "alternatives_rejected": ["restart_api: would remount the same expired cert"],
            }))]
        elif "Scribe agent" in system:
            parts = [types.Part(text="## Summary\nCheckout failed after an expired client cert was mounted.")]
        elif "Ask AutoOps" in system:
            parts = [types.Part(text="A restart would remount the same expired certificate, so it would not help.")]
        else:
            parts = [types.Part(text="unexpected agent")]
        yield LlmResponse(content=types.Content(role="model", parts=parts))


def setup_function():
    try:
        os.remove(os.environ["LOCAL_DB_PATH"])
    except FileNotFoundError:
        pass


def test_adk_pipeline_end_to_end():
    model = ScriptedGemini()
    incident = orchestrator.handle_alert("cert_expiry", model=model)

    assert incident.ai_engine == "test model via ADK", incident.trace  # did not fall back
    assert incident.status.value == "awaiting_approval"
    assert incident.diagnosis.root_cause_type == "tls_cert_expiry"
    assert incident.proposed_fix.fix_id == "rollback_api"
    assert incident.proposed_fix.target == "deployment/api"
    assert "certificate" in incident.proposed_fix.justification

    # The investigator's tool calls really ran against fixture data.
    results = [t.detail for t in incident.trace if t.action == "tool_result"]
    assert any(r.startswith("get_recent_deploys returned deploys: 2") for r in results), results
    assert any(r.startswith("query_logs returned logs: 6") for r in results), results

    # State passed between agents: the diagnoser saw the investigator's findings.
    diagnoser_prompt = next(s for s in model.seen if "Diagnoser agent" in s)
    assert "certs/2025-q4" in diagnoser_prompt
    assert any(t.action == "gemini_calls" and t.detail.startswith("4 ") for t in incident.trace)
    planner_prompt = next(s for s in model.seen if "Remediation Planner agent" in s)
    assert "tls_cert_expiry" in planner_prompt and "rollback_api" in planner_prompt

    resolved = orchestrator.handle_approval(incident.id, True, model=model)
    assert resolved.status.value == "resolved"
    assert resolved.postmortem.startswith("## Summary")

    qa = orchestrator.handle_question(incident.id, "Why not just restart the api?", model=model)
    assert "expired certificate" in qa.answer
    assert qa.engine == "test model via ADK"


def test_planner_cannot_choose_fix_outside_allowlist():
    # A plan outside the catalog fails ADK's schema validation; the incident
    # falls back to the offline engine, which escalates this unseen type.
    model = ScriptedGemini(plan_fix_id="delete_namespace")
    incident = orchestrator.handle_alert("cert_expiry", model=model)
    assert any(t.action == "gemini_unavailable" for t in incident.trace)
    assert incident.status.value == "escalated"
    assert incident.proposed_fix.fix_id == "escalate"


import pytest


@pytest.mark.parametrize("scenario", ["cert_expiry", "vendor_outage", "stuck_worker"])
def test_offline_engine_escalates_incidents_outside_its_rules(scenario):
    incident = orchestrator.handle_alert(scenario)
    assert incident.ai_engine.startswith("offline heuristic")
    assert incident.diagnosis.root_cause_type == "unknown"
    assert incident.status.value == "escalated"


def test_offline_engine_still_handles_known_scenarios():
    for scenario, fix in [("bad_deploy", "rollback_worker"), ("oom_leak", "rollback_worker"),
                          ("db_exhaustion", "rollback_worker"), ("bad_config", "restore_api_config")]:
        incident = orchestrator.handle_alert(scenario)
        assert incident.proposed_fix.fix_id == fix, scenario
        assert orchestrator.handle_approval(incident.id, True).status.value == "resolved"


def test_auto_remediation_policy(monkeypatch):
    monkeypatch.setenv("AUTO_REMEDIATE", "true")
    incident = orchestrator.handle_alert("cert_expiry", model=ScriptedGemini())
    assert incident.status.value == "resolved"
    assert any(t.action == "auto_approved" for t in incident.trace)


class SlowGemini(ScriptedGemini):
    async def generate_content_async(self, llm_request, stream=False):
        import asyncio
        await asyncio.sleep(5)
        async for r in super().generate_content_async(llm_request, stream):
            yield r


def test_slow_gemini_times_out_and_falls_back(monkeypatch):
    from agent import adk_pipeline
    monkeypatch.setattr(adk_pipeline, "AGENT_TIMEOUT_SECONDS", 0.5)
    incident = orchestrator.handle_alert("bad_deploy", model=SlowGemini())
    fallback = [t.detail for t in incident.trace if t.action == "gemini_unavailable"]
    assert fallback and "TimeoutError" in fallback[0]
    assert incident.ai_engine.startswith("offline heuristic")
    assert incident.proposed_fix.fix_id == "rollback_worker"


def test_repeated_runs_share_one_event_loop():
    from agent import adk_pipeline
    model = ScriptedGemini()
    for _ in range(5):
        incident = orchestrator.handle_alert("cert_expiry", model=model)
        assert incident.ai_engine == "test model via ADK"
    loops = [t for t in __import__("threading").enumerate() if t.name == "autoops-adk-loop"]
    assert len(loops) == 1
    assert adk_pipeline._agent_loop().is_running()


class RunawayGemini(ScriptedGemini):
    """Keeps requesting tools forever, as a misbehaving model might."""
    async def generate_content_async(self, llm_request, stream=False):
        self.seen.append("call")
        yield LlmResponse(content=types.Content(role="model", parts=[
            types.Part(function_call=types.FunctionCall(name="get_cluster_events", args={}))]))


def test_call_cap_stops_runaway_model():
    model = RunawayGemini()
    incident = orchestrator.handle_alert("bad_deploy", model=model)
    assert any(t.action == "gemini_unavailable" for t in incident.trace)
    assert incident.ai_engine.startswith("offline heuristic")
    from agent import adk_pipeline
    assert len(model.seen) <= adk_pipeline.MAX_CALLS_PER_INCIDENT


def test_rate_limiter_waits_when_minute_quota_used(monkeypatch):
    import asyncio
    from agent import adk_pipeline
    clock = {"t": 1000.0}
    slept = []

    async def fake_sleep(seconds):
        slept.append(seconds)
        clock["t"] += seconds

    monkeypatch.setattr(adk_pipeline, "GEMINI_RPM", 2)
    monkeypatch.setattr(adk_pipeline.time, "monotonic", lambda: clock["t"])
    monkeypatch.setattr(adk_pipeline.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(adk_pipeline, "_rate_lock", None)
    adk_pipeline._call_times.clear()

    class Ctx:
        state = {}

    async def three_calls():
        for _ in range(3):
            await adk_pipeline._before_model(Ctx(), None)

    asyncio.run(three_calls())
    assert len(slept) == 1 and 59 < slept[0] <= 60.2   # third call waited for the window
    assert Ctx.state["gemini_calls"] == 3
    adk_pipeline._call_times.clear()
