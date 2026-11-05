"""Integration tests: the EXECUTION path - approve -> execute (stubbed write
server) -> verify -> postmortem - plus the executor's fail-closed refusal.

Requires PostgreSQL. No LLM (fakes), no live cluster (k8s/prom stubbed).
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

READY_PODS = ("NAME\tREADY\tSTATUS\tRESTARTS\tAGE\tNODE\n"
              "checkoutservice-5bb775dd58-aaaaa\t1/1\tRunning\t2\t5m\tworker")

DIAGNOSIS = ('{"root_cause": "memory limit too low", "category": "resource",'
             ' "confidence": 0.85, "supporting_evidence": ["E2"],'
             ' "alternative_causes": [],'
             ' "explanation": "OOMKilled restarts after limit cut.",'
             ' "evidence_cited": ["E2"]}')
PLANNER_ACTIONS = (
    '[{"name": "rollout_undo", "namespace": "boutique",'
    ' "target": "checkoutservice", "params": {}, "risk": "low",'
    ' "rationale": "restore previous revision", "runbook_ref": "oomkilled"}]')


async def fake_specialist(agent_name, state, llm=None, tools=None):
    ev = Evidence(id=f"E{len(state.get('evidence', [])) + 1}", source="metrics",
                  summary="restart count rising to 6", raw_ref="t")
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
    import agent.llm as llm_module

    FakeLLM.queue = []
    for mod in ("agent.nodes.triage", "agent.nodes.supervisor",
                "agent.nodes.diagnose", "agent.nodes.remediation"):
        monkeypatch.setattr(f"{mod}.build_llm",
                            lambda role="primary": FakeLLM())
    monkeypatch.setattr(llm_module, "build_llm",
                        lambda role="primary": FakeLLM())
    monkeypatch.setattr("mcp_servers.knowledge.server.search_incidents",
                        lambda query, service=None, limit=5: "(none)")
    monkeypatch.setattr("mcp_servers.knowledge.server.search_similar_incidents",
                        lambda query, service=None, limit=3: "(none)")
    monkeypatch.setattr("mcp_servers.k8s_read.server.list_pods",
                        lambda namespace=None, label_selector=None: READY_PODS)
    monkeypatch.setattr("agent.nodes.specialist.run_specialist", fake_specialist)
    monkeypatch.setattr("mcp_servers.knowledge.server.hybrid_search_runbooks",
                        lambda query, limit=4: [])
    monkeypatch.setattr("agent.nodes.remediation.dry_run_action",
                        lambda action: {"ok": True, "detail": "stub"})
    # verifier: pods immediately ready, no alerts firing
    monkeypatch.setattr("mcp_servers.prometheus.server.list_firing_alerts",
                        lambda: "(no firing or pending alerts)")
    yield
    FakeLLM.queue = []


async def _run_to_pause(thread_id: str):
    import contextlib

    from agent.graph import build_graph

    FakeLLM.queue = [
        '[{"cause": "memory limit too low", "category": "resource",'
        ' "confidence": 0.4, "supporting": ["E2"], "refuting": []}]',
        '{"next_agent": "metrics_agent", "question": "check restarts"}',
        DIAGNOSIS,
        PLANNER_ACTIONS,
        '["lesson one", "lesson two"]',   # postmortem lessons (cheap LLM)
    ]
    stack = contextlib.ExitStack()
    saver = stack.enter_context(
        PostgresSaver.from_conn_string(get_settings().database_url))
    saver.setup()
    graph = build_graph(checkpointer=AsyncCheckpointerAdapter(saver))
    config = {"configurable": {"thread_id": thread_id}}
    # approvals has an FK to incidents - create the row the webhook would
    with get_pool().connection() as conn:
        conn.execute(
            "INSERT INTO incidents (id, alert_name, namespace, service, "
            "status) VALUES (%s::uuid, 'PodRestarting', 'boutique', "
            "'checkoutservice', 'investigating')", (thread_id,))
    result = await graph.ainvoke(
        {"incident_id": thread_id, "alert": {"labels": {
            "alertname": "PodRestarting", "namespace": "boutique",
            "pod": "checkoutservice-abcde-fghij"}},
         "namespace": "boutique", "service": "checkoutservice"},
        config=config)
    assert result.get("__interrupt__")
    return graph, config, stack


async def _cleanup(thread_id: str) -> None:
    def _do():
        with get_pool().connection() as conn:
            conn.execute("DELETE FROM approvals WHERE incident_id = %s::uuid",
                         (thread_id,))
            conn.execute("DELETE FROM evidence_raw WHERE incident_id = %s::uuid",
                         (thread_id,))
            conn.execute("DELETE FROM audit_log WHERE incident_id = %s::uuid",
                         (thread_id,))
            conn.execute("DELETE FROM incidents WHERE id = %s::uuid",
                         (thread_id,))
    import asyncio
    await asyncio.to_thread(_do)


async def test_executor_refuses_without_approval_record(patched):
    """Fail closed: even with approval state set, a MISSING approvals row
    blocks execution (no fake write server patched - a real call attempt
    would fail the test)."""
    from agent.nodes.executor import execute_node

    state = {
        "incident_id": str(uuid.uuid4()),  # no approvals row for this id
        "alert": {"labels": {}}, "namespace": "boutique",
        "service": "checkoutservice", "approval": "approved",
        "plan": [], "execution": None,
    }
    delta = await execute_node(state)
    assert delta["execution"]["executed"] is False
    assert "refus" in delta["execution"]["reason"].lower() or \
        "approval" in delta["execution"]["reason"].lower()


async def test_full_approved_path_executes_verifies_postmortem(patched, monkeypatch):
    thread = str(uuid.uuid4())
    graph, config, stack = await _run_to_pause(thread)
    # create the approval row BEFORE resuming (the endpoint does this via
    # record_approval; here directly)
    from api.services import incident_service
    incident_service.record_approval(thread, "pytest", "approved",
                                     [{"name": "rollout_undo"}])

    calls: list = []

    async def fake_write_server(action):
        calls.append(action.name)
        return {"ok": True, "detail": f"stubbed {action.name}"}

    import agent.nodes.executor as executor_module
    monkeypatch.setattr(executor_module, "call_write_server", fake_write_server)

    try:
        final = await graph.ainvoke(Command(resume={"status": "approved"}),
                                    config=config)
        # execute -> verify -> postmortem all ran
        agents = [s.get("agent") for s in final["timeline"]]
        assert "executor" in agents and "verifier" in agents \
            and "postmortem" in agents
        assert calls == ["rollout_undo"]  # exactly the approved action
        assert final["execution"]["executed"] is True
        assert final["outcome"]["verdict"] == "RESOLVED"
        # postmortem persisted on the incident row
        with get_pool().connection() as conn:
            row = conn.execute(
                "SELECT summary, resolved, status FROM incidents "
                "WHERE id = %s::uuid", (thread,)).fetchone()
        if row:  # the row exists only if this thread matches an incident
            assert row[1] is True and row[2] == "resolved"
            assert "root_cause" in row[0]
    finally:
        stack.close()
        await _cleanup(thread)


async def test_rejected_path_skips_execution(patched):
    thread = str(uuid.uuid4())
    graph, config, stack = await _run_to_pause(thread)
    from api.services import incident_service
    incident_service.record_approval(thread, "pytest", "rejected", [])
    try:
        final = await graph.ainvoke(Command(resume={"status": "rejected"}),
                                    config=config)
        assert final["approval"] == "rejected"
        assert (final.get("execution") or {}).get("executed") is not True
        agents = [s.get("agent") for s in final["timeline"]]
        assert "executor" not in agents
        assert "postmortem" in agents
    finally:
        stack.close()
        await _cleanup(thread)
