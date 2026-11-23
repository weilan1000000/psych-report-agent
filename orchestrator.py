# -*- coding: utf-8 -*-
"""DEBUG ENTRY POINT: run the current text workflow without PDF rendering.

For a production-equivalent local run, use scripts/generate_full_pdf_report.py.
"""
import argparse
import io
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any

from agent_team import (
    DEFAULT_INPUT_PATH,
    ReportOrchestrator,
    create_client,
    load_assessment_result,
    load_report_rubric,
)


def print_json(title: str, value: Any) -> None:
    print(f"\n=== {title} ===")
    print(json.dumps(value, ensure_ascii=False, indent=2))


def print_iteration_summary(iteration: dict[str, Any]) -> None:
    check = iteration["check_result"]["llm_result"]
    print(f"\n=== Round {iteration['round']} Report ===")
    print(iteration["report"])
    print_json("Rule Issues", iteration["check_result"]["rule_issues"])
    print_json("Unsupported Inference Issues", iteration["check_result"].get("unsupported_issues", []))
    print_json("Checker Result", check)
    print_json("Raw LLM Checker Result", iteration["check_result"].get("raw_llm_result", {}))

    if "feedback" in iteration:
        print_json("Feedback Instructions", iteration["feedback"])


def summarize_retrieval_result(retrieval_result: dict[str, Any]) -> dict[str, Any]:
    retrieval_summary = retrieval_result.get("retrieval_summary", {})
    return {
        "has_scale_notes": bool(retrieval_result.get("scale_notes")),
        "has_style_notes": bool(retrieval_result.get("style_notes")),
        "retrieved_example_count": len(retrieval_result.get("retrieved_examples", [])),
        "standard_segment_count": retrieval_summary.get("standard_segment_count", 0),
        "standard_segment_source": retrieval_summary.get("standard_segment_source", ""),
        "standard_segment_strategy": retrieval_summary.get("strategy", ""),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_path", nargs="?", type=Path, default=DEFAULT_INPUT_PATH)
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional UTF-8 text file path for saving the full console result.",
    )
    return parser.parse_args()


def run_workflow(input_path: Path) -> None:
    assessment_result = load_assessment_result(input_path)
    rubric = load_report_rubric()

    orchestrator = ReportOrchestrator(client=create_client(), max_rounds=2)
    result = orchestrator.run(assessment_result)

    print_json("Workflow Status", {"status": result["status"]})
    print_json(
        "Rubric",
        {
            "name": rubric.get("name"),
            "version": rubric.get("version"),
            "pass_score": rubric.get("pass_score"),
            "human_review_score_below": rubric.get("human_review_score_below"),
        },
    )
    print_json("Retrieval Summary", summarize_retrieval_result(result["retrieval_result"]))

    for iteration in result["iterations"]:
        print_iteration_summary(iteration)

    print("\n=== Final Report ===")
    print(result["final_report"])
    print_json("Final Check", result["final_check"])


def main() -> None:
    args = parse_args()

    if not args.output:
        run_workflow(args.input_path)
        return

    buffer = io.StringIO()
    with redirect_stdout(buffer):
        run_workflow(args.input_path)

    text = buffer.getvalue()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")
    sys.stdout.write(text)


if __name__ == "__main__":
    main()
