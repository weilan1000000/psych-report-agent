# -*- coding: utf-8 -*-
"""Generate a parent-facing illustrated PDF report with DeepSeek + local renderer.

Pipeline:
1. Load one assessment JSON.
2. Run the existing TextAgent -> CheckerAgent -> FeedbackAgent workflow.
3. Save the TextAgent result in the same marker format used by batch outputs.
4. Render the latest hybrid PDF design with Playwright.

The DeepSeek API key is read from DEEPSEEK_API_KEY only. Do not put keys in this file.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from agent_team import (  # noqa: E402
    ReportOrchestrator,
    create_client,
    load_assessment_result,
    load_report_rubric,
)
from scripts.run_text_agent_batch import (  # noqa: E402
    render_full_run_text,
    summarize_full_result,
)
from quality_review import (  # noqa: E402
    build_quality_review,
    render_quality_review_html,
)


DEFAULT_INPUT_PATH = ROOT_DIR / "templates" / "assessment_input_example_26_metrics.json"
DEFAULT_OUTPUT_DIR = ROOT_DIR / "output" / "full_pdf_report" / "latest"
DEFAULT_THEME = "hybrid_expert_dashboard"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run DeepSeek report text generation and render a full PDF report.",
    )
    parser.add_argument(
        "input_path",
        nargs="?",
        type=Path,
        default=DEFAULT_INPUT_PATH,
        help="Assessment JSON path. The default is a synthetic elementary-school example.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Output directory. Default: output/full_pdf_report/latest",
    )
    parser.add_argument(
        "--max-rounds",
        type=int,
        default=2,
        help="Maximum TextAgent/Checker/Feedback rounds. Default: 2",
    )
    parser.add_argument(
        "--quality-target-score",
        type=int,
        default=90,
        help=(
            "If the report passes but scores below this value, run a polish round "
            "when max rounds allow it. Default: 90"
        ),
    )
    polish_group = parser.add_mutually_exclusive_group()
    polish_group.add_argument(
        "--polish-minor-issues",
        dest="polish_minor_issues",
        action="store_true",
        help="Run an optional extra rewrite for minor issues after an approved draft.",
    )
    polish_group.add_argument(
        "--no-polish-minor-issues",
        dest="polish_minor_issues",
        action="store_false",
        help="Deprecated compatibility flag; approved drafts are no longer polished by default.",
    )
    parser.set_defaults(polish_minor_issues=False)
    parser.add_argument(
        "--theme",
        default=DEFAULT_THEME,
        help="Renderer theme name. Default: hybrid_expert_dashboard",
    )
    parser.add_argument(
        "--render-review-draft",
        action="store_true",
        help=(
            "Render a clearly non-final preview when the workflow needs human review "
            "but has no hard safety failures."
        ),
    )
    parser.add_argument(
        "--node",
        default="node",
        help="Node.js executable for Playwright renderer. Default: node",
    )
    return parser.parse_args()


def safe_render_stem(input_path: Path) -> str:
    stem = input_path.stem
    stem = re.sub(r"[^0-9A-Za-z_\-\u4e00-\u9fff]+", "_", stem).strip("_")
    if not stem:
        stem = "report"
    if not stem.startswith("sample_"):
        stem = f"sample_{stem}"
    return stem


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_report_json(report_text: str) -> dict[str, Any] | None:
    try:
        parsed = json.loads(report_text)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def require_deepseek_key() -> None:
    if not os.environ.get("DEEPSEEK_API_KEY"):
        raise RuntimeError(
            "没有找到 DEEPSEEK_API_KEY。请先在 PowerShell 中运行："
            '$env:DEEPSEEK_API_KEY="你的 key"'
        )


def render_pdf(
    *,
    node_exe: str,
    text_dir: Path,
    sample_dir: Path,
    pdf_dir: Path,
    theme: str,
) -> None:
    renderer = ROOT_DIR / "scripts" / "render_report_variants_from_text_batch.js"
    command = [
        node_exe,
        str(renderer),
        str(text_dir),
        str(sample_dir),
        str(pdf_dir),
        theme,
    ]
    subprocess.run(command, cwd=ROOT_DIR, check=True)


def validate_rendered_outputs(pdf_outputs: list[dict[str, Any]]) -> dict[str, Any]:
    """Verify renderer artifacts before reporting a PDF path as ready."""
    errors: list[str] = []
    if not pdf_outputs:
        errors.append("renderer manifest does not contain a PDF output")

    for index, item in enumerate(pdf_outputs):
        for key in ("htmlPath", "pdfPath", "pngPath"):
            value = item.get(key, "")
            if not value or not Path(value).is_file() or Path(value).stat().st_size == 0:
                errors.append(f"output[{index}] missing or empty {key}")

        page_count = item.get("pageCount")
        page_checks = item.get("pageCheckPaths", [])
        if not isinstance(page_count, int) or page_count < 1:
            errors.append(f"output[{index}] has invalid pageCount")
            continue
        if not isinstance(page_checks, list) or len(page_checks) != page_count:
            errors.append(f"output[{index}] page screenshot count does not match pageCount")
            continue
        for page_path in page_checks:
            path = Path(page_path)
            if not path.is_file() or path.stat().st_size == 0:
                errors.append(f"output[{index}] missing or empty page screenshot: {page_path}")

    return {
        "pass": not errors,
        "pdf_output_count": len(pdf_outputs),
        "errors": errors,
    }


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

    args = parse_args()
    input_path = args.input_path.resolve()
    output_dir = args.output_dir.resolve()

    if not input_path.exists():
        raise FileNotFoundError(f"输入 JSON 不存在：{input_path}")
    require_deepseek_key()

    render_stem = safe_render_stem(input_path)
    text_dir = output_dir / "text_agent"
    sample_dir = output_dir / "samples"
    pdf_dir = output_dir / "pdf"

    text_dir.mkdir(parents=True, exist_ok=True)
    sample_dir.mkdir(parents=True, exist_ok=True)
    pdf_dir.mkdir(parents=True, exist_ok=True)

    assessment_result = load_assessment_result(input_path)
    rubric = load_report_rubric()

    polish_minor_issues = args.polish_minor_issues
    print(f"[1/3] Running TextAgent workflow: {input_path}")
    print(
        "[1/3] Quality polish gate: "
        f"target_score={args.quality_target_score}, "
        f"polish_minor_issues={polish_minor_issues}, "
        f"max_rounds={args.max_rounds}"
    )
    orchestrator = ReportOrchestrator(
        client=create_client(),
        max_rounds=args.max_rounds,
        quality_target_score=args.quality_target_score,
        polish_minor_issues=polish_minor_issues,
    )
    result = orchestrator.run(assessment_result)

    text_output_path = text_dir / f"{render_stem}.txt"
    text_output_path.write_text(
        render_full_run_text(input_path, rubric, result),
        encoding="utf-8",
    )

    sample_copy_path = sample_dir / f"{render_stem}.json"
    write_json(sample_copy_path, assessment_result)

    final_report_json = parse_report_json(result.get("final_report", ""))
    if final_report_json is not None:
        write_json(output_dir / "final_report.json", final_report_json)
    else:
        (output_dir / "final_report.raw.txt").write_text(
            result.get("final_report", ""),
            encoding="utf-8",
        )
    write_json(output_dir / "final_check.json", result.get("final_check", {}))
    write_json(
        output_dir / "retrieval_trace.json",
        result.get("retrieval_result", {}),
    )

    text_summary = summarize_full_result(
        input_path,
        assessment_result,
        text_output_path,
        result,
    )
    write_json(output_dir / "text_summary.json", text_summary)

    final_llm_result = result.get("final_check", {}).get("llm_result", {})
    has_hard_failures = bool(final_llm_result.get("hard_failures", []))
    review_draft_will_render = (
        result.get("status") != "approved"
        and args.render_review_draft
        and final_report_json is not None
        and not has_hard_failures
    )
    quality_review = build_quality_review(
        result,
        target_score=args.quality_target_score,
        review_draft_rendered=review_draft_will_render,
    )
    quality_review_json_path = output_dir / "quality_review.json"
    quality_review_html_path = output_dir / "quality_review.html"
    write_json(quality_review_json_path, quality_review)
    quality_review_html_path.write_text(
        render_quality_review_html(quality_review),
        encoding="utf-8",
    )

    render_mode = "approved"
    if result.get("status") != "approved":
        can_render_review_draft = review_draft_will_render
        if can_render_review_draft:
            render_mode = "review_draft"
            print(
                "[2/3] Rendering a review draft; do not deliver it to parents before human review."
            )
        else:
            if args.render_review_draft and has_hard_failures:
                print(
                    "[2/3] Review draft was not rendered because hard safety failures were found."
                )
            summary = {
                "status": result.get("status"),
                "input_path": str(input_path),
                "output_dir": str(output_dir),
                "text_output_path": str(text_output_path),
                "final_report_json_path": str(output_dir / "final_report.json")
                if final_report_json is not None
                else "",
                "final_check_path": str(output_dir / "final_check.json"),
                "quality_review_json_path": str(quality_review_json_path),
                "quality_review_html_path": str(quality_review_html_path),
                "pdf_outputs": [],
                "text_summary": text_summary,
                "next_step": (
                    "请先打开 quality_review.html，按其中列出的阻断问题和主要问题逐项处理；"
                    "当前草稿不可直接交付。"
                ),
            }
            write_json(output_dir / "run_summary.json", summary)
            print("[2/3] Text quality was not approved; the draft and check result were saved.")
            print(f"      Draft: {text_output_path}")
            print(f"      Review guide: {quality_review_html_path}")
            print(f"      Raw check: {output_dir / 'final_check.json'}")
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            return

    if render_mode == "approved":
        print(f"[2/3] Rendering PDF with theme: {args.theme}")
    render_pdf(
        node_exe=args.node,
        text_dir=text_dir,
        sample_dir=sample_dir,
        pdf_dir=pdf_dir,
        theme=args.theme,
    )

    manifest_path = pdf_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    pdf_outputs = manifest if isinstance(manifest, list) else []
    render_validation = validate_rendered_outputs(pdf_outputs)
    if not render_validation["pass"]:
        raise RuntimeError(
            "PDF renderer artifact validation failed: "
            + "; ".join(render_validation["errors"])
        )

    summary = {
        "status": "review_draft_rendered"
        if render_mode == "review_draft"
        else result.get("status"),
        "render_mode": render_mode,
        "input_path": str(input_path),
        "output_dir": str(output_dir),
        "text_output_path": str(text_output_path),
        "sample_copy_path": str(sample_copy_path),
        "final_report_json_path": str(output_dir / "final_report.json")
        if final_report_json is not None
        else "",
        "final_check_path": str(output_dir / "final_check.json"),
        "quality_review_json_path": str(quality_review_json_path),
        "quality_review_html_path": str(quality_review_html_path),
        "pdf_index_path": str(pdf_dir / "index.html"),
        "pdf_outputs": pdf_outputs,
        "render_validation": render_validation,
        "input_quality": assessment_result.get("input_quality", {}),
        "quality_polish": {
            "quality_target_score": args.quality_target_score,
            "polish_minor_issues": polish_minor_issues,
            "max_rounds": args.max_rounds,
            "used_feedback": any(
                "feedback" in item for item in result.get("iterations", [])
            ),
            "round_count": len(result.get("iterations", [])),
        },
        "text_summary": text_summary,
    }
    write_json(output_dir / "run_summary.json", summary)

    print("[3/3] Done.")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(
            f"[ERROR] PDF generation stopped: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        print(
            "提示：请检查 DEEPSEEK_API_KEY、DEEPSEEK_MODEL=deepseek-chat、网络连接，"
            "以及本次输出目录中的 final_check.json。",
            file=sys.stderr,
        )
        sys.exit(1)
