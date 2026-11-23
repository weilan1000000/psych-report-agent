# -*- coding: utf-8 -*-
"""Run TextAgent batch validation samples and save per-sample results."""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from pathlib import Path
from typing import Any

ROOT_DIR_FOR_IMPORT = Path(__file__).resolve().parents[1]
if str(ROOT_DIR_FOR_IMPORT) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR_FOR_IMPORT))

from agent_team import (
    ROOT_DIR,
    ReportOrchestrator,
    RetrievalAgent,
    create_client,
    load_assessment_result,
    load_report_rubric,
)
from orchestrator import summarize_retrieval_result


DEFAULT_INPUT_DIR = ROOT_DIR / "samples" / "text_agent_batch"
DEFAULT_OUTPUT_DIR = ROOT_DIR / "output" / "text_agent_batch"


def main() -> None:
    args = parse_args()
    input_dir = args.input_dir
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    sample_paths = sorted(
        path for path in input_dir.glob("*.json") if path.name != "manifest.json"
    )
    if args.limit:
        sample_paths = sample_paths[: args.limit]

    if not sample_paths:
        raise FileNotFoundError(f"没有找到批量样本 JSON：{input_dir}")

    if args.dry_run:
        summary = run_dry_batch(sample_paths, output_dir)
    else:
        if not os.environ.get("DEEPSEEK_API_KEY"):
            raise RuntimeError(
                "没有找到 DEEPSEEK_API_KEY。请先在 PowerShell 中设置后再运行，"
                "或添加 --dry-run 只做本地样本/RAG 检查。"
            )
        summary = run_deepseek_batch(
            sample_paths,
            output_dir,
            args.max_rounds,
            resume=args.resume,
            fail_fast=args.fail_fast,
        )

    write_summary(output_dir, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--max-rounds", type=int, default=2)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Skip samples that already have a completed output .txt in the output dir.",
    )
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="Stop on the first failed sample instead of writing an error file and continuing.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only validate sample JSON and local RetrievalAgent hits; no DeepSeek calls.",
    )
    return parser.parse_args()


def run_dry_batch(sample_paths: list[Path], output_dir: Path) -> dict[str, Any]:
    retrieval_agent = RetrievalAgent()
    samples = []
    for sample_path in sample_paths:
        assessment_result = load_assessment_result(sample_path)
        retrieval_result = retrieval_agent.run(assessment_result)
        retrieval_summary = summarize_retrieval_result(retrieval_result)
        section_counts = {
            section: len(items)
            for section, items in retrieval_result.get(
                "retrieved_standard_segments_by_section", {}
            ).items()
        }

        text = render_dry_run_text(sample_path, assessment_result, retrieval_summary, section_counts)
        output_path = output_dir / f"{sample_path.stem}.txt"
        output_path.write_text(text, encoding="utf-8")

        samples.append(
            {
                "sample": sample_path.name,
                "profile_label": assessment_result.get("profile_label", ""),
                "status": "dry_run",
                "output_path": str(output_path),
                "standard_segment_count": retrieval_summary.get(
                    "standard_segment_count", 0
                ),
                "section_counts": section_counts,
            }
        )

    return {
        "mode": "dry_run",
        "sample_count": len(samples),
        "samples": samples,
    }


def run_deepseek_batch(
    sample_paths: list[Path],
    output_dir: Path,
    max_rounds: int,
    *,
    resume: bool = False,
    fail_fast: bool = False,
) -> dict[str, Any]:
    client = create_client()
    rubric = load_report_rubric()
    samples = []

    for sample_path in sample_paths:
        assessment_result = load_assessment_result(sample_path)
        output_path = output_dir / f"{sample_path.stem}.txt"
        if resume and output_path.exists():
            existing_summary = summarize_existing_result(
                sample_path,
                assessment_result,
                output_path,
            )
            if existing_summary:
                samples.append(existing_summary)
                write_summary(output_dir, build_deepseek_summary(samples))
                continue

        orchestrator = ReportOrchestrator(client=client, max_rounds=max_rounds)
        try:
            result = orchestrator.run(assessment_result)
            output_path.write_text(
                render_full_run_text(sample_path, rubric, result),
                encoding="utf-8",
            )
            samples.append(
                summarize_full_result(
                    sample_path,
                    assessment_result,
                    output_path,
                    result,
                )
            )
        except Exception as exc:
            error_path = output_dir / f"{sample_path.stem}.error.txt"
            error_path.write_text(
                "\n".join(
                    [
                        f"sample: {sample_path.name}",
                        f"profile_label: {assessment_result.get('profile_label', '')}",
                        f"error_type: {type(exc).__name__}",
                        f"error: {exc}",
                        "",
                        traceback.format_exc(),
                    ]
                ),
                encoding="utf-8",
            )
            samples.append(
                {
                    "sample": sample_path.name,
                    "profile_label": assessment_result.get("profile_label", ""),
                    "status": "failed",
                    "output_path": str(error_path),
                    "round_count": 0,
                    "used_feedback": False,
                    "final_score": None,
                    "pass": False,
                    "hard_failure_count": 0,
                    "major_issue_count": 1,
                    "minor_issue_count": 0,
                    "rule_issue_count": 0,
                    "unsupported_issue_count": 0,
                    "standard_segment_count": 0,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
            )
            write_summary(output_dir, build_deepseek_summary(samples))
            if fail_fast:
                raise
            continue

        write_summary(output_dir, build_deepseek_summary(samples))

    return build_deepseek_summary(samples)


def build_deepseek_summary(samples: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "mode": "deepseek",
        "sample_count": len(samples),
        "approved_count": sum(1 for item in samples if item["status"] == "approved"),
        "needs_human_review_count": sum(
            1 for item in samples if item["status"] == "needs_human_review"
        ),
        "failed_count": sum(1 for item in samples if item["status"] == "failed"),
        "samples": samples,
    }


def render_dry_run_text(
    sample_path: Path,
    assessment_result: dict[str, Any],
    retrieval_summary: dict[str, Any],
    section_counts: dict[str, int],
) -> str:
    return "\n".join(
        [
            "=== Dry Run ===",
            compact_json(
                {
                    "sample": sample_path.name,
                    "profile_label": assessment_result.get("profile_label", ""),
                    "note": "未调用 DeepSeek，仅检查样本 JSON 和本地 RAG 命中。",
                }
            ),
            "",
            "=== Retrieval Summary ===",
            compact_json(retrieval_summary),
            "",
            "=== Retrieved Section Counts ===",
            compact_json(section_counts),
            "",
        ]
    )


def render_full_run_text(
    sample_path: Path,
    rubric: dict[str, Any],
    result: dict[str, Any],
) -> str:
    lines = []
    lines.extend(
        [
            "=== Sample ===",
            compact_json({"sample": sample_path.name}),
            "",
            "=== Workflow Status ===",
            compact_json({"status": result["status"]}),
            "",
            "=== Rubric ===",
            compact_json(
                {
                    "name": rubric.get("name"),
                    "version": rubric.get("version"),
                    "pass_score": rubric.get("pass_score"),
                    "human_review_score_below": rubric.get("human_review_score_below"),
                }
            ),
            "",
            "=== Retrieval Summary ===",
            compact_json(summarize_retrieval_result(result["retrieval_result"])),
            "",
        ]
    )

    for iteration in result["iterations"]:
        lines.append(f"=== Round {iteration['round']} Report ===")
        lines.append(iteration["report"])
        lines.append("")
        lines.append("=== Rule Issues ===")
        lines.append(compact_json(iteration["check_result"]["rule_issues"]))
        lines.append("")
        lines.append("=== Unsupported Inference Issues ===")
        lines.append(compact_json(iteration["check_result"].get("unsupported_issues", [])))
        lines.append("")
        lines.append("=== Checker Result ===")
        lines.append(compact_json(iteration["check_result"]["llm_result"]))
        lines.append("")
        lines.append("=== Raw LLM Checker Result ===")
        lines.append(compact_json(iteration["check_result"].get("raw_llm_result", {})))
        lines.append("")
        if "feedback" in iteration:
            lines.append("=== Feedback Instructions ===")
            lines.append(compact_json(iteration["feedback"]))
            lines.append("")

    lines.extend(
        [
            "=== Final Report ===",
            result["final_report"],
            "",
            "=== Final Check ===",
            compact_json(result["final_check"]),
            "",
        ]
    )
    return "\n".join(lines)


def summarize_full_result(
    sample_path: Path,
    assessment_result: dict[str, Any],
    output_path: Path,
    result: dict[str, Any],
) -> dict[str, Any]:
    final_check = result.get("final_check", {})
    llm_result = final_check.get("llm_result", {})
    retrieval_summary = result.get("retrieval_result", {}).get("retrieval_summary", {})

    return {
        "sample": sample_path.name,
        "profile_label": assessment_result.get("profile_label", ""),
        "status": result.get("status"),
        "output_path": str(output_path),
        "round_count": len(result.get("iterations", [])),
        "used_feedback": any("feedback" in item for item in result.get("iterations", [])),
        "final_score": llm_result.get("total_score"),
        "pass": llm_result.get("pass"),
        "hard_failure_count": len(llm_result.get("hard_failures", [])),
        "major_issue_count": len(llm_result.get("major_issues", [])),
        "minor_issue_count": len(llm_result.get("minor_issues", [])),
        "rule_issue_count": len(final_check.get("rule_issues", [])),
        "unsupported_issue_count": len(final_check.get("unsupported_issues", [])),
        "standard_segment_count": retrieval_summary.get("standard_segment_count", 0),
    }


def summarize_existing_result(
    sample_path: Path,
    assessment_result: dict[str, Any],
    output_path: Path,
) -> dict[str, Any] | None:
    text = output_path.read_text(encoding="utf-8", errors="replace")
    final_check = extract_json_marker_block(text, "=== Final Check ===")
    if not isinstance(final_check, dict):
        return None

    workflow_status = extract_json_marker_block(text, "=== Workflow Status ===")
    retrieval_summary = extract_json_marker_block(text, "=== Retrieval Summary ===")
    llm_result = final_check.get("llm_result", {})

    return {
        "sample": sample_path.name,
        "profile_label": assessment_result.get("profile_label", ""),
        "status": (
            workflow_status.get("status")
            if isinstance(workflow_status, dict)
            else "existing"
        ),
        "output_path": str(output_path),
        "round_count": text.count("=== Round "),
        "used_feedback": "=== Feedback Instructions ===" in text,
        "final_score": llm_result.get("total_score"),
        "pass": llm_result.get("pass"),
        "hard_failure_count": len(llm_result.get("hard_failures", [])),
        "major_issue_count": len(llm_result.get("major_issues", [])),
        "minor_issue_count": len(llm_result.get("minor_issues", [])),
        "rule_issue_count": len(final_check.get("rule_issues", [])),
        "unsupported_issue_count": len(final_check.get("unsupported_issues", [])),
        "standard_segment_count": (
            retrieval_summary.get("standard_segment_count", 0)
            if isinstance(retrieval_summary, dict)
            else 0
        ),
        "resumed_from_existing_output": True,
    }


def extract_json_marker_block(text: str, marker: str) -> Any:
    start = text.find(marker)
    if start < 0:
        return None

    start += len(marker)
    next_marker = text.find("\n===", start)
    if next_marker < 0:
        block = text[start:].strip()
    else:
        block = text[start:next_marker].strip()

    try:
        return json.loads(block)
    except json.JSONDecodeError:
        return None


def write_summary(output_dir: Path, summary: dict[str, Any]) -> None:
    (output_dir / "batch_summary.json").write_text(
        compact_json(summary),
        encoding="utf-8",
    )
    (output_dir / "batch_summary.md").write_text(
        render_summary_markdown(summary),
        encoding="utf-8",
    )


def render_summary_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# TextAgent Batch Summary",
        "",
        f"- mode: {summary.get('mode')}",
        f"- sample_count: {summary.get('sample_count')}",
    ]
    if summary.get("mode") == "deepseek":
        lines.extend(
            [
                f"- approved_count: {summary.get('approved_count')}",
                f"- needs_human_review_count: {summary.get('needs_human_review_count')}",
                f"- failed_count: {summary.get('failed_count', 0)}",
            ]
        )
    lines.extend(["", "## Samples"])
    for item in summary.get("samples", []):
        lines.append(
            "- {sample}: {status}, score={score}, rounds={rounds}, rag={rag}, output={output}".format(
                sample=item.get("sample"),
                status=item.get("status"),
                score=item.get("final_score", ""),
                rounds=item.get("round_count", ""),
                rag=item.get("standard_segment_count", ""),
                output=item.get("output_path"),
            )
        )
        if item.get("profile_label"):
            lines.append(f"  profile: {item['profile_label']}")
        if item.get("error"):
            lines.append(f"  error: {item.get('error_type')}: {item.get('error')}")
    return "\n".join(lines) + "\n"


def compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
