from __future__ import annotations

import os
from typing import Any

from .graph import GraphDeps, build_report_graph


def _build_checkpointer():
    if os.environ.get("REPORT_GRAPH_CHECKPOINT", "").strip().lower() == "memory":
        from langgraph.checkpoint.memory import InMemorySaver

        return InMemorySaver()
    return None


class GraphReportOrchestrator:
    """Run the existing agents through a state graph without changing the result envelope."""

    def __init__(self, deps: GraphDeps) -> None:
        deps.checkpointer = deps.checkpointer or _build_checkpointer()
        self.deps = deps
        self.graph = build_report_graph(deps)

    def run(self, assessment_result: dict[str, Any]) -> dict[str, Any]:
        config: dict[str, Any] = {
            "recursion_limit": 10 + 8 * max(1, self.deps.max_rounds),
        }
        if self.deps.checkpointer is not None:
            config["configurable"] = {"thread_id": "report-run"}
        state = self.graph.invoke({"assessment_result": assessment_result}, config)
        result: dict[str, Any] = {
            "status": state.get("status", "needs_human_review"),
            "retrieval_result": state.get("retrieval_result", {}),
            "iterations": state.get("iterations", []),
            "final_report": state.get("final_report", ""),
            "final_check": state.get("final_check", {}),
        }
        if state.get("approval_note"):
            result["approval_note"] = state["approval_note"]
        return result
