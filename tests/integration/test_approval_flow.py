"""Integration test: the full approval workflow with fake LLMs.

Verifies the Phase 6 gate mechanics:
- the graph PAUSES durably at the approval interrupt (checkpointer-backed)
- resuming with 'approved' completes the workflow
- resuming with an INVALID edited plan raises PlanRejected and the graph
  stays paused (no execution)
- resuming with a VALID edited plan re-validates and swaps the plan

Requires PostgreSQL. No LLM, no live cluster (dry-run is stubbed).
"""

import uuid
from typing import ClassVar

import pytest
from langchain_core.language_models.chat_models import BaseChatModel, ChatResult
from langchain_core.messages import AIMessageChunk
from langchain_core.outputs import ChatGenerationChunk
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.types import Command

from agent.graph_runner import AsyncCheckpointerAdapter
from agent.guardrails import PlanRejected
from agent.state import Evidence, Hypothesis
from common.config import get_settings
from database.connection import get_pool

pytestmark = pytest.mark.integration


class FakeLLM(BaseChatModel):
    queue: ClassVar[list[str]] = []

    @property
    def _llm_type(self) -> str:
        return "fake"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        text = self.queue.pop(0) if self.queue else "{}"
        return ChatResult(generations=[
            ChatGenerationChunk(message=AIMessageChunk(content=text))])


def _db_up() -> bool:
    try:
        with get_pool().connection() as conn:
            conn.execute("SELECT 1").fetchone()
        return True
    except Exception:  # noqa: BLE001
        return False


if not _db_up():
    pytest.skip("PostgreSQL not reachable", allow_module_level=True)


DIAGNOSIS = ('{"root_cause": "memory limit too low", "category": "resource",'
             ' "confidence": 0.85, "supporting_evidence": ["E2"],'
             ' "alternative_causes": [],'
             ' "explanation": "OOMKilled restarts after limit cut.",'
             ' "evidence_cited": ["E2"]}')
PLANNER_ACTIONS = (
    '[{"name": "set_resources", "namespace": "boutique",'
    ' "target": "checkoutservice",'
    ' "params": {"limits": {"memory": "128Mi"}, "container": "server"},'
    ' "risk": "medium", "rationale": "restore healthy limit",'
    ' "runbook_ref": "OOMKilled / memory limit too low"}]')


async def fake_specialist(agent_name, state, llm=None, tools=None):
    ev = Evidence(id=f"E{len(state.get('evidence', [])) + 1}", source="metrics",
                  summary="restarts rising", raw_ref="t")
    return {
        "evidence": [ev],
        "hypotheses": [Hypothesis(cause="memory limit too low",
                                  category="resource", confidence=0.85,
                                  supporting=["E2", ev.id])],
        "steps_used": state.get("steps_used", 0) + 1,
        "timeline": [{"agent": agent_name}],
    }


@pytest.fixture
def patched(monkeypatch):
    # triage + supervisor + diagnose + planner LLMs are scripted
    FakeLLM.queue = []  # filled per test
    monkeypatch.setattr("agent.nodes.triage.build_llm", lambda role="primary": FakeLLM())
    monkeypatch.setattr("agent.nodes.supervisor.build_llm", lambda role="primary": FakeLLM())
    monkeypatch.setattr("agent.nodes.diagnose.build_llm", lambda role="primary": FakeLLM())
    monkeypatch.setattr("agent.nodes.remediation.build_llm", lambda role="primary": FakeLLM())
    monkeypatch.setattr("mcp_servers.knowledge.server.search_incidents",
                        lambda query, service=None, limit=5: "(none)")
    monkeypatch.setattr("mcp_servers.knowledge.server.search_similar_incidents",
                        lambda query, service=None, limit=3: "(none)")
    monkeypatch.setattr("mcp_servers.k8s_read.server.list_pods",
                        lambda namespace=None, label_selector=None: "pods")
    monkeypatch.setattr("agent.nodes.specialist.run_specialist", fake_specialist)
    monkeypatch.setattr("mcp_servers.knowledge.server.hybrid_search_runbooks",
                        lambda query, limit=4: [{"runbook": "oom", "section": "Remediation",
                                                 "content": "raise the limit", "score": 0.03}])
    monkeypatch.setattr("agent.nodes.remediation.dry_run_action",
                        lambda action: {"ok": True, "detail": "dry-run admitted (stub)"})
    # these tests focus on APPROVAL mechanics: stub the Phase-7 tail where
    # the graph binds it (agent.graph.*), so approve/edit paths complete
    # without a live write server / verifier / postmortem DB work
    async def _exec_stub(state):
        return {"execution": {"executed": True, "results": []},
                "timeline": [{"agent": "executor", "stub": True}]}

    async def _verify_stub(state):
        return {"outcome": {"verdict": "RESOLVED", "checks": {}},
                "timeline": [{"agent": "verifier", "stub": True}]}

    async def _pm_stub(state):
        return {"timeline": [{"agent": "postmortem", "stub": True}]}

    monkeypatch.setattr("agent.graph.execute_node", _exec_stub)
    monkeypatch.setattr("agent.graph.verifier_node", _verify_stub)
    monkeypatch.setattr("agent.graph.postmortem_node", _pm_stub)
    yield
    FakeLLM.queue = []


async def _run_to_pause(thread_id: str) -> dict:
    """Drive the graph to the approval interrupt. The returned context keeps
    the checkpointer OPEN (close ctx['stack'] when done)."""
    import contextlib

    from agent.graph import build_graph

    FakeLLM.queue = [
        '[{"cause": "memory limit too low", "category": "resource",'
        ' "confidence": 0.4, "supporting": ["E2"], "refuting": []}]',
        '{"next_agent": "metrics_agent", "question": "check restarts"}',
        DIAGNOSIS,
        PLANNER_ACTIONS,
    ]
    stack = contextlib.ExitStack()
    saver = stack.enter_context(
        PostgresSaver.from_conn_string(get_settings().database_url))
    saver.setup()
    graph = build_graph(checkpointer=AsyncCheckpointerAdapter(saver))
    config = {"configurable": {"thread_id": thread_id}}
    result = await graph.ainvoke(
        {"incident_id": thread_id, "alert": {"labels": {
            "alertname": "PodRestarting", "namespace": "boutique",
            "pod": "checkoutservice-abcde-fghij"}},
         "namespace": "boutique", "service": "checkoutservice"},
        config=config)
    assert result.get("__interrupt__"), "graph did not pause at approval"
    interrupt_payload = result["__interrupt__"][0].value
    return {"graph": graph, "config": config, "payload": interrupt_payload,
            "stack": stack}


async def test_approval_pause_and_approve(patched):
    thread = str(uuid.uuid4())
    ctx = await _run_to_pause(thread)
    try:
        # paused BEFORE approval: payload exposes diagnosis + plan + dry-run
        assert ctx["payload"]["root_cause"] == "memory limit too low"
        assert ctx["payload"]["plan"][0]["name"] == "set_resources"
        assert ctx["payload"]["dry_run"][0]["ok"] is True

        final = await ctx["graph"].ainvoke(
            Command(resume={"status": "approved"}), config=ctx["config"])
        assert final["approval"] == "approved"
        assert final["plan"][0].params["limits"]["memory"] == "128Mi"
    finally:
        ctx["stack"].close()
        await _cleanup(thread)


async def test_edited_invalid_plan_rejected_and_stays_paused(patched):
    thread = str(uuid.uuid4())
    ctx = await _run_to_pause(thread)
    try:
        bad_edit = [{"name": "scale", "namespace": "boutique",
                     "target": "checkoutservice",
                     "params": {"replicas": 99}, "risk": "low",
                     "rationale": "human edit that violates policy"}]
        # invalid edit: the node RE-INTERRUPTS with the validation error
        # (a plain raise would brick the thread - LangGraph checkpoints the
        # resume value into the pending task)
        result = await ctx["graph"].ainvoke(
            Command(resume={"status": "edited", "plan": bad_edit}),
            config=ctx["config"])
        assert result.get("__interrupt__"), "expected re-interrupt"
        error = result["__interrupt__"][0].value.get("validation_error", "")
        assert "replicas 99" in error, error
        # still paused: a subsequent VALID decision completes the workflow
        final = await ctx["graph"].ainvoke(
            Command(resume={"status": "rejected"}), config=ctx["config"])
        assert final["approval"] == "rejected"
    finally:
        ctx["stack"].close()
        await _cleanup(thread)


async def test_edited_valid_plan_swaps(patched):
    thread = str(uuid.uuid4())
    ctx = await _run_to_pause(thread)
    try:
        good_edit = [{"name": "rollout_undo", "namespace": "boutique",
                      "target": "checkoutservice", "params": {},
                      "risk": "low", "rationale": "prefer rollback"}]
        final = await ctx["graph"].ainvoke(
            Command(resume={"status": "edited", "plan": good_edit}),
            config=ctx["config"])
        assert final["approval"] == "edited"
        assert final["plan"][0].name == "rollout_undo"
    finally:
        ctx["stack"].close()
        await _cleanup(thread)


async def _cleanup(thread_id: str) -> None:
    def _do():
        with get_pool().connection() as conn:
            conn.execute("DELETE FROM evidence_raw WHERE incident_id = %s::uuid",
                         (thread_id,))
            conn.execute("DELETE FROM audit_log WHERE incident_id = %s::uuid",
                         (thread_id,))
    import asyncio
    await asyncio.to_thread(_do)
