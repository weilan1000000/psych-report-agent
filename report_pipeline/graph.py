from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from langgraph.graph import END, START, StateGraph

from .models.state import ReportState


@dataclass
class GraphDeps:
    normalize_assessment: Callable[[dict[str, Any]], dict[str, Any]]
    retrieval_agent: Any
    planner_agent: Any
    metric_writer_agent: Any
    generator_agent: Any
    checker_agent: Any
    feedback_agent: Any
    patch_agent: Any
    needs_quality_polish: Callable[[dict[str, Any]], bool]
    transient_errors: tuple[type[BaseException], ...]
    max_rounds: int = 2
    checkpointer: Any = None
    extra: dict[str, Any] = field(default_factory=dict)


def _runtime_iteration(round_index: int, exc: BaseException) -> dict[str, Any]:
    return {
        "round": round_index,
        "passed": False,
        "runtime_error": f"{type(exc).__name__}: {exc}",
    }


def build_report_graph(deps: GraphDeps):
    """Build a LangGraph wrapper with control-flow parity to the legacy loop."""

    def prepare(state: ReportState) -> dict[str, Any]:
        assessment = deps.normalize_assessment(state["assessment_result"])
        retrieval = deps.retrieval_agent.run(assessment)
        plan = deps.planner_agent.run(assessment, retrieval)
        retrieval["writing_plan"] = plan
        return {
            "assessment_result": assessment,
            "retrieval_result": retrieval,
            "writing_plan": plan,
            "detail_blocks": None,
            "iterations": [],
            "approved_candidate": None,
            "feedback": None,
            "final_report": "",
            "final_check": {},
            "round_index": 1,
            "repair_mode": "initial_generation",
            "repair_note": "",
            "patch_failed": False,
            "jump_finalize": False,
            "approval_note": "",
        }

    def guard(state: ReportState, exc: BaseException) -> dict[str, Any]:
        iterations = [*state.get("iterations", []), _runtime_iteration(state.get("round_index", 1), exc)]
        if state.get("approved_candidate") is not None:
            return {"iterations": iterations, "jump_finalize": True}
        raise exc

    def write_metrics(state: ReportState) -> dict[str, Any]:
        try:
            return {"detail_blocks": deps.metric_writer_agent.run(state["writing_plan"])}
        except deps.transient_errors as exc:
            return guard(state, exc)

    def generate(state: ReportState) -> dict[str, Any]:
        if state.get("jump_finalize"):
            return {}
        kwargs: dict[str, Any] = {
            "assessment_result": state["assessment_result"],
            "retrieval_result": state["retrieval_result"],
            "writing_plan": state["writing_plan"],
            "detail_blocks": state.get("detail_blocks"),
        }
        if state.get("round_index", 1) > 1:
            kwargs["feedback"] = state.get("feedback") or {}
        try:
            return {"report": deps.generator_agent.run(**kwargs)}
        except deps.transient_errors as exc:
            return guard(state, exc)

    def patch_report(state: ReportState) -> dict[str, Any]:
        try:
            report = deps.patch_agent.run(
                assessment_result=state["assessment_result"],
                report=state["final_report"],
                writing_plan=state["writing_plan"],
                feedback=state.get("feedback") or {},
            )
        except ValueError as exc:
            return {
                "patch_failed": True,
                "repair_mode": "targeted_recompose_fallback",
                "repair_note": f"{type(exc).__name__}: {exc}",
            }
        except deps.transient_errors as exc:
            return guard(state, exc)
        return {"report": report, "patch_failed": False}

    def check(state: ReportState) -> dict[str, Any]:
        if state.get("jump_finalize"):
            return {"next_step": "finalize"}
        round_index = state.get("round_index", 1)
        try:
            check_result = deps.checker_agent.run(state["assessment_result"], state["report"])
        except deps.transient_errors as exc:
            update = guard(state, exc)
            update["next_step"] = "finalize"
            return update

        passed = deps.checker_agent.passed(check_result)
        iteration: dict[str, Any] = {
            "round": round_index,
            "report": state["report"],
            "check_result": check_result,
            "passed": passed,
            "repair_mode": state.get("repair_mode", "initial_generation"),
        }
        if state.get("repair_note"):
            iteration["repair_note"] = state["repair_note"]
        update: dict[str, Any] = {
            "check_result": check_result,
            "passed": passed,
            "final_report": state["report"],
            "final_check": check_result,
        }
        if passed:
            update["approved_candidate"] = {
                "report": state["report"],
                "check": check_result,
                "round": round_index,
            }
            needs_polish = deps.needs_quality_polish(check_result)
            iteration["needs_quality_polish"] = needs_polish
            update["needs_polish"] = needs_polish
            if not needs_polish or round_index >= deps.max_rounds:
                update.update(
                    iterations=[*state.get("iterations", []), iteration],
                    next_step="finalize",
                    immediate_approval=True,
                )
                return update
            update.update(
                iterations=state.get("iterations", []),
                next_step="feedback",
                _pending_iteration=iteration,
            )
            return update
        if round_index < deps.max_rounds:
            update.update(
                iterations=state.get("iterations", []),
                next_step="feedback",
                _pending_iteration=iteration,
            )
            return update
        update.update(
            iterations=[*state.get("iterations", []), iteration],
            next_step="finalize",
        )
        return update

    def feedback(state: ReportState) -> dict[str, Any]:
        iteration = dict(state.get("_pending_iteration") or {})
        iterations = list(state.get("iterations", []))
        if state.get("passed"):
            try:
                feedback_value = deps.feedback_agent.run(
                    assessment_result=state["assessment_result"],
                    report=state["report"],
                    check_result=state["check_result"],
                )
            except deps.transient_errors as exc:
                iteration["polish_runtime_error"] = f"{type(exc).__name__}: {exc}"
                iterations.append(iteration)
                return {"iterations": iterations, "jump_finalize": True, "next_step": "finalize"}
            iteration["feedback"] = feedback_value
            iteration["polish_reason"] = "passed_but_below_quality_target_or_has_minor_issues"
        else:
            feedback_value = deps.feedback_agent.run(
                assessment_result=state["assessment_result"],
                report=state["report"],
                check_result=state["check_result"],
            )
            iteration["feedback"] = feedback_value
        iterations.append(iteration)
        return {
            "iterations": iterations,
            "feedback": feedback_value,
            "round_index": state.get("round_index", 1) + 1,
            "repair_mode": "targeted_patch",
            "repair_note": "",
            "next_step": "patch",
        }

    def finalize(state: ReportState) -> dict[str, Any]:
        candidate = state.get("approved_candidate")
        if candidate is None:
            return {"status": "needs_human_review"}
        update: dict[str, Any] = {
            "status": "approved",
            "final_report": candidate["report"],
            "final_check": candidate["check"],
        }
        if not state.get("immediate_approval"):
            update["approval_note"] = (
                "A later optional polish round was not approved; "
                f"retained the approved report from round {candidate['round']}."
            )
        return update

    graph = StateGraph(ReportState)
    graph.add_node("prepare", prepare)
    graph.add_node("write_metrics", write_metrics)
    graph.add_node("generate", generate)
    graph.add_node("patch", patch_report)
    graph.add_node("check", check)
    graph.add_node("feedback", feedback)
    graph.add_node("finalize", finalize)
    graph.add_edge(START, "prepare")
    graph.add_edge("prepare", "write_metrics")
    graph.add_conditional_edges("write_metrics", lambda s: "finalize" if s.get("jump_finalize") else "generate")
    graph.add_conditional_edges("generate", lambda s: "finalize" if s.get("jump_finalize") else "check")
    graph.add_conditional_edges(
        "patch",
        lambda s: "finalize" if s.get("jump_finalize") else ("generate" if s.get("patch_failed") else "check"),
    )
    graph.add_conditional_edges("check", lambda s: "feedback" if s.get("next_step") == "feedback" else "finalize")
    graph.add_conditional_edges("feedback", lambda s: "finalize" if s.get("jump_finalize") else "patch")
    graph.add_edge("finalize", END)
    return graph.compile(checkpointer=deps.checkpointer)
