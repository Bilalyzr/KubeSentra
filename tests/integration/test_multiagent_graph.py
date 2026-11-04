"""Integration test: the FULL multi-agent graph runs end to end with fake
LLMs and a fake specialist - verifying orchestration, budgets, append-only
evidence and citation grounding without any LLM quota or live cluster.

Requires PostgreSQL (evidence_raw + audit writes).
"""

import uuid
from typing import ClassVar

import pytest
from langchain_core.language_models.chat_models import BaseChatModel, ChatResult
from langchain_core.messages import AIMessageChunk
from langchain_core.outputs import ChatGenerationChunk

from agent.state import Evidence, Hypothesis
from database.connection import get_pool

pytestmark = pytest.mark.integration


class FakeLLM(BaseChatModel):
    """Pops scripted plain-text responses from a shared queue."""
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
    pytest.skip("PostgreSQL not reachable - run `docker compose up -d postgres`",
                allow_module_level=True)


TRIAGE_HYPS = ('[{"cause": "memory limit too low", "category": "resource",'
               ' "confidence": 0.4, "supporting": ["E2"], "refuting": []},'
               ' {"cause": "bad rollout", "category": "change",'
               ' "confidence": 0.3, "supporting": [], "refuting": []}]')
SUPERVISOR_CHOICE = ('{"next_agent": "metrics_agent", "question": '
                     '"check restarts and memory for checkoutservice", '
                     '"rationale": "leading hypothesis is resource"}')
DIAGNOSIS = ('{"root_cause": "memory limit too low", "category": "resource",'
             ' "confidence": 0.9, "supporting_evidence": ["E1", "E3", "E9"],'
             ' "alternative_causes": [{"cause": "bad rollout",'
             ' "why_less_likely": "no rollout events"}],'
             ' "explanation": "Restarts rose while limits were cut.",'
             ' "evidence_cited": ["E3"]}')


async def fake_specialist(agent_name: str, state, llm=None, tools=None) -> dict:
    ev = Evidence(id=f"E{len(state.get('evidence', [])) + 1}", source="metrics",
                  summary="restart count rising 4 -> 11 in 10m", raw_ref="test")
    return {
        "evidence": [ev],
        "hypotheses": [Hypothesis(cause="memory limit too low",
                                  category="resource", confidence=0.85,
                                  supporting=["E1", ev.id])],
        "steps_used": state.get("steps_used", 0) + 1,
        "timeline": [{"agent": agent_name, "tool_calls": ["query_template"],
                      "evidence_added": [ev.id]}],
    }


@pytest.fixture
def patched_graph(monkeypatch):
    # triage hyps, supervisor choice, diagnosis, planner proposes nothing ([]),
    # approval is reached via the interrupt
    FakeLLM.queue = [TRIAGE_HYPS, SUPERVISOR_CHOICE, DIAGNOSIS, "[]"]
    monkeypatch.setattr("agent.nodes.triage.build_llm", lambda role="primary": FakeLLM())
    monkeypatch.setattr("agent.nodes.supervisor.build_llm", lambda role="primary": FakeLLM())
    monkeypatch.setattr("agent.nodes.diagnose.build_llm", lambda role="primary": FakeLLM())
    monkeypatch.setattr("agent.nodes.remediation.build_llm", lambda role="primary": FakeLLM())
    # triage imports these lazily inside the node -> patch at the source
    monkeypatch.setattr("mcp_servers.knowledge.server.search_incidents",
                        lambda query, service=None, limit=5: "(no matching incidents)")
    monkeypatch.setattr("mcp_servers.knowledge.server.search_similar_incidents",
                        lambda query, service=None, limit=3: "(none)")
    monkeypatch.setattr("mcp_servers.k8s_read.server.list_pods",
                        lambda namespace=None, label_selector=None:
                        "NAME READY STATUS RESTARTS AGE NODE\n"
                        "checkoutservice-6fd54f5c78-gdtds 0/1 CrashLoopBackOff 6 5m worker")
    monkeypatch.setattr("agent.nodes.specialist.run_specialist", fake_specialist)
    # Phase 6 tail: planner gets no runbooks and stubs the dry run
    # (remediation imports hybrid_search lazily -> patch at the source)
    monkeypatch.setattr("mcp_servers.knowledge.server.hybrid_search_runbooks",
                        lambda query, limit=4: [])
    monkeypatch.setattr("agent.nodes.remediation.dry_run_action",
                        lambda action: {"ok": True, "detail": "stub"})
    yield
    FakeLLM.queue = []


async def test_graph_diagnosis_flow_with_grounding(patched_graph):
    from langgraph.checkpoint.postgres import PostgresSaver
    from langgraph.types import Command

    from agent.graph import build_graph
    from agent.graph_runner import AsyncCheckpointerAdapter
    from common.config import get_settings

    incident_id = str(uuid.uuid4())
    with PostgresSaver.from_conn_string(get_settings().database_url) as saver:
        saver.setup()
        graph = build_graph(checkpointer=AsyncCheckpointerAdapter(saver))
        config = {"configurable": {"thread_id": incident_id}}
        final = await graph.ainvoke({
            "incident_id": incident_id,
            "alert": {"labels": {"alertname": "PodRestarting",
                                 "namespace": "boutique",
                                 "pod": "checkoutservice-6fd54f5c78-gdtds"}},
            "namespace": "boutique", "service": "checkoutservice",
        }, config=config)

        try:
            # orchestration: triage -> supervisor -> metrics specialist ->
            # supervisor (hard rule) -> diagnose -> remediate -> PAUSE
            agents = [s.get("agent") for s in final["timeline"]]
            assert agents[0] == "triage"
            assert "metrics_agent" in agents
            assert "diagnose" in agents
            assert "remediation" in agents
            assert final["steps_used"] == 1  # budget respected

            # append-only evidence: triage E1+E2, specialist E3
            assert [e.id for e in final["evidence"]] == ["E1", "E2", "E3"]

            # GROUNDING: the diagnosis cited E9 which does not exist -> dropped
            report = final["report"]
            assert report.supporting_evidence == ["E1", "E3"]
            assert "E9" not in report.evidence_cited + report.supporting_evidence
            assert report.root_cause == "memory limit too low"

            # Phase 6: graph paused at the approval interrupt (empty plan)
            assert final.get("__interrupt__"), "expected approval interrupt"
            payload = final["__interrupt__"][0].value
            assert payload["root_cause"] == "memory limit too low"
            done = await graph.ainvoke(
                Command(resume={"status": "rejected"}), config=config)
            assert done["approval"] == "rejected"
        finally:
            with get_pool().connection() as conn:
                conn.execute("DELETE FROM evidence_raw WHERE incident_id = %s::uuid",
                             (incident_id,))
                conn.execute("DELETE FROM audit_log WHERE incident_id = %s::uuid",
                             (incident_id,))


async def test_graph_escalates_on_budget_exhaustion(patched_graph, monkeypatch):
    from common.config import get_settings

    monkeypatch.setenv("MAX_INVESTIGATION_STEPS", "2")
    get_settings.cache_clear()
    FakeLLM.queue = [TRIAGE_HYPS] + [SUPERVISOR_CHOICE] * 10

    async def weak_specialist(agent_name, state, llm=None, tools=None):
        delta = await fake_specialist(agent_name, state)
        delta["hypotheses"] = [Hypothesis(cause="unclear", category="other",
                                          confidence=0.3)]
        return delta

    import agent.nodes.specialist as specialist_module
    monkeypatch.setattr(specialist_module, "run_specialist", weak_specialist)

    from agent.graph import build_graph
    incident_id = str(uuid.uuid4())
    graph = build_graph()
    final = await graph.ainvoke({
        "incident_id": incident_id,
        "alert": {"labels": {"alertname": "X", "namespace": "boutique"}},
        "namespace": "boutique", "service": "checkoutservice",
    })
    try:
        assert final["outcome"]["escalated"] is True
        assert final["steps_used"] == 2  # exactly the budget, never more
        assert "budget" in final["outcome"]["human_summary"].lower()
    finally:
        with get_pool().connection() as conn:
            conn.execute("DELETE FROM evidence_raw WHERE incident_id = %s::uuid",
                         (incident_id,))
            conn.execute("DELETE FROM audit_log WHERE incident_id = %s::uuid",
                         (incident_id,))
        get_settings.cache_clear()
