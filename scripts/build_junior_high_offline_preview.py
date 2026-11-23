"""Build a deterministic junior-high report fixture without calling an LLM."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent_team import (
    ReportPlannerAgent,
    RetrievalAgent,
    _compose_controlled_metric_block,
    load_assessment_result,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a student-facing junior-high report fixture for renderer checks."
    )
    parser.add_argument(
        "input",
        nargs="?",
        default=str(ROOT / "samples" / "sample_synthetic_junior_high_demo.json"),
    )
    parser.add_argument(
        "--output-dir",
        default=str(ROOT / "output" / "junior_high_offline_preview_v1"),
    )
    return parser.parse_args()


def sketch_item(metric: dict[str, Any]) -> dict[str, Any]:
    name = str(metric.get("dimension_name", "")).strip()
    level = str(metric.get("level", "")).strip()
    return {
        "dimension_name": name,
        "source_level": level,
        "level": level,
        "evidence": f"{name}按固定常模划分为{level}",
    }


def section(
    section_id: str,
    title: str,
    body: str,
    evidence_used: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "section_id": section_id,
        "title": title,
        "body": body,
        "evidence_used": evidence_used or [],
        "risk_flags": [],
    }


def metric_names(metrics: list[dict[str, Any]], level: str, limit: int) -> list[str]:
    return [
        str(metric.get("dimension_name", "")).strip()
        for metric in metrics
        if str(metric.get("level", "")).strip() == level
    ][:limit]


def build_report(assessment: dict[str, Any]) -> dict[str, Any]:
    retrieval = RetrievalAgent().run(assessment)
    plan = ReportPlannerAgent().run(assessment, retrieval)
    metrics = plan.get("metric_plans", [])

    strengths = metric_names(metrics, "优势区", 4)
    supports = metric_names(metrics, "潜力区", 4)
    detail_blocks = [
        _compose_controlled_metric_block(metric, "", report_stage="junior_high")
        for metric in metrics
    ]

    strength_text = "、".join(strengths[:3]) or "当前较稳定的能力"
    support_text = "、".join(supports[:2]) or "仍可继续练习的能力"
    core_body = (
        f"这组结果呈现出一条较清楚的发展主线：{strength_text}是你现阶段较容易调动的资源。"
        "三项高分共同指向一种特点：当任务目标较明确、允许把想法转化为行动，"
        "并需要在过程中作出判断时，你更有机会建立自己的处理节奏。\n\n"
        "这些资源的价值不仅在于完成某一道题或某一次任务。面对需要设计方案、协调观点或控制行动节奏的情境，"
        "你更可能先抓住目标，再把想法落实为可以继续推进的步骤。如果能主动说清自己用了什么方法、"
        "为什么有效，并尝试迁移到新的学科或项目中，优势就会逐渐变成可重复使用的学习能力。\n\n"
        f"与此同时，{support_text}是当前更值得继续练习的方向。"
        "面对较开放的问题、较少的信息线索，或者需要在短时间内产生和调整多种想法时，"
        "表现可能更容易受到任务复杂度与时间压力影响。比起要求自己一次做到最好，更重要的是把探索过程拆得清楚，"
        "让每次尝试都留下可以比较的结果。\n\n"
        "已有的行动与组织资源，也为这些支持方向提供了连接点。目标越清楚、任务结构越可见，"
        "你越容易把已有优势带入开放探索和复杂问题中。由优势带动尚不稳定的部分，"
        "会比把每个指标孤立地看待更接近真实的发展过程，也更能呈现你现阶段完整的能力结构。"
    )

    suggestions = [
        {
            "category": "自我成长与学习规划",
            "scene": "需要自己安排作业、复习或阶段目标时",
            "data_basis": "整体执行功能、注意稳定性、学习自信感",
            "action": "把目标拆成“本周目标—今天行动—完成后复盘”三层，每次只调整一个影响效率的环节；周末比较计划与实际完成情况，决定保留或调整下一周的安排。",
            "parent_wording": "需要支持时，可以直接说：“请帮我确认目标是否现实，具体步骤我想先自己安排。”",
            "first_step": "选一项近期任务，连续一周记录计划、实际完成情况和下一次要保留的方法。",
        },
        {
            "category": "兴趣探索与项目实践",
            "scene": "参加社团、项目学习或接触一个新主题时",
            "data_basis": "设计、社会、兴趣好奇心",
            "action": "从一个真实问题或可见作品开始，先提出猜想并做出小版本，再用资料、反馈或实验结果继续修正；完成后比较最初猜想与实际结果，判断是否继续、调整或更换方向。",
            "parent_wording": "需要资源时，可以这样表达：“我想先完成一个小版本，再请你帮我找资料或工具。”",
            "first_step": "本周选一个感兴趣的问题，写下一个想验证的猜测，完成一次可记录结果的小尝试，并根据结果决定下一步。",
        },
        {
            "category": "生涯启发与发展规划",
            "scene": "思考未来选科、社团方向或想进一步了解的领域时",
            "data_basis": "兴趣好奇心、设计、逻辑推理",
            "action": "先把感兴趣的方向写成可验证的假设，例如“我可能喜欢把想法做成作品”，再通过课程、访谈或小项目检验；体验后比较投入感、困难和继续探索意愿。初中阶段暂不急着确定专业或职业。",
            "parent_wording": "需要资源时，可以这样表达：“我想先体验这个方向，请帮我找一次课程、访谈或实践机会。”",
            "first_step": "本周选择一个方向，完成一次不少于三十分钟的真实体验，记录喜欢、困难和仍想追问的部分，再判断是否继续深入。",
        },
    ]

    return {
        "audience": "student",
        "report_type": assessment.get("report_type")
        or "青少年创新潜能与综合素质评估报告",
        "data_sketch": {
            "advantage_dimensions": [
                sketch_item(metric)
                for metric in metrics
                if metric.get("level") == "优势区"
            ],
            "developing_dimensions": [
                sketch_item(metric)
                for metric in metrics
                if metric.get("level") == "潜力区"
            ],
            "middle_dimensions": [
                sketch_item(metric)
                for metric in metrics
                if metric.get("level") == "常态区"
            ],
        },
        "sections": [
            section(
                "preface",
                "写在前面",
                "这份报告帮助你定位当前的发展阶段，认识可以继续运用的资源，也看见值得练习的方向。阅读后，请选出一个小方法，在真实任务中试一试，并用结果判断下一步如何调整。",
                strengths[:2] + supports[:1],
            ),
            section(
                "core_growth_portrait",
                "核心成长画像",
                core_body,
                strengths[:3] + supports[:2],
            ),
            section(
                "detailed_indicator_analysis",
                "详细指标解读",
                "\n\n".join(detail_blocks),
                [str(metric.get("dimension_name", "")) for metric in metrics[:5]],
            ),
            section(
                "growth_support_suggestions",
                "成长支持与生涯规划建议",
                "下面三条建议分别对应自我管理、项目探索和生涯启发。先选择最贴近当前需要的一条，用真实行动验证，再根据结果调整方向。",
                strengths[:2] + supports[:2],
            ),
            section(
                "boundary_note",
                "报告说明",
                "本报告基于本次测评结果，用于帮助你理解当前的学习与发展特点，不能替代医学诊断、心理治疗或个别化咨询。",
            ),
        ],
        # Retain the legacy API key while using student-facing semantics.
        "parent_suggestions": suggestions,
        "self_check": {
            "data_faithful": True,
            "no_diagnosis": True,
            "no_invented_history": True,
            "student_facing": True,
        },
    }


def main() -> None:
    args = parse_args()
    input_path = Path(args.input).resolve()
    output_dir = Path(args.output_dir).resolve()
    text_dir = output_dir / "text_agent"
    sample_dir = output_dir / "samples"
    text_dir.mkdir(parents=True, exist_ok=True)
    sample_dir.mkdir(parents=True, exist_ok=True)

    assessment = load_assessment_result(input_path)
    report = build_report(assessment)
    stem = input_path.stem
    report_path = text_dir / f"{stem}.txt"
    sample_path = sample_dir / input_path.name
    rendered_report = json.dumps(report, ensure_ascii=False, indent=2)
    report_path.write_text(
        "\n".join(
            [
                "=== Final Report ===",
                rendered_report,
                "=== Final Check ===",
                json.dumps(
                    {
                        "pass": True,
                        "status": "offline_preview",
                        "report_stage": "junior_high",
                        "audience": "student",
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
            ]
        ),
        encoding="utf-8",
    )
    sample_path.write_text(
        json.dumps(assessment, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": "ok",
                "report_stage": "junior_high",
                "audience": "student",
                "report_path": str(report_path),
                "sample_path": str(sample_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
