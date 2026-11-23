"""Offline checks for the canonical report pipeline.

This script deliberately makes no DeepSeek calls. It catches missing runtime skills,
RAG/planner coverage drift, and report-contract regressions before a live PDF run.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
from openai import BadRequestError


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from agent_team import (  # noqa: E402
    REPORT_OUTPUT_CONTRACT,
    RUNTIME_REPORT_TEXT_FILES,
    ReportPlannerAgent,
    RetrievalAgent,
    _compose_controlled_metric_block,
    _core_portrait_quality_issues,
    _core_portrait_level_issues,
    _iter_score_items,
    _normalize_core_portrait_labels,
    build_runtime_agent_context,
    chat_text,
    load_assessment_result,
    normalize_assessment_result,
    normalize_report_contract,
    parse_report_json,
    resolve_report_stage,
    run_output_contract_checks,
)


ELEMENTARY_FIXTURE = ROOT_DIR / "templates" / "assessment_input_example_26_metrics.json"
SAMPLE_PATHS = [
    ELEMENTARY_FIXTURE,
    ROOT_DIR / "samples" / "sample_synthetic_junior_high_demo.json",
    *sorted((ROOT_DIR / "samples" / "text_agent_batch").glob("*.json")),
]


def validate_runtime_context() -> list[str]:
    errors: list[str] = []
    for relative_path in RUNTIME_REPORT_TEXT_FILES:
        path = ROOT_DIR / "skills" / relative_path
        if not path.is_file():
            errors.append(f"missing runtime skill: {relative_path}")

    for role in ("generator", "checker", "feedback"):
        context = build_runtime_agent_context(role)
        if "# report_text/references/expert_writing_core.md" not in context:
            errors.append(f"{role} does not load expert_writing_core.md")
        if "# report_text/references/secondary_school_writing_style.md" in context:
            errors.append(f"{role} loads secondary writing rules in the default elementary mode")
    return errors


def validate_school_stage_routing() -> list[str]:
    errors: list[str] = []
    cases = [
        ({}, "elementary"),
        ({"respondent_profile": {"age_group": "小学阶段"}}, "elementary"),
        ({"respondent_profile": {"age_group": "初中阶段"}}, "junior_high"),
        ({"school_stage": "senior_high"}, "senior_high"),
        ({"writing_variant": "中学版"}, "secondary"),
        ({"report_type": "青少年创新潜能与综合素质评估报告"}, "secondary"),
        (
            {
                "report_type": "青少年创新潜能与综合素质评估报告",
                "school_stage": "elementary",
            },
            "elementary",
        ),
    ]
    for payload, expected in cases:
        actual = resolve_report_stage(payload)
        if actual != expected:
            errors.append(f"stage routing expected {expected}, got {actual}: {payload}")

    secondary_input = {
        "report_type": "青少年创新潜能与综合素质评估报告",
        "audience": "parents_and_teachers",
        "respondent_profile": {"age_group": "初中阶段"},
        "scores": {},
    }
    context = build_runtime_agent_context("generator", secondary_input)
    if "# report_text/references/secondary_school_writing_style.md" not in context:
        errors.append("secondary runtime context does not load the secondary writing style")
    if "# report_text/references/secondary_school_support_advice.md" not in context:
        errors.append("secondary runtime context does not load secondary support advice")
    if "# report_text/references/senior_pdf_feedback.md" in context:
        errors.append("secondary runtime context leaks elementary senior feedback rules")
    if "# report_text/references/humanized_parent_style.md" in context:
        errors.append("secondary runtime context leaks elementary parent-facing style")

    retrieved = RetrievalAgent().run(secondary_input)
    summary = retrieved.get("retrieval_summary", {})
    if summary.get("report_stage") != "junior_high":
        errors.append("secondary retrieval trace does not preserve the routed stage")
    if retrieved.get("retrieved_standard_segments"):
        errors.append("untagged elementary standard segments leaked into secondary RAG")
    if retrieved.get("gold_section_references"):
        errors.append("elementary gold section references leaked into secondary RAG")
    return errors


def validate_retrieval_and_planning() -> list[str]:
    errors: list[str] = []
    retrieval_agent = RetrievalAgent()
    planner = ReportPlannerAgent()
    for sample_path in SAMPLE_PATHS:
        if sample_path.name == "manifest.json":
            continue
        assessment = load_assessment_result(sample_path)
        retrieved = retrieval_agent.run(assessment)
        plan = planner.run(assessment, retrieved)
        supplied_count = len(_iter_score_items(assessment))
        if sample_path == ELEMENTARY_FIXTURE and not retrieved.get("retrieved_standard_segments"):
            errors.append("elementary fixture did not retrieve the synthetic writing examples")
        if len(plan.get("metric_plans", [])) != supplied_count:
            errors.append(
                f"{sample_path.name}: planned {len(plan.get('metric_plans', []))} of {supplied_count} metrics"
            )
        if len(retrieved.get("metric_reference_cards", [])) != supplied_count:
            errors.append(
                f"{sample_path.name}: retrieved {len(retrieved.get('metric_reference_cards', []))} of {supplied_count} metric cards"
            )
        if "dimension_detail_templates" in retrieved:
            errors.append(f"{sample_path.name}: raw Excel templates leaked into runtime retrieval")
        for references in retrieved.get("gold_metric_references", {}).values():
            for reference in references:
                if "method_exemplar" in reference:
                    errors.append(f"{sample_path.name}: raw gold prose leaked into runtime retrieval")
        for item in plan.get("metric_plans", []):
            if not item.get("definition"):
                errors.append(f"{sample_path.name}: missing definition for {item.get('dimension_name')}")
            if item.get("definition_source") != "excel_dimension_detail_first_sentence":
                errors.append(
                    f"{sample_path.name}: definition is not sourced from the Excel 维度详解 first sentence for {item.get('dimension_name')}"
                )
            if not item.get("metric_reference_card"):
                errors.append(f"{sample_path.name}: missing reference card for {item.get('dimension_name')}")
        blueprint = plan.get("macro_plan", {}).get("portrait_blueprint", {})
        selected = blueprint.get("selected_evidence", [])
        if not selected:
            errors.append(f"{sample_path.name}: portrait blueprint selected no evidence")
        if len(selected) > 5:
            errors.append(f"{sample_path.name}: portrait blueprint selected more than five metrics")
        selected_domains = {
            cluster.get("domain")
            for cluster in blueprint.get("strength_clusters", [])
            if isinstance(cluster, dict)
        }
        if len(selected_domains) < 2 and len(blueprint.get("strength_clusters", [])) >= 2:
            errors.append(f"{sample_path.name}: portrait strengths were not selected across domains")
    return errors


def validate_contract_normalization() -> list[str]:
    errors: list[str] = []
    report = {
        "data_sketch": {},
        "sections": [],
        "parent_suggestions": [
            {
                "category": "学习与日常",
                "scene": "完成一项需要归纳的任务后",
                "data_basis": "思维聚合性",
                "action": "邀请孩子说出筛选线索的顺序。",
                "parent_wording": "你先说说，哪条线索最重要？",
                "small_first_step": "本周选一道题，先说思路再核对答案。",
            }
        ],
        "self_check": {},
    }
    normalized = normalize_report_contract(json.dumps(report, ensure_ascii=False), {})
    parsed, parse_error = parse_report_json(normalized)
    if parsed is None:
        return [f"normalized contract is invalid JSON: {parse_error}"]
    suggestion = parsed["parent_suggestions"][0]
    if suggestion.get("first_step") != "本周选一道题，先说思路再核对答案。":
        errors.append("legacy small_first_step was not normalized to first_step")
    if "small_first_step" in suggestion:
        errors.append("legacy small_first_step remained in normalized output")

    expected = set(REPORT_OUTPUT_CONTRACT["parent_suggestion"]["required_fields"])
    if expected != set(suggestion):
        errors.append("normalized suggestion fields do not match the canonical schema")
    return errors


def validate_portrait_guard() -> list[str]:
    assessment = load_assessment_result(ELEMENTARY_FIXTURE)
    for item in assessment["scores"].values():
        item.update(level="常态区", percentile_band="middle")
    report = {
        "sections": [
            {
                "section_id": "core_growth_portrait",
                "body": "【潜力】把常态区改写成潜力区。",
            }
        ]
    }
    issues = _core_portrait_level_issues(report, assessment)
    if not issues:
        return ["portrait guard did not reject an invented potential section"]
    normalized = _normalize_core_portrait_labels(
        json.dumps(report, ensure_ascii=False), assessment
    )
    if "【发展基础】" not in normalized or "【潜力】" in normalized:
        return ["portrait normalization did not replace an absent potential heading"]
    fabricated = {
        "sections": [
            {
                "section_id": "core_growth_portrait",
                "body": (
                    "孩子喜欢动手设计，在小组活动中经常主动提出办法，也能够和同学顺利合作。"
                    "另一方面，好奇心仍可继续发展，已有优势可以成为探索的起点。"
                ),
                "evidence_used": ["表演", "文学", "设计", "科学", "社会", "兴趣好奇心"],
            }
        ]
    }
    quality_issues = _core_portrait_quality_issues(fabricated, assessment)
    if not any("真实经历" in issue for issue in quality_issues):
        return ["portrait quality guard did not reject unsupported child history"]
    if not any("超过 5 个指标" in issue for issue in quality_issues):
        return ["portrait quality guard did not reject excessive evidence"]
    return []


def validate_controlled_metric_composition() -> list[str]:
    errors: list[str] = []
    assessment = load_assessment_result(ELEMENTARY_FIXTURE)
    assessment["scores"]["注意稳定性"].update(
        score=100,
        raw_score=100,
        level="优势区",
        percentile_band="advantage",
        rating_basis="extreme_score_override",
    )
    plan = ReportPlannerAgent().run(assessment, RetrievalAgent().run(assessment))
    attention = next(
        item
        for item in plan["metric_plans"]
        if item["dimension_name"] == "注意稳定性"
    )
    body = _compose_controlled_metric_block(
        attention,
        "在连续阅读、书写或多步骤任务中，孩子较容易把注意保持在当前步骤上。面对任务变长或信息增多时，这一能力仍有助于维持投入。",
    )
    for required_text in (
        "【注意稳定性】",
        attention["professional_label"],
        attention["definition"],
        "本项得分满分，按本量表规则列为优势区。",
        "在连续阅读、书写或多步骤任务中",
    ):
        if required_text not in body:
            errors.append(f"controlled metric block missing: {required_text}")

    polluted = _compose_controlled_metric_block(
        attention,
        (
            f"{attention['professional_label']}：{attention['definition']}"
            "当前结果为优势区。在连续阅读或书写时，孩子较容易在分心后重新回到当前步骤。"
        ),
    )
    if polluted.count(attention["definition"]) != 1:
        errors.append("controlled metric composition did not remove a repeated professional definition")
    for definition_sentence in attention["definition"].replace("；", "。").split("。"):
        definition_sentence = definition_sentence.strip()
        if len(definition_sentence) >= 12 and polluted.count(definition_sentence) != 1:
            errors.append(
                "controlled metric composition did not remove a repeated definition sentence"
            )
            break
    if polluted.count("优势区") != 1:
        errors.append("controlled metric composition did not remove a repeated score-level conclusion")

    duplicate_report = {
        "data_sketch": {},
        "sections": [
            {"section_id": "preface", "title": "前言", "body": "供家长参考。"},
            {"section_id": "core_growth_portrait", "title": "核心成长画像", "body": "供家长参考。"},
            {
                "section_id": "detailed_indicator_analysis",
                "title": "详细指标分析",
                "body": (
                    f"【注意稳定性】{attention['definition']}本项得分满分，按本量表规则列为优势区。"
                    f"{attention['definition']}当前结果为优势区。当孩子连续阅读时，可观察他怎样回到任务。"
                ),
            },
            {"section_id": "growth_support_suggestions", "title": "成长支持建议", "body": "供家长参考。"},
            {"section_id": "boundary_note", "title": "报告说明", "body": "不能替代专业诊断或咨询。"},
        ],
        "parent_suggestions": [],
        "self_check": {},
    }
    duplicate_issues = run_output_contract_checks(
        json.dumps(duplicate_report, ensure_ascii=False), assessment
    )
    if not any("重复了专业界定" in issue for issue in duplicate_issues):
        errors.append("output contract did not reject a repeated detailed-definition layer")

    weakening_report = json.loads(json.dumps(duplicate_report, ensure_ascii=False))
    weakening_report["sections"][2]["body"] = (
        f"【注意稳定性】{attention['definition']}本项得分满分，按本量表规则列为优势区。"
        "在连续阅读或书写时，孩子较容易把注意留在当前步骤上。"
        "当任务变复杂或信息增多时，可能需要更多提醒。"
    )
    weakening_issues = run_output_contract_checks(
        json.dumps(weakening_report, ensure_ascii=False), assessment
    )
    if not any("自动附加复杂情境下的退化" in issue for issue in weakening_issues):
        errors.append("output contract did not reject an advantage-band weakening caveat")
    return errors


def validate_fixed_norm_injection() -> list[str]:
    errors: list[str] = []
    assessment = normalize_assessment_result(
        {
            "report_type": "儿童综合素质评估报告",
            "audience": "parents",
            "scale_name": "儿童创新潜能与综合素质评估",
            "scores": {
                "注意稳定性": {"score": 100},
                "规则抽象能力": {"score": 66.6667},
                "逻辑推理": {"score": 26},
                "表演": {"score": 4},
                "瑞文推理": {"dimension_name": "瑞文推理", "score": 20},
                "负性情绪": {"score": 10},
            },
        }
    )
    if assessment.get("scale_config", {}).get("classification_basis") != "fixed_norm_20_80_raw_score":
        errors.append("fixed norm classification_basis was not injected")
    if assessment.get("input_quality", {}).get("fixed_norm_metric_count") != 6:
        errors.append("fixed norm injection did not cover all test metrics")

    expected = {
        "注意稳定性": ("优势区", 80.0, 100.0, "规则维持与注意稳定性"),
        "规则抽象能力": ("常态区", 50.0, 83.3333, "规则抽象与概念形成能力"),
        "逻辑推理": ("优势区", 20.0, 26.0, "逻辑推理"),
        "表演": ("潜力区", 4.0, 8.4, "表演艺术创造性"),
        "瑞文推理": ("潜力区", 20.0, 26.0, "逻辑推理"),
        "负性情绪": ("优势区", 15.0, 40.0, "负性情绪"),
    }
    for metric, (level, p20, p80, norm_name) in expected.items():
        item = assessment["scores"][metric]
        if item.get("level") != level:
            errors.append(f"{metric}: expected {level}, got {item.get('level')}")
        if item.get("norm_p20") != p20 or item.get("norm_p80") != p80:
            errors.append(f"{metric}: wrong norm boundaries")
        if item.get("norm_metric_name") != norm_name:
            errors.append(f"{metric}: wrong norm metric name")
        if item.get("rating_basis") != "fixed_norm_20_80_raw_score":
            errors.append(f"{metric}: wrong rating_basis")
    return errors


def validate_deepseek_json_fallback() -> list[str]:
    """Ensure an optional response_format 400 does not kill the report run."""
    errors: list[str] = []

    class FakeCompletions:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        def create(self, **kwargs):
            self.calls.append(kwargs)
            if len(self.calls) == 1:
                response = httpx.Response(
                    400,
                    request=httpx.Request("POST", "https://api.deepseek.com/chat/completions"),
                    json={"error": {"message": "response_format unsupported"}},
                )
                raise BadRequestError(
                    "response_format unsupported",
                    response=response,
                    body={"error": {"message": "response_format unsupported"}},
                )
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content='{"ok": true}'))]
            )

    completions = FakeCompletions()
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    original_stream = os.environ.get("DEEPSEEK_STREAM")
    try:
        os.environ["DEEPSEEK_STREAM"] = "1"
        result = chat_text(client, [{"role": "user", "content": "return JSON"}], json_output=True)
    finally:
        if original_stream is None:
            os.environ.pop("DEEPSEEK_STREAM", None)
        else:
            os.environ["DEEPSEEK_STREAM"] = original_stream

    if result != '{"ok": true}':
        errors.append("DeepSeek JSON fallback did not return the successful fallback response")
    if len(completions.calls) != 2:
        errors.append("DeepSeek JSON fallback did not issue exactly one retry")
    elif "response_format" not in completions.calls[0] or "response_format" in completions.calls[1]:
        errors.append("DeepSeek JSON fallback did not remove response_format on retry")
    elif completions.calls[1].get("stream") is not False:
        errors.append("DeepSeek JSON fallback did not switch to non-streaming mode")
    return errors


def validate_nonstream_json_retry() -> list[str]:
    """Ensure malformed non-streaming JSON is retried before agent parsing."""
    errors: list[str] = []

    class FakeCompletions:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        def create(self, **kwargs):
            self.calls.append(kwargs)
            content = '{"items": [1 2]}' if len(self.calls) == 1 else '{"items": [1, 2]}'
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
            )

    completions = FakeCompletions()
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    original_env = {
        name: os.environ.get(name)
        for name in (
            "DEEPSEEK_STREAM",
            "DEEPSEEK_MAX_RETRIES",
            "DEEPSEEK_RETRY_BASE_SECONDS",
            "DEEPSEEK_RETRY_MAX_SECONDS",
            "DEEPSEEK_RETRY_JITTER_SECONDS",
        )
    }
    try:
        os.environ["DEEPSEEK_STREAM"] = "0"
        os.environ["DEEPSEEK_MAX_RETRIES"] = "2"
        os.environ["DEEPSEEK_RETRY_BASE_SECONDS"] = "0"
        os.environ["DEEPSEEK_RETRY_MAX_SECONDS"] = "0"
        os.environ["DEEPSEEK_RETRY_JITTER_SECONDS"] = "0"
        result = chat_text(
            client,
            [{"role": "user", "content": "return JSON"}],
            json_output=True,
        )
    finally:
        for name, value in original_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    if result != '{"items": [1, 2]}':
        errors.append("non-stream JSON retry did not return the valid second response")
    if len(completions.calls) != 2:
        errors.append("non-stream JSON retry did not issue exactly one retry")
    return errors


def main() -> None:
    checks = {
        "runtime_context": validate_runtime_context(),
        "school_stage_routing": validate_school_stage_routing(),
        "retrieval_and_planning": validate_retrieval_and_planning(),
        "contract_normalization": validate_contract_normalization(),
        "portrait_guard": validate_portrait_guard(),
        "controlled_metric_composition": validate_controlled_metric_composition(),
        "fixed_norm_injection": validate_fixed_norm_injection(),
        "deepseek_json_fallback": validate_deepseek_json_fallback(),
        "nonstream_json_retry": validate_nonstream_json_retry(),
    }
    errors = [error for items in checks.values() for error in items]
    print(json.dumps({"pass": not errors, "checks": checks}, ensure_ascii=False, indent=2))
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
