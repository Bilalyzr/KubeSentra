"""The multi-agent investigation graph (implementation document 4.4).

Phase 5 scope: triage -> supervisor loop (specialists) -> diagnose | escalate.
Phase 6/7 append: remediate -> approval interrupt -> execute -> verify ->
postmortem.
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph
from langgraph.checkpoint.base import BaseCheckpointSaver

from agent.nodes.approval import approval_node
from agent.nodes.diagnose import diagnose_node
from agent.nodes.escalate import escalate_node
from agent.nodes.k8s_state import k8s_node
from agent.nodes.logs import logs_node
from agent.nodes.metrics import metrics_node
from agent.nodes.remediation import remediation_node
from agent.nodes.supervisor import route_from_supervisor, supervisor_node
from agent.nodes.triage import triage_node
from agent.state import IncidentState


def build_graph(checkpointer: BaseCheckpointSaver | None = None):
    graph = StateGraph(IncidentState)

    graph.add_node("triage", triage_node)
    graph.add_node("supervisor", supervisor_node)
    graph.add_node("metrics_agent", metrics_node)
    graph.add_node("logs_agent", logs_node)
    graph.add_node("k8s_agent", k8s_node)
    graph.add_node("diagnose", diagnose_node)
    graph.add_node("remediate", remediation_node)
    graph.add_node("approval", approval_node)
    graph.add_node("escalate", escalate_node)

    graph.add_edge(START, "triage")
    graph.add_edge("triage", "supervisor")
    graph.add_conditional_edges(
        "supervisor", route_from_supervisor,
        ["metrics_agent", "logs_agent", "k8s_agent", "diagnose", "escalate"],
    )
    for specialist in ("metrics_agent", "logs_agent", "k8s_agent"):
        graph.add_edge(specialist, "supervisor")
    graph.add_edge("diagnose", "remediate")
    graph.add_edge("remediate", "approval")
    # Phase 7 replaces this edge with execute -> verify -> postmortem via
    # route_after_approval (approved/edited -> execute, rejected -> postmortem)
    graph.add_edge("approval", END)
    graph.add_edge("escalate", END)

    return graph.compile(checkpointer=checkpointer)
