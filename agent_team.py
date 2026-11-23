# -*- coding: utf-8 -*-
import json
import os
import random
import re
import sys
import time
from copy import deepcopy
from pathlib import Path
from typing import Any

import httpx
from openai import (
    APIConnectionError,
    APITimeoutError,
    BadRequestError,
    InternalServerError,
    OpenAI,
    RateLimitError,
)

from agent_context import MEMORY_DIR, ROOT_DIR, SKILLS_DIR, build_agent_context, load_text


MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEFAULT_INPUT_PATH = ROOT_DIR / "sample_assessment.json"
RUBRIC_CONFIG_PATH = ROOT_DIR / "config" / "report_rubric.json"
REPORT_OUTPUT_CONTRACT_PATH = ROOT_DIR / "config" / "report_output_schema.json"
METRIC_ALIASES_PATH = ROOT_DIR / "config" / "metric_aliases.json"
SCALE_CATALOG_PATH = ROOT_DIR / "config" / "scale_catalogs" / "students_scores_100.json"
FIXED_NORM_RULE_PATH = ROOT_DIR / "config" / "score_level_rules" / "junior_norm_20_80_raw_score.json"
METRICS_REQUIRING_EXPLICIT_DIRECTION = {
    "负性情绪",
    "抑制控制(Nogo)",
    "抑制控制(go)",
}


COMMON_RUNTIME_REPORT_TEXT_FILES = [
    "report_text/SKILL.md",
    "report_text/references/expert_definition_method.md",
    "report_text/references/final_report_patterns.md",
    "report_text/references/agent_workflow.md",
    "report_text/references/metric_reference_cards.md",
    "report_text/references/expert_writing_core.md",
    "report_text/references/core_portrait_method.md",
    "report_text/references/school_stage_router.md",
    "report_text/references/teacher_annotation_universal_rules.md",
    "safety_boundary.md",
]

ELEMENTARY_RUNTIME_REPORT_TEXT_FILES = [
    "report_text/references/humanized_parent_style.md",
    "report_text/references/section_structure.md",
    "report_text/references/senior_pdf_feedback.md",
]

SECONDARY_RUNTIME_REPORT_TEXT_FILES = [
    "report_text/references/secondary_school_writing_style.md",
    "report_text/references/secondary_school_support_advice.md",
]

# Kept as the complete validation manifest. Runtime loading is stage-selective.
RUNTIME_REPORT_TEXT_FILES = [
    *COMMON_RUNTIME_REPORT_TEXT_FILES,
    *ELEMENTARY_RUNTIME_REPORT_TEXT_FILES,
    *SECONDARY_RUNTIME_REPORT_TEXT_FILES,
]


def resolve_report_stage(assessment_result: dict[str, Any] | None) -> str:
    """Select a writing variant only from explicit stage metadata.

    Elementary remains the safe default. Score patterns, age inference, and RAG
    examples are deliberately excluded from this decision.
    """
    if not isinstance(assessment_result, dict):
        return "elementary"

    profile = assessment_result.get("respondent_profile", {})
    profile = profile if isinstance(profile, dict) else {}
    explicit_stage_fields = (
        "report_stage",
        "school_stage",
        "education_stage",
        "age_group",
        "report_variant",
        "writing_variant",
    )
    explicit_values = [assessment_result.get(field) for field in explicit_stage_fields]
    explicit_values.extend(profile.get(field) for field in explicit_stage_fields)
    normalized = " ".join(
        str(value or "").strip().lower() for value in explicit_values
    )

    if any(term in normalized for term in ("senior_high", "high_school", "高中")):
        return "senior_high"
    if any(term in normalized for term in ("junior_high", "初中")):
        return "junior_high"
    if any(
        term in normalized
        for term in ("middle_school", "secondary", "中学", "青少年")
    ):
        return "secondary"
    if any(term in normalized for term in ("elementary", "primary_school", "小学")):
        return "elementary"

    # A report title is a weaker but still explicit fallback. Dedicated stage
    # fields above always win, which lets the local UI override legacy titles.
    report_type = str(assessment_result.get("report_type") or "").strip().lower()
    if any(term in report_type for term in ("高中", "senior_high", "high_school")):
        return "senior_high"
    if any(term in report_type for term in ("初中", "junior_high")):
        return "junior_high"
    if any(term in report_type for term in ("青少年", "中学", "middle_school", "secondary")):
        return "secondary"
    return "elementary"


SECONDARY_REPORT_STAGES = {"secondary", "junior_high", "senior_high"}


def report_reader_mode(assessment_result: dict[str, Any] | None) -> str:
    """Keep the visible reader deterministic and aligned with the stage route."""
    return (
        "student"
        if resolve_report_stage(assessment_result) in SECONDARY_REPORT_STAGES
        else "parents"
    )


def build_runtime_agent_context(
    role: str,
    assessment_result: dict[str, Any] | None = None,
) -> str:
    """Load a small, high-signal subset of the folder skill for API requests.

    The full folder remains available locally for maintenance and RAG preparation.
    Runtime generation receives the core rules plus retrieved cases, preventing a
    large prompt from making long report requests fragile.
    """
    report_stage = resolve_report_stage(assessment_result)
    files = list(COMMON_RUNTIME_REPORT_TEXT_FILES)
    if report_stage == "elementary":
        files.extend(ELEMENTARY_RUNTIME_REPORT_TEXT_FILES)
    else:
        files.extend(SECONDARY_RUNTIME_REPORT_TEXT_FILES)
    if role in {"checker", "feedback"}:
        files.append("report_checker.md")
    if role == "feedback":
        files.append("report_rewriter.md")

    sections = []
    for relative_path in files:
        path = SKILLS_DIR / relative_path
        sections.append(f"# {relative_path}\n{load_text(path)}")

    memory_names = ["report_rubric", "style_guide", "scale_knowledge"]
    memory = "\n\n".join(
        f"# memory/{name}.md\n{load_text(MEMORY_DIR / f'{name}.md')}"
        for name in memory_names
    )
    reader_mode = report_reader_mode(assessment_result)
    stage_override = (
        "可见正文直接写给学生本人，使用“你”。共同层资料中的“家长可读/家长翻译”"
        "只表示要通俗易懂，不得据此改回家长信口吻。"
        if reader_mode == "student"
        else
        "可见正文主要写给家长，以“孩子”描述被试并提供家长可执行的支持方式。"
    )
    return (
        f"本次确定性学段路由结果：{report_stage}；可见读者：{reader_mode}。"
        f"不得由检索案例改写。{stage_override}\n\n"
        "以下是本次运行必须遵守的精炼技能上下文。完整案例仅通过 "
        "RetrievalAgent 的检索结果提供。\n\n<skills>\n"
        + "\n\n".join(sections)
        + "\n</skills>\n\n<memory>\n"
        + memory
        + "\n</memory>"
    )


def require_api_key() -> str:
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise RuntimeError(
            "没有找到 DEEPSEEK_API_KEY。请先在 PowerShell 中运行："
            '$env:DEEPSEEK_API_KEY="你的新APIKey"'
        )
    return api_key


def create_client() -> OpenAI:
    timeout_seconds = max(10.0, float(os.environ.get("DEEPSEEK_TIMEOUT_SECONDS", "180")))
    connect_timeout_seconds = max(
        5.0,
        float(os.environ.get("DEEPSEEK_CONNECT_TIMEOUT_SECONDS", "30")),
    )
    # The desktop environment may set HTTP(S)_PROXY for unrelated software.
    # DeepSeek calls have repeatedly failed during that proxy's TLS handshake,
    # so direct HTTPS is the default. Set DEEPSEEK_TRUST_ENV=1 only when a
    # working corporate proxy is explicitly required.
    trust_environment_proxy = os.environ.get("DEEPSEEK_TRUST_ENV", "0").strip().lower() in {
        "1",
        "true",
        "yes",
    }
    timeout = httpx.Timeout(timeout_seconds, connect=connect_timeout_seconds)
    return OpenAI(
        api_key=require_api_key(),
        base_url=BASE_URL,
        timeout=timeout,
        http_client=httpx.Client(timeout=timeout, trust_env=trust_environment_proxy),
        # Retries are controlled below so logs and backoff remain predictable.
        max_retries=0,
    )


def load_assessment_result(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"找不到测评 JSON 文件：{path}")

    with path.open("r", encoding="utf-8") as file:
        return normalize_assessment_result(json.load(file))


def load_scale_catalog(path: Path = SCALE_CATALOG_PATH) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as file:
        value = json.load(file)
    return value if isinstance(value, dict) else {}


def load_fixed_norm_rules(path: Path = FIXED_NORM_RULE_PATH) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as file:
        value = json.load(file)
    return value if isinstance(value, dict) else {}


def _fixed_norm_lookup(norm_rules: dict[str, Any]) -> dict[str, tuple[str, dict[str, Any]]]:
    lookup: dict[str, tuple[str, dict[str, Any]]] = {}
    norms = norm_rules.get("norms", {})
    if not isinstance(norms, dict):
        return lookup

    for norm_name, norm_item in norms.items():
        if isinstance(norm_item, dict):
            lookup[_normalize_dimension_name(norm_name)] = (str(norm_name), norm_item)

    aliases = norm_rules.get("aliases", {})
    if isinstance(aliases, dict):
        for metric_name, norm_name in aliases.items():
            norm_item = norms.get(str(norm_name))
            if isinstance(norm_item, dict):
                lookup[_normalize_dimension_name(metric_name)] = (str(norm_name), norm_item)
    return lookup


def _score_number(item: dict[str, Any]) -> float | None:
    for field in ("raw_score", "score"):
        value = item.get(field)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
        if isinstance(value, str):
            stripped = value.strip()
            if stripped:
                try:
                    return float(stripped)
                except ValueError:
                    pass
    return None


def _fixed_norm_level(
    raw_score: float,
    p20: float,
    p80: float,
    direction: str = "higher_is_better",
) -> tuple[str, str]:
    if raw_score <= p20:
        if direction == "lower_is_better":
            return "优势区", "norm_favorable_bottom_20"
        return "潜力区", "norm_bottom_20"
    if raw_score >= p80:
        if direction == "lower_is_better":
            return "潜力区", "norm_unfavorable_top_20"
        return "优势区", "norm_top_20"
    return "常态区", "norm_middle_60"


def apply_fixed_norm_to_score_item(
    item: dict[str, Any],
    norm_lookup: dict[str, tuple[str, dict[str, Any]]],
) -> bool:
    """Attach fixed norm P20/P80 level metadata to one raw-score metric."""
    dimension_name = str(item.get("dimension_name", "")).strip()
    if not dimension_name:
        return False
    if str(item.get("rating_basis", "")).strip() == "expert_report_gold_reference":
        return False

    matched = norm_lookup.get(_normalize_dimension_name(dimension_name))
    if not matched:
        return False
    norm_name, norm_item = matched
    if "p20" not in norm_item or "p80" not in norm_item:
        return False

    raw_score = _score_number(item)
    if raw_score is None:
        return False
    p20 = float(norm_item["p20"])
    p80 = float(norm_item["p80"])
    direction = (
        str(item.get("direction", "")).strip()
        or str(norm_item.get("direction", "")).strip()
        or "higher_is_better"
    )
    item.setdefault("direction", direction)
    level, percentile_band = _fixed_norm_level(raw_score, p20, p80, direction)

    item["raw_score"] = raw_score
    item["score"] = raw_score
    item["level"] = level
    item["percentile_band"] = percentile_band
    item["rating_basis"] = "fixed_norm_20_80_raw_score"
    item["norm_metric_name"] = norm_name
    item["norm_p20"] = p20
    item["norm_p80"] = p80
    item["norm_sample_size"] = norm_item.get("sample_size")
    item["raw_score_range"] = norm_item.get("raw_range")
    item["plot_range"] = norm_item.get("plot_range") or norm_item.get("raw_range")
    item.setdefault("interpretation", f"按固定常模 P20/P80 分界值，本指标原始分位于{level}。")
    return True


def normalize_assessment_result(assessment_result: dict[str, Any]) -> dict[str, Any]:
    """Attach catalog metadata without inventing score meanings or directions."""
    prepared = deepcopy(assessment_result)
    catalog = load_scale_catalog()
    norm_rules = load_fixed_norm_rules()
    norm_lookup = _fixed_norm_lookup(norm_rules)
    catalog_id = str(catalog.get("catalog_id", "")).strip()

    metric_catalog: dict[str, dict[str, str]] = {}
    for domain in catalog.get("domains", []):
        if not isinstance(domain, dict):
            continue
        domain_name = str(domain.get("name", "")).strip()
        submodule = str(domain.get("submodule", "")).strip()
        for metric in domain.get("metrics", []):
            metric_name = str(metric).strip()
            if metric_name:
                metric_catalog[_normalize_dimension_name(metric_name)] = {
                    "domain": domain_name,
                    "submodule": submodule,
                }

    scores = prepared.get("scores")
    flags: list[str] = []
    provided_metrics: list[str] = []
    normalized_with_fixed_norm = 0

    scale_config = prepared.get("scale_config")
    if not isinstance(scale_config, dict):
        scale_config = {}
    requested_basis = str(scale_config.get("classification_basis", "")).strip()
    should_apply_fixed_norm = requested_basis in {"", "fixed_norm_20_80_raw_score"}

    if isinstance(scores, dict):
        for key, raw_value in list(scores.items()):
            item = dict(raw_value) if isinstance(raw_value, dict) else {"score": raw_value}
            dimension_name = str(item.get("dimension_name") or key).strip()
            item["dimension_name"] = dimension_name
            metadata = metric_catalog.get(_normalize_dimension_name(dimension_name))
            if metadata:
                item.setdefault("domain", metadata["domain"])
                item.setdefault("submodule", metadata["submodule"])

            if dimension_name:
                provided_metrics.append(dimension_name)
            if should_apply_fixed_norm and apply_fixed_norm_to_score_item(item, norm_lookup):
                normalized_with_fixed_norm += 1
            if not any(str(item.get(field, "")).strip() for field in ("level", "percentile_band", "interpretation")):
                flags.append(f"{dimension_name}：缺少层级或解释规则")
            if (
                dimension_name in METRICS_REQUIRING_EXPLICIT_DIRECTION
                and not str(item.get("direction", "")).strip()
                and not str(item.get("interpretation", "")).strip()
            ):
                flags.append(f"{dimension_name}：缺少方向或解释规则")
            scores[key] = item

    if catalog_id:
        scale_config.setdefault("catalog_id", catalog_id)
    if should_apply_fixed_norm and normalized_with_fixed_norm:
        scale_config["classification_basis"] = "fixed_norm_20_80_raw_score"
        scale_config["classification_rule_id"] = norm_rules.get(
            "rule_id",
            "junior_norm_20_80_raw_score_v1",
        )
        scale_config["reference_group"] = norm_rules.get("source", {}).get(
            "reference_group",
            "初中生全国常模",
        )
        scale_config["level_rules"] = norm_rules.get("level_rules", [])
        scale_config["chart_rule"] = norm_rules.get("chart_rule", {})
        scale_config.setdefault("score_reference_lines", [])
    prepared["scale_config"] = scale_config
    prepared["input_quality"] = {
        "catalog_id": catalog_id,
        "provided_metric_count": len(provided_metrics),
        "provided_metrics": provided_metrics,
        "fixed_norm_rule_id": norm_rules.get("rule_id", ""),
        "fixed_norm_metric_count": normalized_with_fixed_norm,
        "flags": flags,
    }
    return prepared


def load_report_rubric(path: Path = RUBRIC_CONFIG_PATH) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"找不到评分配置文件：{path}")

    with path.open("r", encoding="utf-8") as file:
        rubric = json.load(file)

    total_weight = sum(int(item["max_score"]) for item in rubric["dimensions"])
    if total_weight != 100:
        raise ValueError(f"评分维度总分必须为 100，目前为：{total_weight}")

    return rubric


def get_pass_score(rubric: dict[str, Any]) -> int:
    return int(os.environ.get("REPORT_PASS_SCORE", rubric.get("pass_score", 80)))


def build_score_schema(rubric: dict[str, Any]) -> dict[str, int]:
    return {dimension["key"]: 0 for dimension in rubric["dimensions"]}


def format_rubric_for_prompt(rubric: dict[str, Any]) -> str:
    dimension_lines = []
    for dimension in rubric["dimensions"]:
        dimension_lines.append(
            "\n".join(
                [
                    f"- {dimension['key']}（{dimension['label']}，满分 {dimension['max_score']}）：",
                    f"  优秀标准：{dimension['excellent']}",
                    f"  扣分点：{dimension['deduct']}",
                ]
            )
        )

    hard_failures = "\n".join(
        f"- {item}" for item in rubric.get("hard_failures", [])
    )
    calibration = rubric.get("calibration", {})

    return f"""
评分配置：
- 名称：{rubric.get("name")}
- 版本：{rubric.get("version")}
- 通过阈值：{get_pass_score(rubric)}
- 人工审核建议阈值：低于 {rubric.get("human_review_score_below", 70)}

评分维度：
{chr(10).join(dimension_lines)}

硬性不合格项：
{hard_failures}

评分校准上限：
- 未经过人工审核或黄金样例对照时，最高 {calibration.get("no_gold_reference_max_score", 94)}
- 存在 minor_issues 时，最高 {calibration.get("minor_issue_max_score", 92)}
- 存在 major_issues 时，最高 {calibration.get("major_issue_max_score", 79)}
- 存在 hard_failures 时，最高 {calibration.get("hard_failure_max_score", 69)}
""".strip()


def parse_json_object(text: str) -> dict[str, Any]:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(0))


def strip_markdown_code_fence(text: str) -> str:
    stripped = text.strip()
    match = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", stripped, re.DOTALL)
    if match:
        return match.group(1).strip()
    return stripped


def normalize_cjk_spacing(text: str) -> str:
    return re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", text)


def extract_report_check_text(report: str) -> str:
    """Return only user-visible report prose for deterministic rule checks."""
    stripped = normalize_cjk_spacing(strip_markdown_code_fence(report))
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        return stripped

    if not isinstance(parsed, dict):
        return stripped

    chunks: list[str] = []
    for section in parsed.get("sections", []):
        if not isinstance(section, dict):
            continue
        title = str(section.get("title", "")).strip()
        body = str(section.get("body", "")).strip()
        if title:
            chunks.append(title)
        if body:
            chunks.append(body)

    for suggestion in parsed.get("parent_suggestions", []):
        if not isinstance(suggestion, dict):
            continue
        for key in ("category", "scene", "data_basis", "action", "parent_wording", "first_step"):
            value = str(suggestion.get(key, "")).strip()
            if value:
                chunks.append(value)

    return normalize_cjk_spacing("\n".join(chunks).strip() or stripped)


def load_report_output_contract(
    path: Path = REPORT_OUTPUT_CONTRACT_PATH,
) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"找不到报告输出合同：{path}")
    with path.open("r", encoding="utf-8") as file:
        contract = json.load(file)
    if not isinstance(contract, dict):
        raise ValueError("报告输出合同必须是 JSON object")
    return contract


def load_metric_aliases(path: Path = METRIC_ALIASES_PATH) -> dict[str, str]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    aliases = payload.get("aliases", {}) if isinstance(payload, dict) else {}
    return {
        re.sub(r"[\s【】()（）_-]", "", str(alias)).lower(): str(canonical)
        for alias, canonical in aliases.items()
        if str(alias).strip() and str(canonical).strip()
    }


REPORT_OUTPUT_CONTRACT = load_report_output_contract()
METRIC_ALIASES = load_metric_aliases()
REQUIRED_REPORT_TOP_LEVEL_KEYS = list(
    REPORT_OUTPUT_CONTRACT["required_top_level_keys"]
)
REQUIRED_SECTION_IDS = list(REPORT_OUTPUT_CONTRACT["required_section_ids"])

ALLOWED_SECTION_IDS = set(REQUIRED_SECTION_IDS)

PARENT_SUGGESTION_CONTRACT = REPORT_OUTPUT_CONTRACT["parent_suggestion"]
REQUIRED_PARENT_SUGGESTION_KEYS = list(
    PARENT_SUGGESTION_CONTRACT["required_fields"]
)
SUGGESTION_CATEGORIES = set(PARENT_SUGGESTION_CONTRACT["allowed_categories"])
SUGGESTION_CATEGORY_ORDER_BY_STAGE = {
    str(stage): list(categories)
    for stage, categories in PARENT_SUGGESTION_CONTRACT.get(
        "allowed_categories_by_stage", {}
    ).items()
}
SUGGESTION_CATEGORIES_BY_STAGE = {
    stage: set(categories)
    for stage, categories in SUGGESTION_CATEGORY_ORDER_BY_STAGE.items()
}
PARENT_SUGGESTION_ALIASES = dict(
    PARENT_SUGGESTION_CONTRACT.get("legacy_aliases", {})
)


def suggestion_categories_for_stage(
    assessment_result: dict[str, Any] | None,
) -> set[str]:
    """Return the visible advice categories for the deterministic stage."""
    stage = resolve_report_stage(assessment_result)
    if stage in SUGGESTION_CATEGORIES_BY_STAGE:
        return set(SUGGESTION_CATEGORIES_BY_STAGE[stage])
    if stage in SECONDARY_REPORT_STAGES:
        return set(SUGGESTION_CATEGORIES_BY_STAGE.get("secondary", set()))
    return set(
        SUGGESTION_CATEGORIES_BY_STAGE.get(
            "elementary",
            {"学习与日常", "课外与探索", "亲子互动与沟通"},
        )
    )


def suggestion_category_order_for_stage(
    assessment_result: dict[str, Any] | None,
) -> list[str]:
    """Return advice categories in their visible report order."""
    stage = resolve_report_stage(assessment_result)
    if stage in SUGGESTION_CATEGORY_ORDER_BY_STAGE:
        return list(SUGGESTION_CATEGORY_ORDER_BY_STAGE[stage])
    if stage in SECONDARY_REPORT_STAGES:
        return list(SUGGESTION_CATEGORY_ORDER_BY_STAGE.get("secondary", []))
    return list(
        SUGGESTION_CATEGORY_ORDER_BY_STAGE.get(
            "elementary",
            ["学习与日常", "课外与探索", "亲子互动与沟通"],
        )
    )


UNSUPPORTED_EXPERIENCE_PATTERNS = {
    r"(上次|上周|昨天|前几天|之前|还记得).{0,24}(班里|同学|老师|考试|数学题|作业|模型|乐高|养了|比赛|提到)": "疑似把未提供的过去经历写成真实事件",
    r"(你|孩子).{0,8}(提到|说过|经历过|遇到过|做过|养过).{0,24}(班里|同学|老师|考试|作业|模型|乐高|蚕|比赛)": "疑似编造孩子既往经历",
    r"(老师|同学|班里).{0,16}(表扬|批评|说|养了|发生|要求|排斥|欺负)": "疑似编造学校、老师或同伴事件",
    r"最引以为豪": "疑似推断孩子主观感受，输入未必支持",
    r"孩子在.{0,20}(拼乐高|做手工|写日记|讲故事).{0,24}(喜欢|常常|总能|会主动)": "疑似把示例活动写成孩子已发生的真实行为",
    r"孩子(喜欢上学|.*与同学老师相处融洽)": "疑似把学校体验写成已知事实",
    r"孩子(?!是否).{0,8}(乐于|喜欢|擅长|总是|通常会|已经会).{0,28}(角色扮演|分享|表达|班级|同学|老师|团队互动)": "疑似把分数推断写成孩子已发生的具体行为",
    r"在(团队|班级|学校).{0,24}(表现出|展现出|能够|能).{0,24}(同理心|组织意识|人际|表达|互动)": "疑似把测评倾向写成未经提供的学校或同伴事实",
    r"(更愿意|愿意).{0,18}(在班级中|与老师|与同学).{0,24}(表达|分享|互动|参与)": "疑似把测评倾向写成未经提供的关系或活动事实",
}


def parse_report_json(report: str) -> tuple[dict[str, Any] | None, str]:
    stripped = normalize_cjk_spacing(strip_markdown_code_fence(report))
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError as exc:
        return None, f"{exc.msg}，line {exc.lineno} column {exc.colno}"

    if not isinstance(parsed, dict):
        return None, "TextAgent 输出的 JSON 顶层不是 object"

    return parsed, ""


def normalize_report_contract(
    report: str,
    assessment_result: dict[str, Any],
) -> str:
    """Fill deterministic API metadata that the model occasionally omits."""
    parsed, _ = parse_report_json(report)
    if parsed is None:
        return report

    # The stage route, not a stale input field or retrieved example, controls
    # the visible reader. Keep the legacy schema key deterministic.
    parsed["audience"] = report_reader_mode(assessment_result)
    parsed.setdefault(
        "report_type",
        assessment_result.get("report_type") or "儿童综合素质评估报告",
    )
    if resolve_report_stage(assessment_result) in SECONDARY_REPORT_STAGES:
        def student_voice(value: Any) -> Any:
            if not isinstance(value, str):
                return value
            normalized = re.sub(r"儿童|孩子|学生本人", "你", value)
            normalized = re.sub(
                r"^(?:尊敬的)?家长(?:您好|，您好)[：:，,]?\s*",
                "",
                normalized,
            )
            return normalized

        sections = parsed.get("sections")
        if isinstance(sections, list):
            for section in sections:
                if not isinstance(section, dict):
                    continue
                section["title"] = student_voice(section.get("title", ""))
                section["body"] = student_voice(section.get("body", ""))

    suggestions = parsed.get("parent_suggestions")
    if isinstance(suggestions, list):
        for suggestion in suggestions:
            if not isinstance(suggestion, dict):
                continue
            for legacy_key, canonical_key in PARENT_SUGGESTION_ALIASES.items():
                if (
                    not str(suggestion.get(canonical_key, "")).strip()
                    and str(suggestion.get(legacy_key, "")).strip()
                ):
                    suggestion[canonical_key] = suggestion[legacy_key]
                suggestion.pop(legacy_key, None)
            if resolve_report_stage(assessment_result) in SECONDARY_REPORT_STAGES:
                for key in (
                    "category",
                    "scene",
                    "data_basis",
                    "action",
                    "parent_wording",
                    "first_step",
                ):
                    suggestion[key] = student_voice(suggestion.get(key, ""))
    return json.dumps(parsed, ensure_ascii=False, indent=2)


def run_output_contract_checks(
    report: str,
    assessment_result: dict[str, Any],
) -> list[str]:
    """Check API/PDF readiness and unsupported specific experiences."""
    issues = []
    parsed, parse_error = parse_report_json(report)
    if parsed is None:
        return [f"[major] TextAgent 输出不是合法 JSON，无法稳定接入 renderer/API：{parse_error}"]

    missing_keys = [
        key for key in REQUIRED_REPORT_TOP_LEVEL_KEYS if key not in parsed
    ]
    if missing_keys:
        issues.append(f"[major] TextAgent 输出缺少顶层字段：{', '.join(missing_keys)}")

    sections = parsed.get("sections")
    if not isinstance(sections, list):
        issues.append("[major] TextAgent 输出的 sections 不是数组")
        sections = []

    section_ids = []
    for index, section in enumerate(sections):
        if not isinstance(section, dict):
            issues.append(f"[major] sections[{index}] 不是对象")
            continue
        section_id = str(section.get("section_id", "")).strip()
        if section_id:
            section_ids.append(section_id)
        else:
            issues.append(f"[major] sections[{index}] 缺少 section_id")
        if not str(section.get("title", "")).strip():
            issues.append(f"[minor] sections[{index}] 缺少 title")
        if not str(section.get("body", "")).strip():
            issues.append(f"[major] sections[{index}] 缺少 body")

    missing_section_ids = [
        section_id for section_id in REQUIRED_SECTION_IDS if section_id not in section_ids
    ]
    if missing_section_ids:
        issues.append(
            "[major] TextAgent 输出缺少固定 section_id："
            + ", ".join(missing_section_ids)
        )

    unexpected_section_ids = [
        section_id for section_id in section_ids if section_id not in ALLOWED_SECTION_IDS
    ]
    if unexpected_section_ids:
        issues.append(
            "[major] TextAgent 输出包含 renderer/API 未约定的 section_id："
            + ", ".join(unexpected_section_ids)
        )

    duplicate_section_ids = [
        section_id
        for section_id in sorted(set(section_ids))
        if section_ids.count(section_id) > 1
    ]
    if duplicate_section_ids:
        issues.append(
            "[major] TextAgent 输出存在重复 section_id："
            + ", ".join(duplicate_section_ids)
        )

    suggestions = parsed.get("parent_suggestions")
    expected_suggestion_categories = suggestion_categories_for_stage(
        assessment_result
    )
    if not isinstance(suggestions, list):
        issues.append("[major] parent_suggestions 不是数组")
        suggestions = []
    elif len(suggestions) != 3:
        reader = "学生行动" if report_reader_mode(assessment_result) == "student" else "家长行动"
        issues.append(
            f"[major] parent_suggestions 必须恰好为 3 条，当前为 {len(suggestions)} 条，"
            f"无法形成完整的{reader}建议页"
        )

    for index, suggestion in enumerate(suggestions):
        if not isinstance(suggestion, dict):
            issues.append(f"[major] parent_suggestions[{index}] 不是对象")
            continue
        missing_suggestion_keys = [
            key for key in REQUIRED_PARENT_SUGGESTION_KEYS if not str(suggestion.get(key, "")).strip()
        ]
        if missing_suggestion_keys:
            issues.append(
                f"[major] parent_suggestions[{index}] 缺少字段："
                + ", ".join(missing_suggestion_keys)
            )
            continue
        category = str(suggestion.get("category", "")).strip()
        if category not in expected_suggestion_categories:
            issues.append(
                f"[major] parent_suggestions[{index}].category 必须是："
                + "、".join(sorted(expected_suggestion_categories))
            )

    if len(suggestions) >= 3:
        present_categories = {
            str(item.get("category", "")).strip()
            for item in suggestions
            if isinstance(item, dict)
        }
        missing_categories = expected_suggestion_categories - present_categories
        support_risk_flags = []
        for section in sections:
            if not isinstance(section, dict):
                continue
            if section.get("section_id") != "growth_support_suggestions":
                continue
            risk_flags = section.get("risk_flags", [])
            if isinstance(risk_flags, list):
                support_risk_flags.extend(str(flag) for flag in risk_flags)
        risk_text = "\n".join(support_risk_flags)
        unexplained_categories = {
            category for category in missing_categories if category not in risk_text
        }
        if unexplained_categories:
            issues.append(
                "[major] 成长建议未覆盖全部教育场景："
                + "、".join(sorted(unexplained_categories))
                + "。若该场景确实不适用，请在 growth_support_suggestions.risk_flags 中说明数据依据。"
            )

    issues.extend(_data_sketch_level_issues(parsed, assessment_result))
    issues.extend(_core_portrait_level_issues(parsed, assessment_result))
    issues.extend(_core_portrait_quality_issues(parsed, assessment_result))
    issues.extend(_detailed_indicator_coverage_issues(parsed, assessment_result))
    issues.extend(_detailed_indicator_duplicate_analysis_issues(parsed))
    issues.extend(_detailed_indicator_role_issues(parsed, assessment_result))
    issues.extend(_mechanical_style_contract_issues(parsed))
    issues.extend(_suggestion_actionability_issues(parsed, assessment_result))
    issues.extend(_unsupported_specific_experience_issues(parsed, assessment_result))
    return issues


def _mechanical_style_contract_issues(
    report_json: dict[str, Any],
) -> list[str]:
    """Locate teacher-rejected template language so FeedbackAgent can patch it."""
    patterns = (
        (re.compile(r"不是[^。！？\n]{0,36}而是"), "“不是……而是……”"),
        (re.compile(r"这(?:提示|说明)"), "“这提示/这说明”"),
        (re.compile(r"按输入的量表解释"), "内部管线措辞“按输入的量表解释”"),
        (re.compile(r"一个可操作的起点是"), "模板句“一个可操作的起点是”"),
    )
    issues: list[str] = []
    for index, section in enumerate(report_json.get("sections", [])):
        if not isinstance(section, dict):
            continue
        section_id = str(section.get("section_id", "")).strip() or f"sections[{index}]"
        body = str(section.get("body", ""))
        hits = [label for pattern, label in patterns if pattern.search(body)]
        if hits:
            issues.append(
                f"[major] sections[{section_id}].body 使用机械句式："
                + "、".join(hits)
                + "；请直接陈述任务表现、发展含义或下一步动作。"
            )
    for index, suggestion in enumerate(report_json.get("parent_suggestions", [])):
        if not isinstance(suggestion, dict):
            continue
        text = "\n".join(
            str(suggestion.get(key, ""))
            for key in ("scene", "action", "parent_wording", "first_step")
        )
        hits = [label for pattern, label in patterns if pattern.search(text)]
        if hits:
            issues.append(
                f"[major] parent_suggestions[{index}] 使用机械句式："
                + "、".join(hits)
                + "；请改成具体场景、动作和可观察结果。"
            )
    return issues


def _suggestion_actionability_issues(
    report_json: dict[str, Any],
    assessment_result: dict[str, Any],
) -> list[str]:
    """Reject advice that names a direction but leaves no executable first move."""
    suggestions = report_json.get("parent_suggestions", [])
    if not isinstance(suggestions, list):
        return []

    action_verbs = (
        "写下",
        "列出",
        "圈出",
        "标记",
        "拆分",
        "比较",
        "选择",
        "完成",
        "制作",
        "记录",
        "查找",
        "阅读",
        "询问",
        "访谈",
        "体验",
        "验证",
        "复盘",
        "整理",
        "复述",
        "画出",
        "提出",
        "筛选",
        "保留",
    )
    observable_pattern = re.compile(
        r"(?:\d+|一|两|二|三|四|五|每|本周|今天|分钟|小时|天|周|次|条|项|"
        r"个|份|页|阶段|步骤|清单|表格|卡片|草图|方案|问题|资料|作品|记录|结果)"
    )
    review_cues = (
        "完成后",
        "结束后",
        "一周后",
        "周末",
        "复盘",
        "完成后比较",
        "周末比较",
        "体验后比较",
        "检查",
        "查看",
        "根据结果",
        "根据记录",
        "根据反馈",
        "保留",
        "调整",
        "修正",
        "更换",
        "再决定",
        "判断是否",
    )
    issues: list[str] = []
    reader = "学生" if report_reader_mode(assessment_result) == "student" else "家长"
    require_review_rule = resolve_report_stage(assessment_result) in SECONDARY_REPORT_STAGES
    for index, suggestion in enumerate(suggestions):
        if not isinstance(suggestion, dict):
            continue
        action = str(suggestion.get("action", "")).strip()
        first_step = str(suggestion.get("first_step", "")).strip()
        combined = f"{action}\n{first_step}"
        if not any(verb in combined for verb in action_verbs):
            issues.append(
                f"[major] parent_suggestions[{index}] 仍是概念性建议，"
                f"缺少{reader}可以立即执行的具体动作；请改为“场景 + 动词 + 工具/步骤”。"
            )
        if not any(verb in first_step for verb in action_verbs):
            issues.append(
                f"[major] parent_suggestions[{index}].first_step 没有明确的第一步动作；"
                "请写清今天或本周具体要做什么。"
            )
        if not observable_pattern.search(combined):
            issues.append(
                f"[major] parent_suggestions[{index}] 缺少可观察的完成结果或复核信号；"
                "请补充数量、时间、清单、作品、记录或一次复盘。"
            )
        if require_review_rule and not any(cue in combined for cue in review_cues):
            issues.append(
                f"[major] parent_suggestions[{index}] 缺少完成后的复核规则；"
                "请写清根据什么结果决定保留、调整或更换当前方法。"
            )
    return issues


def _core_portrait_level_issues(
    report_json: dict[str, Any],
    assessment_result: dict[str, Any],
) -> list[str]:
    """Prevent the portrait from inventing a potential area absent from the input."""
    has_potential_dimension = any(
        _classify_score_band(item) == "potential"
        for item in _iter_score_items(assessment_result)
    )
    if has_potential_dimension:
        return []
    portrait = _section_body(report_json, "core_growth_portrait")
    if "【潜力】" in portrait or "潜力区" in portrait:
        return [
            "[major] 输入没有潜力区指标，但核心成长画像写入了“潜力”结论；"
            "常态区只能用于说明平衡或发展基础，不能改写为潜力区。"
        ]
    return []


def _core_portrait_quality_issues(
    report_json: dict[str, Any],
    assessment_result: dict[str, Any],
) -> list[str]:
    """Catch score-list portraits and unsupported child-history assertions."""
    portrait_section = next(
        (
            item
            for item in report_json.get("sections", [])
            if isinstance(item, dict)
            and item.get("section_id") == "core_growth_portrait"
        ),
        {},
    )
    body = str(portrait_section.get("body", "")).strip()
    issues: list[str] = []
    student_facing = resolve_report_stage(assessment_result) in SECONDARY_REPORT_STAGES
    evidence = portrait_section.get("evidence_used", [])
    if isinstance(evidence, list) and len(evidence) > 5:
        issues.append(
            "[major] 核心成长画像使用了超过 5 个指标，已变成分数罗列；"
            "请只保留能组成一条画像主线的 3-5 个代表性证据。"
        )
    minimum_length = 320 if student_facing else 220
    maximum_length = 560 if student_facing else 520
    if body and len(body) < minimum_length:
        stage_hint = "中学版建议写成 360-500 字的四段画像；" if student_facing else ""
        issues.append(
            "[minor] 核心成长画像过短，"
            + stage_hint
            + "尚未形成‘画像主线—优势机制—发展价值—支持桥梁’的完整论证。"
        )
    if len(body) > maximum_length:
        issues.append("[minor] 核心成长画像过长，请压缩指标复述并保留画像主线。")

    profile = assessment_result.get("respondent_profile", {})
    profile = profile if isinstance(profile, dict) else {}
    supplied_background = any(
        str(profile.get(key, "")).strip()
        for key in ("background", "known_context", "parent_observations", "teacher_observations")
    )
    if not supplied_background:
        unsupported_patterns = (
            r"孩子(?:喜欢|经常|总是|习惯于|能够|会主动|乐于)",
            r"(?:在班里|在班级|在小组(?:活动)?中|在学校里|在校内|与同学|与老师)",
            r"对学校有归属感",
        )
        hits = [pattern for pattern in unsupported_patterns if re.search(pattern, body)]
        if hits:
            issues.append(
                "[major] 核心成长画像把测评分数扩写成了输入未提供的真实经历或稳定习惯；"
                "请改为‘当任务需要……时，孩子更可能……’等条件式趋势表达。"
            )

    has_strength = any(
        _classify_score_band(item) == "advantage"
        for item in _iter_score_items(assessment_result)
    )
    has_support = any(
        _classify_score_band(item) == "potential"
        for item in _iter_score_items(assessment_result)
    )
    bridge_terms = ("同时", "而", "这也为", "可以成为", "以此为起点", "借助", "带动", "支持")
    if has_strength and has_support and not any(term in body for term in bridge_terms):
        issues.append(
            "[major] 核心成长画像同时涉及优势和支持重点，却没有解释二者的联系；"
            "请写清可借助哪项优势带动哪项能力发展。"
        )
    return issues


def _normalize_core_portrait_labels(
    report: str,
    assessment_result: dict[str, Any],
) -> str:
    """Prevent a no-potential profile from rendering a misleading 潜力 heading."""
    has_potential_dimension = any(
        _classify_score_band(item) == "potential"
        for item in _iter_score_items(assessment_result)
    )
    if has_potential_dimension:
        return report
    parsed, _ = parse_report_json(report)
    if parsed is None:
        return report
    for section in parsed.get("sections", []):
        if not isinstance(section, dict) or section.get("section_id") != "core_growth_portrait":
            continue
        body = str(section.get("body", ""))
        body = body.replace("【潜力】", "【发展基础】")
        body = body.replace("没有明确的潜力区需要优先支持", "当前没有需要优先支持的指标")
        body = body.replace("没有潜力区需要优先支持", "当前没有需要优先支持的指标")
        section["body"] = body
    return json.dumps(parsed, ensure_ascii=False, indent=2)


def _data_sketch_level_issues(
    report_json: dict[str, Any],
    assessment_result: dict[str, Any],
) -> list[str]:
    """Keep TextAgent's portrait labels traceable to scoring-service metadata."""
    source_levels: dict[str, str] = {}
    for item in _iter_score_items(assessment_result):
        level = str(item.get("level", "")).strip()
        if not level:
            continue
        for name in (item.get("dimension_name"), item.get("key")):
            normalized = _normalize_dimension_name(name)
            if normalized:
                source_levels[normalized] = level

    if not source_levels:
        return []

    data_sketch = report_json.get("data_sketch")
    if not isinstance(data_sketch, dict):
        return ["[major] TextAgent 输出缺少可核对层级的 data_sketch 对象"]

    issues: list[str] = []
    for bucket in (
        "advantage_dimensions",
        "developing_dimensions",
        "middle_dimensions",
    ):
        entries = data_sketch.get(bucket, [])
        if not isinstance(entries, list):
            continue
        for index, entry in enumerate(entries):
            if not isinstance(entry, dict):
                continue
            name = entry.get("dimension_name") or entry.get("dimension") or entry.get("key")
            source_level = source_levels.get(_normalize_dimension_name(name))
            if not source_level:
                continue

            reported_source_level = str(entry.get("source_level", "")).strip()
            visible_level = str(entry.get("level", "")).strip()
            location = f"data_sketch.{bucket}[{index}]"

            if not reported_source_level:
                issues.append(
                    f"[major] {location} 缺少 source_level，无法追溯“{name}”的原始层级“{source_level}”"
                )
            elif _normalize_level(reported_source_level) != _normalize_level(source_level):
                issues.append(
                    f"[major] {location}.source_level 与输入不一致：{name} 输入为“{source_level}”，输出为“{reported_source_level}”"
                )

            if visible_level and not _visible_level_matches_source(visible_level, source_level):
                issues.append(
                    f"[major] {location}.level 擅自改写层级：{name} 输入为“{source_level}”，输出为“{visible_level}”"
                )

    return issues


def _detailed_indicator_coverage_issues(
    report_json: dict[str, Any],
    assessment_result: dict[str, Any],
) -> list[str]:
    """Require one explicit, renderer-addressable block for every supplied metric."""
    detail_body = "\n".join(
        str(section.get("body", "")).strip()
        for section in report_json.get("sections", [])
        if isinstance(section, dict)
        and section.get("section_id") == "detailed_indicator_analysis"
    )
    if not detail_body:
        return []

    headings = {
        _normalize_dimension_name(match.group(1))
        for match in re.finditer(r"【\s*([^】]+?)\s*】", detail_body)
        if match.group(1).strip()
    }
    expected_names = []
    score_items_by_name: dict[str, dict[str, Any]] = {}
    for item in _iter_score_items(assessment_result):
        name = str(item.get("dimension_name") or item.get("key") or "").strip()
        normalized = _normalize_dimension_name(name)
        if name and normalized:
            expected_names.append((name, normalized))
            score_items_by_name[normalized] = item

    missing = [
        name
        for name, normalized in expected_names
        if not any(
            heading == normalized or heading.startswith(normalized)
            for heading in headings
        )
    ]
    issues: list[str] = []
    if missing:
        issues.append(
            "[major] detailed_indicator_analysis 未为全部已测指标提供独立【指标名】解读块："
            + "、".join(missing)
        )

    definition_cues = (
        "反映", "衡量", "观察", "用于理解", "指向", "涉及", "关注", "评估",
        "考察", "描述", "指学生", "指儿童", "指孩子", "指个体", "指你",
        "代表", "作为", "即",
    )
    translation_cues = (
        "本次",
        "结合这项表现",
        "这提示",
        "这说明",
        "在需要",
        "课堂",
        "写作业",
        "阅读",
        "小组",
        "家庭",
        "家长可",
        "家长可以",
        "当前",
        "处于",
        "满分",
        "按规则",
    )
    for match in re.finditer(r"【\s*([^】]+?)\s*】(?P<body>.*?)(?=\n【|$)", detail_body, re.DOTALL):
        normalized_heading = _normalize_dimension_name(match.group(1))
        if not any(
            normalized_heading == expected or normalized_heading.startswith(expected)
            for _, expected in expected_names
        ):
            continue
        readable_length = len(re.sub(r"\s+", "", match.group("body")))
        if readable_length < 55:
            issues.append(
                f"[minor] 指标“{match.group(1).strip()}”的解释过短，建议补足专业界定与家长可观察的通俗说明"
            )
        block_text = match.group("body")
        if not any(cue in block_text for cue in definition_cues):
            issues.append(
                f"[major] 指标“{match.group(1).strip()}”缺少准确的专业界定（先说明该指标观察什么）"
            )
        has_result_signal = any(cue in block_text for cue in translation_cues)
        parent_scene_cues = (
            "家长",
            "阅读",
            "书写",
            "作业",
            "课堂",
            "小组",
            "家庭",
            "活动",
            "任务",
            "情境",
            "日常",
            "练习",
            "观察",
            "场合",
            "日记",
            "故事",
            "手工",
            "拼搭",
            "自然",
            "讨论",
            "创作",
            "选项",
            "规则",
            "指令",
            "学习",
            "学校",
            "情绪",
            "挫折",
            "进步",
            "资料",
            "方案",
            "项目",
            "目标",
            "信息",
            "观点",
            "知识",
            "复习",
            "计划",
            "压力",
            "受挫",
            "作品",
            "发言",
            "展示",
            "实验",
            "问题",
        )
        has_result_analysis = any(cue in block_text for cue in parent_scene_cues)
        if not has_result_signal or not has_result_analysis:
            issues.append(
                f"[major] 指标“{match.group(1).strip()}”缺少基于本次结果的任务表现分析或情境说明"
            )

        sentences = [
            re.sub(r"\s+", "", sentence).strip("。！？；")
            for sentence in re.split(r"[。！？；]", block_text)
        ]
        sentences = [sentence for sentence in sentences if len(sentence) >= 16]
        duplicated_sentences = sorted(
            sentence for sentence in set(sentences) if sentences.count(sentence) > 1
        )
        if duplicated_sentences:
            issues.append(
                f"[major] 指标“{match.group(1).strip()}”重复了专业界定或结果句，"
                "受控事实层与模型翻译发生叠加"
            )

        visible_level_count = sum(
            block_text.count(level)
            for level in ("优势区", "常态区", "潜力区")
        )
        if visible_level_count > 1:
            issues.append(
                f"[major] 指标“{match.group(1).strip()}”重复出现层级结论，"
                "每个指标块只能保留一次输入校准后的层级"
            )

        source_item = score_items_by_name.get(normalized_heading, {})
        if _classify_score_band(source_item) == "advantage":
            weakening_pattern = (
                r"(?:复杂|高压|干扰|多重指令|要求提高|任务叠加).{0,42}"
                r"(?:延迟|困难|较弱|不稳|波动|受影响|需要.{0,6}(?:提醒|支持)|退化)"
            )
            if re.search(weakening_pattern, block_text):
                issues.append(
                    f"[major] 指标“{match.group(1).strip()}”输入为优势区，"
                    "结果分析不应自动附加复杂情境下的退化或弱化尾注；"
                    "请改写为稳定表现及其积极作用"
                )

    direct_parent_instruction_count = len(
        re.findall(r"(?:家长|父母).{0,8}(?:可|可以|不妨|建议|留意|观察)", detail_body)
    )
    if direct_parent_instruction_count > 3:
        issues.append(
            "[major] 详细指标分析中直接面向家长的指令过多（"
            f"{direct_parent_instruction_count} 次）；该页应优先解释分数对应的任务表现，"
            "具体行动放入成长支持建议"
        )
    return issues


def _controlled_result_analysis(block_body: str) -> str:
    """Extract the reader-facing analysis after the local score conclusion."""
    marker = re.search(
        r"(?:"
        r"本项得分满分，按本量表规则列为优势区。|"
        r"按本次评估的同班参照，本项处于(?:优势区|常态区|潜力区)。|"
        r"按输入的量表解释，本项处于(?:优势区|常态区|潜力区)。|"
        r"本项指标目前处于(?:优势区|常态区|潜力区)。"
        r")",
        block_body,
    )
    if not marker:
        return ""
    return block_body[marker.end() :].strip()


def _normalized_analysis_fingerprint(text: str) -> str:
    """Normalize punctuation and spacing so exact template reuse is detectable."""
    return re.sub(r"[\s，,。！？；;：:、“”‘’（）()《》]+", "", text)


def _detailed_indicator_duplicate_analysis_issues(
    report_json: dict[str, Any],
) -> list[str]:
    """Reject one interchangeable result paragraph reused across metrics."""
    detail_body = _section_body(report_json, "detailed_indicator_analysis")
    if not detail_body:
        return []

    groups: dict[str, list[str]] = {}
    for match in re.finditer(
        r"【\s*([^】]+?)\s*】(?P<body>.*?)(?=\n\s*【|\Z)",
        detail_body,
        flags=re.S,
    ):
        name = match.group(1).strip()
        analysis = _controlled_result_analysis(match.group("body"))
        fingerprint = _normalized_analysis_fingerprint(analysis)
        if len(fingerprint) >= 18:
            groups.setdefault(fingerprint, []).append(name)

    duplicate_groups = [names for names in groups.values() if len(names) >= 2]
    if not duplicate_groups:
        return []
    return [
        "[major] 不同指标复用了完全相同的结果分析，未体现各指标独有的任务含义："
        + "；".join("、".join(names) for names in duplicate_groups)
    ]


SECONDARY_METRIC_ADVICE_PATTERN = re.compile(
    r"(?:建议|你可以|可以继续|可以尝试|不妨|本周|今天|下一次|下次|从.+开始|"
    r"(?:^|[。；])先.{0,30}再|写下|列出|圈出|打勾|计时|录音|回听|"
    r"做一(?:张|个|次)|完成后|结束后|连续\d|练习\d|练习。)"
)

SECONDARY_METRIC_INTERPRETATION_CUES = (
    "任务",
    "学习",
    "讨论",
    "表达",
    "合作",
    "项目",
    "信息",
    "问题",
    "规则",
    "情绪",
    "压力",
    "投入",
    "理解",
    "判断",
    "表现",
    "基础",
    "资源",
    "稳定",
    "影响",
    "支持",
    "有助于",
    "更容易",
    "可能",
)


def _is_secondary_metric_interpretation(text: str) -> bool:
    """Accept analysis that explains the result without turning into advice."""
    compact = re.sub(r"\s+", "", str(text or ""))
    return (
        len(compact) >= 42
        and not SECONDARY_METRIC_ADVICE_PATTERN.search(compact)
        and any(cue in compact for cue in SECONDARY_METRIC_INTERPRETATION_CUES)
    )


def _detailed_indicator_role_issues(
    report_json: dict[str, Any],
    assessment_result: dict[str, Any],
) -> list[str]:
    """Keep secondary metric cards analytical and move actions to final advice."""
    if resolve_report_stage(assessment_result) not in SECONDARY_REPORT_STAGES:
        return []
    detail_body = _section_body(report_json, "detailed_indicator_analysis")
    if not detail_body:
        return []

    issues: list[str] = []
    for match in re.finditer(
        r"【\s*([^】]+?)\s*】(?P<body>.*?)(?=\n\s*【|\Z)",
        detail_body,
        flags=re.S,
    ):
        name = match.group(1).strip()
        analysis = _controlled_result_analysis(match.group("body"))
        if not analysis:
            continue
        if SECONDARY_METRIC_ADVICE_PATTERN.search(analysis):
            issues.append(
                f"[major] 指标“{name}”的结果分析混入了行动建议；"
                "详细指标页只解释当前表现、发展含义和影响条件，"
                "具体做法应统一放入成长支持建议。"
            )
        elif not _is_secondary_metric_interpretation(analysis):
            issues.append(
                f"[minor] 指标“{name}”的结果分析过短或仍停留在层级复述；"
                "请补充该能力在对应任务中的可能表现、发展价值或影响其发挥的条件。"
            )
    return issues


def _normalize_dimension_name(value: Any) -> str:
    normalized = re.sub(r"[\s【】()（）_-]", "", str(value or "")).lower()
    canonical = METRIC_ALIASES.get(normalized)
    if not canonical:
        return normalized
    return re.sub(r"[\s【】()（）_-]", "", canonical).lower()


def _normalize_level(value: Any) -> str:
    return re.sub(r"[\s()（）_-]", "", str(value or "")).lower()


def _visible_level_matches_source(visible_level: str, source_level: str) -> bool:
    visible = _normalize_level(visible_level)
    source = _normalize_level(source_level)
    return visible == source or visible.startswith(source)


def _unsupported_specific_experience_issues(
    report_json: dict[str, Any],
    assessment_result: dict[str, Any],
) -> list[str]:
    assessment_text = compact_json(assessment_result)
    issues = []
    for location, text in _iter_visible_advice_fields(report_json):
        for pattern, reason in UNSUPPORTED_EXPERIENCE_PATTERNS.items():
            match = re.search(pattern, text)
            if not match:
                continue
            matched_text = match.group(0)
            if matched_text and matched_text in assessment_text:
                continue
            issues.append(
                f"[major] {location} {reason}：{matched_text}。请改成“如果孩子最近...”“可以选一个孩子熟悉的...”等可替换场景。"
            )
            break
    return issues


def _iter_visible_advice_fields(
    report_json: dict[str, Any],
) -> list[tuple[str, str]]:
    items: list[tuple[str, str]] = []
    for index, section in enumerate(report_json.get("sections", [])):
        if not isinstance(section, dict):
            continue
        body = str(section.get("body", "")).strip()
        if not body:
            continue
        if section.get("section_id") == "detailed_indicator_analysis":
            blocks = list(
                re.finditer(r"【\s*([^】]+?)\s*】.*?(?=\n\s*【|\Z)", body, re.DOTALL)
            )
            if blocks:
                for block in blocks:
                    metric = block.group(1).strip()
                    items.append(
                        (f"sections[{index}].body[{metric}]", block.group(0).strip())
                    )
                continue
        items.append((f"sections[{index}].body", body))

    for index, suggestion in enumerate(report_json.get("parent_suggestions", [])):
        if not isinstance(suggestion, dict):
            continue
        for key in ("category", "scene", "action", "parent_wording", "first_step"):
            value = str(suggestion.get(key, "")).strip()
            if value:
                items.append((f"parent_suggestions[{index}].{key}", value))
    return items


def chat_text(
    client: OpenAI,
    messages: list[dict[str, str]],
    *,
    json_output: bool = False,
) -> str:
    kwargs: dict[str, Any] = {
        "model": MODEL,
        "messages": messages,
        "max_tokens": max(512, int(os.environ.get("DEEPSEEK_MAX_OUTPUT_TOKENS", "16000"))),
    }

    if json_output:
        kwargs["response_format"] = {"type": "json_object"}

    max_attempts = max(
        2 if json_output else 1,
        int(os.environ.get("DEEPSEEK_MAX_RETRIES", "4")),
    )
    base_sleep_seconds = float(os.environ.get("DEEPSEEK_RETRY_BASE_SECONDS", "2"))
    max_sleep_seconds = max(
        base_sleep_seconds,
        float(os.environ.get("DEEPSEEK_RETRY_MAX_SECONDS", "30")),
    )
    jitter_seconds = max(0.0, float(os.environ.get("DEEPSEEK_RETRY_JITTER_SECONDS", "0.5")))
    transient_errors = (
        APIConnectionError,
        APITimeoutError,
        InternalServerError,
        RateLimitError,
        httpx.ConnectError,
        httpx.ReadError,
        httpx.RemoteProtocolError,
    )
    # Non-streaming is the reliable default for structured report generation.
    # Some proxies and OpenAI-compatible gateways terminate long SSE responses,
    # which previously surfaced as incomplete JSON or opaque HTTP 400 errors.
    use_stream = os.environ.get("DEEPSEEK_STREAM", "0").strip().lower() not in {
        "0",
        "false",
        "no",
    }
    json_mode_fallback_used = False

    for attempt in range(1, max_attempts + 1):
        try:
            if use_stream:
                stream = client.chat.completions.create(**kwargs, stream=True)
                parts: list[str] = []
                try:
                    for chunk in stream:
                        for choice in chunk.choices:
                            content = getattr(choice.delta, "content", None)
                            if content:
                                parts.append(content)
                except transient_errors:
                    partial = "".join(parts).strip()
                    if json_output and partial:
                        try:
                            parsed = json.loads(partial)
                        except json.JSONDecodeError:
                            # A broken stream normally ends mid-JSON. Let the outer
                            # transient-error handler retry instead of surfacing a
                            # misleading JSONDecodeError.
                            pass
                        else:
                            if isinstance(parsed, dict):
                                return partial
                    raise
                text = "".join(parts).strip()
                if not text:
                    raise RuntimeError("DeepSeek stream ended without text output")
                if json_output:
                    try:
                        parsed = json.loads(text)
                    except json.JSONDecodeError as exc:
                        if attempt >= max_attempts:
                            raise RuntimeError(
                                "DeepSeek 连续返回了不完整的 JSON；请稍后重试。"
                            ) from exc
                        sleep_seconds = min(
                            max_sleep_seconds,
                            base_sleep_seconds * (2 ** (attempt - 1)),
                        ) + random.uniform(0, jitter_seconds)
                        print(
                            (
                                f"DeepSeek returned incomplete JSON on attempt "
                                f"{attempt}/{max_attempts}; retrying after "
                                f"{sleep_seconds:.1f}s."
                            ),
                            file=sys.stderr,
                        )
                        time.sleep(sleep_seconds)
                        continue
                    if not isinstance(parsed, dict):
                        raise RuntimeError("DeepSeek JSON 输出的顶层不是 object")
                return text

            response = client.chat.completions.create(**kwargs, stream=False)
            text = (response.choices[0].message.content or "").strip()
            if not text:
                raise RuntimeError("DeepSeek response ended without text output")
            if json_output:
                try:
                    parsed = parse_json_object(strip_markdown_code_fence(text))
                except json.JSONDecodeError as exc:
                    if attempt >= max_attempts:
                        raise RuntimeError(
                            "DeepSeek 连续返回了语法不完整的 JSON；"
                            f"最后一次错误位于 line {exc.lineno} column {exc.colno}。"
                        ) from exc
                    sleep_seconds = min(
                        max_sleep_seconds,
                        base_sleep_seconds * (2 ** (attempt - 1)),
                    ) + random.uniform(0, jitter_seconds)
                    print(
                        (
                            "DeepSeek returned invalid JSON in non-streaming mode "
                            f"on attempt {attempt}/{max_attempts} "
                            f"(line {exc.lineno}, column {exc.colno}); retrying "
                            f"after {sleep_seconds:.1f}s."
                        ),
                        file=sys.stderr,
                    )
                    time.sleep(sleep_seconds)
                    continue
                if not isinstance(parsed, dict):
                    raise RuntimeError("DeepSeek JSON 输出的顶层不是 object")
            return text
        except BadRequestError as exc:
            # DeepSeek-compatible gateways occasionally reject response_format
            # even though the prompt itself asks for strict JSON. Retry once
            # without that optional OpenAI parameter and use non-streaming mode.
            if json_output and "response_format" in kwargs and not json_mode_fallback_used:
                json_mode_fallback_used = True
                kwargs.pop("response_format", None)
                use_stream = False
                print(
                    "DeepSeek rejected response_format=json_object; retrying once without response_format in non-streaming mode.",
                    file=sys.stderr,
                )
                continue

            response = getattr(exc, "response", None)
            detail = ""
            body = getattr(exc, "body", None)
            if body:
                try:
                    detail = json.dumps(body, ensure_ascii=False)
                except (TypeError, ValueError):
                    detail = str(body).strip()
            if response is not None:
                try:
                    detail = detail or str(response.text).strip()
                except Exception:
                    pass
            detail = detail[:1200] if detail else "服务端未返回可读详情"
            raise RuntimeError(
                "DeepSeek 拒绝了请求（HTTP 400）。"
                f"当前模型为 {MODEL!r}；请优先使用 DEEPSEEK_MODEL=deepseek-chat。"
                f"服务端详情：{detail}"
            ) from exc
        except transient_errors as exc:
            if attempt >= max_attempts:
                raise

            sleep_seconds = min(
                max_sleep_seconds,
                base_sleep_seconds * (2 ** (attempt - 1)),
            ) + random.uniform(0, jitter_seconds)
            cause = exc.__cause__
            cause_detail = f" | cause={type(cause).__name__}: {cause}" if cause else ""
            print(
                (
                    f"DeepSeek transient error on attempt {attempt}/{max_attempts}; "
                    f"retrying after {sleep_seconds:.1f}s: {type(exc).__name__}: {exc}"
                    f"{cause_detail}"
                ),
                file=sys.stderr,
            )
            time.sleep(sleep_seconds)

    raise RuntimeError("DeepSeek API 调用失败，且重试逻辑未返回结果")


def compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


class RetrievalAgent:
    """Finds context for the generator, including local expert report RAG cases."""

    def __init__(self) -> None:
        self.examples_dir = ROOT_DIR / "rag_examples"
        self.report_text_cases_dir = self.examples_dir / "report_text_cases"
        self.standard_segments_path = self.report_text_cases_dir / "standard_segments.jsonl"
        self.gold_reports_dir = self.examples_dir / "gold_comprehensive_reports"
        self.gold_segments_path = self.gold_reports_dir / "gold_segments.jsonl"
        # Raw Excel templates remain available for offline audit/build tooling only.
        # Runtime generation consumes metric_reference_cards instead.
        self.dimension_detail_templates_path = (
            self.examples_dir / "dimension_detail_templates.jsonl"
        )
        self.metric_reference_cards_path = (
            self.examples_dir / "metric_reference_cards.jsonl"
        )

    def run(self, assessment_result: dict[str, Any]) -> dict[str, Any]:
        report_stage = resolve_report_stage(assessment_result)
        profile = self._build_score_profile(assessment_result)
        max_segments = max(1, int(os.environ.get("TEXT_AGENT_RAG_SEGMENTS", "6")))
        standard_segments = (
            self._retrieve_standard_segments(profile, max_segments=max_segments)
            if report_stage == "elementary"
            else []
        )
        metric_reference_cards = self._retrieve_metric_reference_cards(
            assessment_result
        )
        gold_metric_references = self._retrieve_gold_metric_references(
            assessment_result,
            max_per_metric=max(
                1, int(os.environ.get("TEXT_AGENT_GOLD_REFERENCES_PER_METRIC", "1"))
            ),
        )
        gold_section_references = (
            self._retrieve_gold_section_references(
                profile,
                max_items=max(
                    1, int(os.environ.get("TEXT_AGENT_GOLD_SECTION_REFERENCES", "3"))
                ),
            )
            if report_stage == "elementary"
            else []
        )
        standard_segments_for_prompt = [
            self._to_style_reference(segment) for segment in standard_segments
        ]
        return {
            "scale_notes": self._load_memory("scale_knowledge"),
            "style_notes": self._load_memory("style_guide"),
            "retrieved_examples": (
                self._retrieve_examples(assessment_result)
                if report_stage == "elementary"
                else []
            ),
            "retrieved_standard_segments": standard_segments_for_prompt,
            "retrieved_standard_segments_by_section": self._group_segments_by_section(
                standard_segments_for_prompt
            ),
            "metric_reference_cards": metric_reference_cards,
            "gold_metric_references": gold_metric_references,
            "gold_section_references": gold_section_references,
            "retrieval_profile": self._compact_score_profile(profile),
            "retrieval_summary": {
                "report_stage": report_stage,
                "standard_segment_count": len(standard_segments),
                "standard_segment_source": str(self.standard_segments_path),
                "metric_reference_card_count": len(metric_reference_cards),
                "metric_reference_card_source": str(self.metric_reference_cards_path),
                "gold_metric_reference_count": sum(
                    len(items) for items in gold_metric_references.values()
                ),
                "gold_metric_reference_source": str(self.gold_segments_path),
                "gold_section_reference_count": len(gold_section_references),
                "strategy": (
                    "section_quota_keyword_rag_v1"
                    if report_stage == "elementary"
                    else "secondary_skill_only_until_stage_tagged_rag_exists"
                ),
            },
        }

    def _retrieve_metric_reference_cards(
        self,
        assessment_result: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Retrieve one safe Excel-derived reference card per supplied metric."""
        if not self.metric_reference_cards_path.exists():
            return []
        cards_by_metric: dict[str, list[dict[str, Any]]] = {}
        with self.metric_reference_cards_path.open("r", encoding="utf-8") as file:
            for line in file:
                if not line.strip():
                    continue
                card = json.loads(line)
                key = _normalize_dimension_name(card.get("metric", ""))
                if key:
                    cards_by_metric.setdefault(key, []).append(card)

        selected = []
        for item in _iter_score_items(assessment_result):
            metric = str(item.get("dimension_name") or item.get("key") or "").strip()
            try:
                score = float(item.get("score"))
            except (TypeError, ValueError):
                continue
            candidates = cards_by_metric.get(_normalize_dimension_name(metric), [])
            matched = [
                card
                for card in candidates
                if card.get("score_band", {}).get("min", 0) <= score
                <= card.get("score_band", {}).get("max", 100)
            ]
            if not matched:
                continue
            card = max(
                matched,
                key=lambda value: value.get("score_band", {}).get("min", 0),
            )
            selected.append(
                {
                    "card_id": card.get("card_id"),
                    "metric": metric,
                    "score_band": card.get("score_band", {}),
                    "professional_label": card.get("professional_label", ""),
                    "professional_definition": card.get(
                        "professional_definition", ""
                    ),
                    "parent_translation_focus": card.get(
                        "parent_translation_focus", ""
                    ),
                    "xlsx_definition_reference": card.get(
                        "xlsx_definition_reference", ""
                    ),
                    "score_band_use": card.get("score_band_use", ""),
                    "do_not_use": card.get("do_not_use", []),
                    "legacy_risk_terms": card.get("legacy_risk_terms", []),
                    "review_status": card.get("review_status", ""),
                }
            )
        return selected

    def _read_gold_segments(self) -> list[dict[str, Any]]:
        if not self.gold_segments_path.exists():
            return []
        records = []
        with self.gold_segments_path.open("r", encoding="utf-8") as file:
            for line in file:
                if not line.strip():
                    continue
                value = json.loads(line)
                if isinstance(value, dict):
                    records.append(value)
        return records

    def _retrieve_gold_metric_references(
        self,
        assessment_result: dict[str, Any],
        *,
        max_per_metric: int,
    ) -> dict[str, list[dict[str, Any]]]:
        """Return a tiny method exemplar per metric, never a child-data reference."""
        gold_segments = self._read_gold_segments()
        result: dict[str, list[dict[str, Any]]] = {}
        for item in _iter_score_items(assessment_result):
            metric = str(item.get("dimension_name") or item.get("key") or "").strip()
            if not metric:
                continue
            normalized = _normalize_dimension_name(metric)
            matches = [
                segment
                for segment in gold_segments
                if _normalize_dimension_name(segment.get("indicator", "")) == normalized
                and segment.get("section_type") == "detailed_indicator_analysis"
            ]
            if not matches:
                continue
            result[metric] = [
                self._compact_gold_reference(segment) for segment in matches[:max_per_metric]
            ]
        return result

    def _retrieve_gold_section_references(
        self,
        profile: dict[str, Any],
        *,
        max_items: int,
    ) -> list[dict[str, Any]]:
        allowed_sections = {
            "preface",
            "core_growth_portrait",
            "growth_support_suggestions",
        }
        candidates = [
            segment
            for segment in self._read_gold_segments()
            if segment.get("section_type") in allowed_sections
            and len(str(segment.get("text", ""))) >= 50
        ]
        candidates.sort(
            key=lambda item: (
                item.get("section_type") == "growth_support_suggestions",
                len(str(item.get("text", ""))),
            ),
            reverse=True,
        )
        return [self._compact_gold_reference(item) for item in candidates[:max_items]]

    def _compact_gold_reference(self, segment: dict[str, Any]) -> dict[str, Any]:
        """Expose a gold report's writing method without exposing its prose."""
        section_type = str(segment.get("section_type", "")).strip()
        method_patterns = {
            "detailed_indicator_analysis": [
                "professional_definition",
                "source_level_calibration",
                "conditional_parent_translation",
            ],
            "core_growth_portrait": [
                "select_representative_evidence",
                "explain_profile_relationship",
                "do_not_list_all_scores",
            ],
            "growth_support_suggestions": [
                "data_basis",
                "scene_action_parent_wording_first_step",
                "do_not_assume_history",
            ],
            "preface": [
                "scope_and_parent_goal",
                "non_diagnostic_boundary",
            ],
        }
        return {
            "gold_segment_id": segment.get("gold_segment_id"),
            "section_type": section_type,
            "indicator": segment.get("indicator"),
            "method_pattern": method_patterns.get(
                section_type,
                ["restrained_parent_facing_explanation"],
            ),
            "use_rule": (
                "仅学习结构方法；不得使用或复述原始段落、人物、经历、分数或结论。"
            ),
        }

    def _retrieve_dimension_detail_templates(
        self,
        assessment_result: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Retrieve one score-band writing pattern per supplied metric."""
        if not self.dimension_detail_templates_path.exists():
            return []

        templates_by_metric: dict[str, list[dict[str, Any]]] = {}
        with self.dimension_detail_templates_path.open("r", encoding="utf-8") as file:
            for line in file:
                if not line.strip():
                    continue
                template = json.loads(line)
                key = _normalize_dimension_name(template.get("metric", ""))
                if key:
                    templates_by_metric.setdefault(key, []).append(template)

        selected = []
        for item in _iter_score_items(assessment_result):
            name = str(item.get("dimension_name") or item.get("key") or "").strip()
            try:
                score = float(item.get("score"))
            except (TypeError, ValueError):
                continue
            candidates = templates_by_metric.get(_normalize_dimension_name(name), [])
            matched = [
                template
                for template in candidates
                if template.get("score_band", {}).get("min", 0) <= score
                <= template.get("score_band", {}).get("max", 100)
            ]
            if not matched:
                continue
            # Boundaries such as 80 select the higher-intensity 80-100 pattern.
            template = max(
                matched,
                key=lambda value: value.get("score_band", {}).get("min", 0),
            )
            selected.append(
                {
                    "template_id": template.get("template_id"),
                    "metric": name,
                    "score_band": template.get("score_band", {}).get("label"),
                    "source_definition": template.get("source_definition", ""),
                    "legacy_risk_terms": template.get("legacy_risk_terms", []),
                    "rewrite_policy": template.get("rewrite_policy", {}),
                    "parent_translation_rule": (
                        "用条件式的当前倾向或家长观察点翻译；不把范文中的"
                        "活动、人物关系或既往行为当作本生事实。"
                    ),
                }
            )
        return selected

    def _to_style_reference(self, segment: dict[str, Any]) -> dict[str, Any]:
        """Keep report-corpus retrieval useful without injecting another child's prose."""
        return {
            "segment_id": segment.get("segment_id"),
            "case_id": segment.get("case_id"),
            "expert_source": segment.get("expert_source"),
            "section_type": segment.get("section_type"),
            "title": segment.get("title"),
            "dimensions": segment.get("dimensions", []),
            "style_instruction": (
                "仅参考该章节的组织顺序、信息密度与克制语气；"
                "不可复用原文措辞、人物称呼、具体经历或指标结论。"
            ),
        }

    def _load_memory(self, name: str) -> str:
        return load_text(MEMORY_DIR / f"{name}.md")

    def _retrieve_examples(self, assessment_result: dict[str, Any]) -> list[dict[str, Any]]:
        if not self.examples_dir.exists():
            return []

        examples = []
        for path in self.examples_dir.glob("*.json"):
            with path.open("r", encoding="utf-8") as file:
                example = json.load(file)
            example["_match_score"] = self._score_example(assessment_result, example)
            examples.append(example)

        examples.sort(key=lambda item: item.get("_match_score", 0), reverse=True)
        return examples[:3]

    def _retrieve_standard_segments(
        self,
        profile: dict[str, Any],
        *,
        max_segments: int = 12,
    ) -> list[dict[str, Any]]:
        if not self.standard_segments_path.exists():
            return []

        candidates = []
        with self.standard_segments_path.open("r", encoding="utf-8") as file:
            for line in file:
                if not line.strip():
                    continue
                segment = json.loads(line)
                if self._is_rag_unsafe_segment(segment):
                    continue
                segment["_match_score"] = self._score_standard_segment(profile, segment)
                candidates.append(segment)

        candidates.sort(key=lambda item: item.get("_match_score", 0), reverse=True)
        selected = self._select_diverse_segments(candidates, max_segments=max_segments)
        return [self._compact_segment_for_prompt(item) for item in selected]

    def _compact_score_profile(self, profile: dict[str, Any]) -> dict[str, Any]:
        return {
            "dimensions": sorted(profile["dimensions"]),
            "top_dimensions": sorted(profile["top_dimensions"]),
            "low_dimensions": sorted(profile["low_dimensions"]),
            "levels": profile["levels"],
        }

    def _group_segments_by_section(
        self,
        segments: list[dict[str, Any]],
    ) -> dict[str, list[dict[str, Any]]]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for segment in segments:
            section_type = str(segment.get("section_type", "other"))
            grouped.setdefault(section_type, []).append(segment)
        return grouped

    def _build_score_profile(self, assessment_result: dict[str, Any]) -> dict[str, Any]:
        dimensions = set()
        top_dimensions = set()
        low_dimensions = set()
        levels = {}

        for item in _iter_score_items(assessment_result):
            names = {
                str(item.get("key") or ""),
                str(item.get("dimension_name") or ""),
                str(item.get("domain") or ""),
            }
            names = {name for name in names if name}
            dimensions.update(names)

            band = _classify_score_band(item)
            for name in names:
                if band:
                    levels[name] = band
                if band == "advantage":
                    top_dimensions.add(name)
                elif band == "potential":
                    low_dimensions.add(name)

        return {
            "dimensions": dimensions,
            "top_dimensions": top_dimensions,
            "low_dimensions": low_dimensions,
            "levels": levels,
        }

    def _score_standard_segment(
        self,
        profile: dict[str, Any],
        segment: dict[str, Any],
    ) -> int:
        section_weights = {
            "core_growth_portrait": 7,
            "growth_support_suggestions": 7,
            "detailed_indicator_analysis": 5,
            "preface": 3,
            "boundary_note": 2,
        }
        score = section_weights.get(segment.get("section_type", ""), 1)

        segment_dimensions = set(segment.get("dimensions", []))
        segment_top = set(segment.get("top_dimensions", []))
        segment_low = set(segment.get("low_dimensions", []))

        score += 8 * len(profile["dimensions"] & segment_dimensions)
        score += 6 * len(profile["top_dimensions"] & segment_top)
        score += 6 * len(profile["low_dimensions"] & segment_low)

        if segment.get("expert_source") == "综合版":
            score += 2

        return score

    def _select_diverse_segments(
        self,
        candidates: list[dict[str, Any]],
        *,
        max_segments: int,
    ) -> list[dict[str, Any]]:
        selected = []
        used_ids = set()
        quotas = {
            "preface": 1,
            "core_growth_portrait": 2 if max_segments <= 6 else 3,
            "detailed_indicator_analysis": 2 if max_segments <= 6 else 4,
            "growth_support_suggestions": 1 if max_segments <= 6 else 4,
        }

        for section_type, quota in quotas.items():
            section_candidates = [
                item for item in candidates if item.get("section_type") == section_type
            ]
            selected.extend(
                self._take_with_case_diversity(
                    section_candidates,
                    quota=quota,
                    used_ids=used_ids,
                )
            )

        if len(selected) < max_segments:
            selected_ids = {item.get("segment_id") for item in selected}
            filler = [
                item
                for item in candidates
                if item.get("segment_id") not in selected_ids
            ]
            selected.extend(
                self._take_with_case_diversity(
                    filler,
                    quota=max_segments - len(selected),
                    used_ids=used_ids,
                    allow_existing_case=True,
                )
            )

        return selected[:max_segments]

    def _take_with_case_diversity(
        self,
        candidates: list[dict[str, Any]],
        *,
        quota: int,
        used_ids: set[str],
        allow_existing_case: bool = False,
    ) -> list[dict[str, Any]]:
        selected = []
        deferred = []
        for segment in candidates:
            case_id = str(segment.get("case_id", ""))
            if not allow_existing_case and case_id in used_ids:
                deferred.append(segment)
                continue
            selected.append(segment)
            used_ids.add(case_id)
            if len(selected) >= quota:
                return selected

        for segment in deferred:
            selected.append(segment)
            used_ids.add(str(segment.get("case_id", "")))
            if len(selected) >= quota:
                break

        return selected

    def _compact_segment_for_prompt(self, segment: dict[str, Any]) -> dict[str, Any]:
        text = str(segment.get("text", ""))
        max_chars = max(180, int(os.environ.get("TEXT_AGENT_RAG_SEGMENT_CHARS", "460")))
        if len(text) > max_chars:
            text = text[:max_chars].rstrip() + "..."

        return {
            "segment_id": segment.get("segment_id"),
            "case_id": segment.get("case_id"),
            "expert_source": segment.get("expert_source"),
            "section_type": segment.get("section_type"),
            "title": segment.get("title"),
            "dimensions": segment.get("dimensions", []),
            "top_dimensions": segment.get("top_dimensions", []),
            "low_dimensions": segment.get("low_dimensions", []),
            "match_score": segment.get("_match_score", 0),
            "text": text,
        }

    def _is_rag_unsafe_segment(self, segment: dict[str, Any]) -> bool:
        text = str(segment.get("text", ""))
        unsafe_terms = [
            "极其",
            "极度",
            "极强",
            "完美",
            "顶尖",
            "一流",
            "无懈可击",
            "第一梯队",
            "天生",
            "绝不",
            "脑洞大开",
            "成就大事",
            "必备心理素质",
            "问题严重",
            "极易",
            "半途而废",
            "怨天尤人",
            "画等号",
            "一定会",
            "必然",
        ]
        return any(term in text for term in unsafe_terms)

    def _score_example(
        self,
        assessment_result: dict[str, Any],
        example: dict[str, Any],
    ) -> int:
        score = 0
        profile = assessment_result.get("respondent_profile", {})
        example_tags = example.get("tags", {})

        if profile.get("age_group") == example_tags.get("age_group"):
            score += 2

        scenario = profile.get("scenario", "")
        for keyword in example_tags.get("scenario_keywords", []):
            if keyword and keyword in scenario:
                score += 1

        input_scores = assessment_result.get("scores", {})
        example_levels = example_tags.get("levels", {})
        for dimension, value in input_scores.items():
            if value.get("level") == example_levels.get(dimension):
                score += 2

        return score


def _load_indicator_definition_catalog() -> dict[str, Any]:
    path = SKILLS_DIR / "report_text" / "references" / "indicator_definition_catalog.json"
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as file:
        value = json.load(file)
    if not isinstance(value, dict):
        return {}

    # The workbook's 维度详解 first sentence is the approved construct
    # definition. Keep the catalog's label and parent-focus metadata, but do
    # not ask the model to improvise or paraphrase this factual layer.
    excel_path = (
        SKILLS_DIR
        / "report_text"
        / "references"
        / "excel_dimension_detail_definitions.json"
    )
    if not excel_path.exists():
        return value
    with excel_path.open("r", encoding="utf-8") as file:
        excel_value = json.load(file)
    excel_definitions = excel_value.get("definitions", {}) if isinstance(excel_value, dict) else {}
    indicators = value.get("indicators", value.get("metrics", {}))
    if not isinstance(indicators, dict) or not isinstance(excel_definitions, dict):
        return value

    for metric_name, metadata in indicators.items():
        if not isinstance(metadata, dict):
            continue
        matched = next(
            (
                source
                for source_name, source in excel_definitions.items()
                if _normalize_dimension_name(source_name)
                == _normalize_dimension_name(metric_name)
                and isinstance(source, str)
            ),
            None,
        )
        professional_definition = str(matched or "").strip()
        if professional_definition:
            metadata["definition"] = professional_definition
            metadata["definition_source"] = "excel_dimension_detail_first_sentence"
    return value


def _find_metric_definition(
    catalog: dict[str, Any],
    metric_name: str,
) -> dict[str, Any]:
    # The current catalog schema uses `indicators`; retain `metrics` as a
    # compatibility fallback for earlier local exports.
    metrics = catalog.get("indicators", catalog.get("metrics", {}))
    if not isinstance(metrics, dict):
        return {}
    normalized = _normalize_dimension_name(metric_name)
    for name, value in metrics.items():
        if _normalize_dimension_name(name) == normalized and isinstance(value, dict):
            return value
    return {}


DETAIL_ENTRY_PATTERNS = (
    "construct_first",
    "task_first",
    "result_first",
    "contrast_first",
)

DOMAIN_PORTRAIT_CONSTRUCTS = {
    "创新": "把想法转化为表达、作品或合作方案",
    "好奇": "察觉新异信息并继续追问和探索",
    "思维": "产生、转换、筛选并整合想法",
    "认知": "理解规则、保持目标并调节行动",
    "情绪": "维持学习投入、归属、自信与情绪恢复",
}


def _portrait_clusters(
    metric_plans: list[dict[str, Any]],
    band: str,
    *,
    max_domains: int,
    max_metrics: int,
) -> list[dict[str, Any]]:
    """Select cross-domain portrait evidence instead of taking score-order slices."""
    by_domain: dict[str, list[str]] = {}
    for item in metric_plans:
        if _classify_score_band(item) != band:
            continue
        domain = str(item.get("domain", "")).strip() or "其他"
        name = str(item.get("dimension_name", "")).strip()
        if name:
            by_domain.setdefault(domain, []).append(name)

    ranked = sorted(
        by_domain.items(),
        key=lambda pair: (-len(pair[1]), list(DOMAIN_PORTRAIT_CONSTRUCTS).index(pair[0])
                          if pair[0] in DOMAIN_PORTRAIT_CONSTRUCTS else 99),
    )
    clusters: list[dict[str, Any]] = []
    remaining = max_metrics
    for domain, names in ranked[:max_domains]:
        selected = names[: min(2, remaining)]
        if not selected:
            continue
        clusters.append(
            {
                "domain": domain,
                "dimensions": selected,
                "construct": DOMAIN_PORTRAIT_CONSTRUCTS.get(domain, "当前发展表现"),
            }
        )
        remaining -= len(selected)
        if remaining <= 0:
            break
    return clusters


def _build_portrait_blueprint(
    metric_plans: list[dict[str, Any]],
    report_stage: str = "elementary",
) -> dict[str, Any]:
    strengths = _portrait_clusters(
        metric_plans, "advantage", max_domains=2, max_metrics=3
    )
    supports = _portrait_clusters(
        metric_plans, "potential", max_domains=2, max_metrics=2
    )
    if not supports:
        supports = _portrait_clusters(
            metric_plans, "normal", max_domains=1, max_metrics=1
        )
        support_role = "balance_not_weakness"
    else:
        support_role = "development_priority"

    evidence = [
        name
        for cluster in [*strengths, *supports]
        for name in cluster["dimensions"]
    ][:5]
    student_facing = report_stage in SECONDARY_REPORT_STAGES
    paragraph_jobs = (
        [
            "第1段：用两三句形成画像主线，说明两个优势簇如何共同构成现阶段的学习或行动特点。",
            "第2段：解释优势机制在学习、项目或协作任务中的可能表现、发展价值与可迁移性；全部使用条件式表达。",
            "第3段：解释真实支持重点出现在哪类任务条件中，以及它为什么值得继续练习；不得写成固定弱项。",
            "第4段：明确已有优势如何成为支持重点的起点，并给出一条面向学生自主尝试与复盘的原则，不展开成建议卡。",
        ]
        if student_facing
        else
        [
            "第1段：一句画像主线，加上两个优势簇之间的联系。",
            "第2段：解释优势在相应任务中的可能表现及其发展价值，场景必须使用条件式表达。",
            "第3段：写支持重点及其与优势的桥接关系；常态区只能写平衡基础，不能写成弱项。",
        ]
    )
    return {
        "strength_clusters": strengths,
        "support_clusters": supports,
        "support_role": support_role,
        "selected_evidence": evidence,
        "portrait_thesis_job": (
            "先概括孩子当前最鲜明的成长组织方式，再说明这些资源如何共同发挥作用；"
            "不要以‘从整体来看’开头，也不要逐项报分。"
        ),
        "relationship_job": (
            "明确写出优势资源如何为待支持部分提供起点或桥梁，形成一幅完整画像，"
            "不能把优势和潜力写成互不相干的两张清单。"
        ),
        "paragraph_jobs": paragraph_jobs,
        "length": (
            "360-500 Chinese characters in four short paragraphs"
            if student_facing
            else "260-420 Chinese characters in two or three short paragraphs"
        ),
        "evidence_limit": 5,
        "fact_boundary": (
            "输入未提供日常背景时，不得写‘孩子喜欢/经常/能够’、‘在班里/小组中/学校里’"
            "等已经发生的事实；改写为‘当任务需要……时，更可能……’。"
        ),
    }


class ReportPlannerAgent:
    """Build a deterministic evidence plan before any generative writing.

    The plan makes score interpretation, terminology, and RAG use inspectable. It
    deliberately does not spend an API call: scoring truth is a system concern,
    not an LLM decision.
    """

    def __init__(self) -> None:
        self.definition_catalog = _load_indicator_definition_catalog()

    def run(
        self,
        assessment_result: dict[str, Any],
        retrieval_result: dict[str, Any],
    ) -> dict[str, Any]:
        report_stage = resolve_report_stage(assessment_result)
        metric_plans = []
        gold_references = retrieval_result.get("gold_metric_references", {})
        reference_cards = {
            _normalize_dimension_name(item.get("metric", "")): item
            for item in retrieval_result.get("metric_reference_cards", [])
            if isinstance(item, dict)
        }
        for index, item in enumerate(_iter_score_items(assessment_result)):
            metric = str(item.get("dimension_name") or item.get("key") or "").strip()
            if not metric:
                continue
            definition = _find_metric_definition(self.definition_catalog, metric)
            metric_plans.append(
                {
                    "dimension_name": metric,
                    "score": item.get("score"),
                    "level": item.get("level", ""),
                    "percentile_band": item.get("percentile_band", ""),
                    "rating_basis": item.get("rating_basis", ""),
                    "direction": item.get("direction", ""),
                    "interpretation": item.get("interpretation", ""),
                    "domain": item.get("domain", ""),
                    "professional_label": definition.get("professional_label", ""),
                    "definition": definition.get("definition", ""),
                    "definition_source": definition.get("definition_source", "catalog"),
                    "parent_translation_focus": definition.get(
                        "parent_translation_focus", ""
                    ),
                    "metric_reference_card": reference_cards.get(
                        _normalize_dimension_name(metric), {}
                    ),
                    "gold_method_references": gold_references.get(metric, []),
                    # Vary the rhetorical entry while preserving the same evidence order.
                    # This prevents 26 blocks from becoming one repeated template.
                    "entry_pattern": DETAIL_ENTRY_PATTERNS[
                        index % len(DETAIL_ENTRY_PATTERNS)
                    ],
                    "writing_contract": {
                        "required_order": [
                            "professional_definition",
                            "source_level_interpretation",
                            "conditional_parent_observation",
                        ],
                        "no_invented_history": True,
                        "no_diagnosis": True,
                        "visible_level_required": True,
                    },
                }
            )
        portrait_blueprint = _build_portrait_blueprint(metric_plans, report_stage)
        return {
            "plan_version": "report_writer_plan_v1",
            "report_stage": report_stage,
            "audience": report_reader_mode(assessment_result),
            "metric_plans": metric_plans,
            "macro_plan": {
                "required_section_ids": list(REQUIRED_SECTION_IDS),
                "suggestion_categories": suggestion_category_order_for_stage(
                    assessment_result
                ),
                "portrait_evidence": {
                    "primary_strengths": [
                        name
                        for cluster in portrait_blueprint["strength_clusters"]
                        for name in cluster["dimensions"]
                    ],
                    "support_priorities": [
                        name
                        for cluster in portrait_blueprint["support_clusters"]
                        for name in cluster["dimensions"]
                    ],
                    "instruction": (
                        "首页只围绕 2-3 个代表性优势和至多 2 个支持维度形成一个成长主题；"
                        "不要罗列全部指标、重复原始分数，或编造学校和家庭事实。"
                    ),
                },
                "portrait_blueprint": portrait_blueprint,
                "gold_section_references": retrieval_result.get(
                    "gold_section_references", []
                ),
            },
        }


def _metric_writer_context(report_stage: str = "elementary") -> str:
    """Keep per-batch calls compact and exclude locally controlled definitions."""
    paths = [
        SKILLS_DIR / "report_text" / "references" / "expert_writing_core.md",
        SKILLS_DIR
        / "report_text"
        / "references"
        / "teacher_annotation_universal_rules.md",
        SKILLS_DIR / "report_text" / "references" / "safety_boundary.md",
    ]
    if report_stage in {"secondary", "junior_high", "senior_high"}:
        paths.extend(
            [
                SKILLS_DIR
                / "report_text"
                / "references"
                / "secondary_school_writing_style.md",
                SKILLS_DIR
                / "report_text"
                / "references"
                / "secondary_school_support_advice.md",
            ]
        )
    else:
        paths.append(
            SKILLS_DIR
            / "report_text"
            / "references"
            / "humanized_parent_style.md"
        )
    return "\n\n".join(load_text(path) for path in paths if path.exists())


def _metric_result_sentence(metric_plan: dict[str, Any]) -> str:
    """Render the score conclusion locally so an LLM cannot alter its level."""
    band = _classify_score_band(metric_plan)
    level = str(metric_plan.get("level", "")).strip()
    rating_basis = str(metric_plan.get("rating_basis", "")).strip()
    if rating_basis == "extreme_score_override" and band == "advantage":
        return "本项得分满分，按本量表规则列为优势区。"

    level_label = {
        "advantage": "优势区",
        "normal": "常态区",
        "potential": "潜力区",
    }.get(band, level or "当前层级")
    if rating_basis in {"class_rank_percentile", "expert_report_gold_reference"}:
        return f"按本次评估的同班参照，本项处于{level_label}。"
    return f"本项指标目前处于{level_label}。"


def _compose_controlled_metric_block(
    metric_plan: dict[str, Any],
    result_analysis: str,
    report_stage: str = "elementary",
) -> str:
    """Assemble definition, calibrated result, and stage-facing result analysis."""
    metric = str(metric_plan.get("dimension_name", "")).strip()
    label = str(metric_plan.get("professional_label", "")).strip()
    definition = _definition_for_report_stage(
        str(metric_plan.get("definition", "")).strip(),
        report_stage,
    )
    analysis = _sanitize_result_analysis(metric_plan, result_analysis)
    if report_stage in SECONDARY_REPORT_STAGES:
        analysis = re.sub(r"儿童|孩子|学生本人", "你", analysis)
        if not _is_secondary_metric_interpretation(analysis):
            analysis = ""
    if not analysis:
        analysis = _fallback_result_analysis(metric_plan, report_stage)
    title = f"【{metric}】"
    if label:
        title += f"{label}："
    return f"{title}{definition}{_metric_result_sentence(metric_plan)}{analysis}"


def _definition_for_report_stage(definition: str, report_stage: str) -> str:
    """Adapt only the person reference; preserve the expert construct meaning."""
    if report_stage not in SECONDARY_REPORT_STAGES:
        return definition
    adapted = re.sub(r"儿童|孩子|学生|个体", "你", definition)
    readability_replacements = (
        (
            "指你为了消除信息盲区，不满足于事物表象，主动寻求深层原因与底层逻辑的内驱力。",
            "指你在信息还不完整时，愿意继续追问原因并寻找解释。",
        ),
        (
            "衡量大脑在规定时间内产生不同观念的数量",
            "衡量你在规定时间内能产生多少种不同想法",
        ),
        (
            "深层原因与底层逻辑的内驱力",
            "原因并寻找更完整解释的动力",
        ),
        (
            "大脑神经信息加工速率与短时记忆编码效率",
            "接收新信息并形成初步记忆的效率",
        ),
        (
            "大脑前额叶对注意力的维持与抗干扰能力",
            "维持注意并抵抗干扰的能力",
        ),
        (
            "作为大脑的高级指挥官",
            "作为任务管理的综合能力",
        ),
        (
            "大脑中枢神经系统的执行唤醒效率",
            "把目标信号转化为行动的效率",
        ),
        (
            "是评估大脑前额叶自我控制功能的核心维度",
            "是理解自我控制和行为节奏的重要维度",
        ),
        (
            "进行多层级因果推演、空间矩阵分析",
            "梳理多步因果关系和空间线索",
        ),
        (
            "在内心的抗衡状态",
            "之间的平衡状态",
        ),
        (
            "体验到纯粹快乐与心流的程度",
            "体验兴趣、投入和完成后满足感的程度",
        ),
        (
            "是驱动你成为终身学习者的最深层内在动力",
            "是支持持续学习的重要动力",
        ),
        (
            "是否发自内心地认同知识探索本身的价值，并能将当下的学业付出与长远的人生目标建立起链接",
            "能否理解学习的价值，并把当下投入与自己的近期目标和未来方向联系起来",
        ),
        (
            "打心底里对自己是否具备克服困难、掌控学习并取得优异成绩的主观正面评估",
            "对自己能否克服困难、掌握学习并取得进步的信心",
        ),
    )
    for source, replacement in readability_replacements:
        adapted = adapted.replace(source, replacement)
    return adapted


SECONDARY_METRIC_RESULT_PROFILES = {
    "表演": (
        "课堂发言、展示或讨论",
        "把观点与情绪清楚呈现出来",
        "清晰表达有助于他人理解你的想法，也能让你在交流中更主动地参与和回应",
        "内容熟悉度、准备时间和听众规模",
    ),
    "文学": (
        "写作、阅读回应或长段表达",
        "组织词句并把想法写得完整连贯",
        "语言组织能力关系到观点能否被准确展开，并支持较复杂内容的理解与表达",
        "材料长度、主题熟悉度和表达时间",
    ),
    "设计": (
        "模型搭建、方案设计或动手改造",
        "把空间设想转化成可见方案",
        "把设想落到结构、材料和功能上，是从创意走向实际解决方案的重要环节",
        "材料限制、空间复杂度和任务目标是否清楚",
    ),
    "科学": (
        "观察现象、实验验证或解释因果",
        "提出猜想并寻找证据",
        "这种探究方式有助于区分直觉与证据，使判断建立在可观察的信息之上",
        "线索是否充分、验证条件是否明确以及问题的开放程度",
    ),
    "社会": (
        "小组协作、活动策划或意见协调",
        "理解不同需要并推动共同方案",
        "兼顾多方观点有助于形成可推进的合作关系，并提升集体任务中的协调质量",
        "角色分工、意见差异和目标是否一致",
    ),
    "兴趣好奇心": (
        "新主题、陌生课程或未接触过的活动",
        "靠近陌生内容并形成初步兴趣",
        "对新事物的兴趣决定了你是否愿意停下来了解，并把短暂注意发展为持续探索",
        "主题与已有经验的联系、进入方式和可获得的反馈",
    ),
    "问题好奇心": (
        "遇到信息缺口或不理解的现象",
        "继续追问原因并查找线索",
        "追问能够把表面疑惑转化为可研究的问题，是深入理解和独立判断的起点",
        "问题线索是否清楚、资料是否可得以及任务是否允许继续追究",
    ),
    "思维流畅性": (
        "开放题、头脑风暴或创意任务",
        "在有限时间内产生多个不同想法",
        "想法数量为后续比较和筛选提供候选空间，也影响开放任务的起步速度",
        "时间压力、题目开放程度和可用信息的多少",
    ),
    "思维灵活性": (
        "原方法受阻、规则改变或观点碰撞",
        "切换角度并尝试新的路径",
        "角度转换有助于摆脱单一路径，在条件变化时重新组织问题与方法",
        "原有方法的熟悉程度、变化幅度和调整时间",
    ),
    "思维独创性": (
        "创作、讨论或问题解决",
        "形成带有个人判断的新颖观点",
        "独特观点能够为常见问题增加新的解释或方案，是形成个人创造表达的重要部分",
        "任务是否允许差异、已有知识储备和对不确定性的容忍度",
    ),
    "思维聚合性": (
        "多线索题目、资料整理或方案选择",
        "抓住重点并筛出更合适的答案",
        "聚合判断帮助你从多个可能中形成结论，使想法能够收束为可继续推进的选择",
        "判断标准是否明确、线索数量和信息之间的冲突程度",
    ),
    "认知灵活性": (
        "任务要求、计划或规则发生变化",
        "调整原有做法并重新进入任务",
        "及时调整有助于减少旧规则的干扰，让注意和行动重新对准当前目标",
        "变化是否突然、规则差异大小和重新准备的时间",
    ),
    "规则抽象能力": (
        "学习新概念、变式题或陌生规则",
        "从例子中提取共同规律",
        "抓住不变关系能够减少对单个例题的依赖，并支持知识迁移到新的情境",
        "例子是否具有代表性、干扰信息多少和概念层级",
    ),
    "学习速度": (
        "首次接触新知识或新指令",
        "抓住关键信息并形成初步理解",
        "较快形成任务框架有助于及时进入练习，把更多精力留给理解和修正",
        "知识陌生度、指令长度和信息呈现方式",
    ),
    "注意稳定性": (
        "阅读、复习或较长的多步骤任务",
        "维持投入并在分心后回到当前目标",
        "稳定注意能够保护连续的信息加工，使较长任务保持思路和进度的一致性",
        "任务时长、环境干扰和目标清晰度",
    ),
    "整体执行功能": (
        "需要规划顺序和持续推进的任务",
        "安排步骤、管理进度并完成收尾",
        "执行组织能力把目标连接到具体行动，关系到多步骤任务能否有序推进并完成",
        "步骤数量、时间限制和任务之间的切换频率",
    ),
    "抑制控制(Nogo)": (
        "等待、暂停或需要抵抗即时冲动的情境",
        "先停一下再判断是否行动",
        "反应抑制帮助你为判断留出空间，是遵守规则、减少冲动失误和管理行为节奏的基础",
        "刺激强度、情绪状态和规则是否明确",
    ),
    "抑制控制(go)": (
        "指令明确、需要及时启动的任务",
        "把目标信号转化为第一步行动",
        "及时启动能够缩短从理解要求到采取行动的距离，使任务推进更连贯",
        "指令复杂度、准备状态和多个任务是否同时出现",
    ),
    "逻辑推理": (
        "阅读论证、解决复杂题目或比较方案",
        "连接条件、因果与结论",
        "逻辑链条有助于检验结论是否成立，也支持对复杂信息作出有依据的判断",
        "条件数量、信息隐含程度和推理步骤的长度",
    ),
    "学习乐趣": (
        "日常学习和自主选择的知识活动",
        "从理解、解决或发现中获得积极体验",
        "学习中的愉悦感会影响主动投入和持续时间，是维持学习动力的重要情绪基础",
        "任务难度、选择空间和反馈是否及时",
    ),
    "学校归属感": (
        "参与班级、课程与校园共同活动",
        "感受到自己与学校环境的联系",
        "归属体验有助于建立参与感和安全感，并支持在集体环境中表达与合作",
        "互动质量、角色清晰度和被接纳的体验",
    ),
    "学习意义感": (
        "面对重复练习或长期学习任务",
        "把当下投入与个人目标建立联系",
        "理解学习为何值得投入，能够为持续努力提供方向，并帮助你在短期困难中保持目标感",
        "目标是否具体、内容与个人经验的联系以及反馈周期",
    ),
    "学习自信感": (
        "新题、难题或不熟悉的任务",
        "相信努力和方法能够带来进步",
        "对自身学习能力的信心会影响是否愿意开始、坚持和在受挫后再次尝试",
        "既往成功经验、任务难度和反馈方式",
    ),
    "积极情绪": (
        "学习、合作或完成任务的过程中",
        "体验兴趣、愉快与投入",
        "积极情绪有助于拓宽注意范围，并为参与、合作和持续学习提供心理能量",
        "活动匹配度、互动氛围和完成感",
    ),
    "负性情绪": (
        "压力、误解或受挫出现时",
        "觉察不愉快情绪并逐步恢复到可行动状态",
        "负性情绪的频率、强度和停留时间会影响注意、判断及恢复后的投入效率",
        "压力强度、支持条件和恢复时间",
    ),
    "情感平衡": (
        "情绪起伏之后重新投入学习和生活",
        "在积极与不愉快体验之间恢复平衡",
        "情绪恢复力关系到你能否在波动后重新组织注意和行动，维持日常节奏",
        "事件影响程度、可获得支持和调整空间",
    ),
}


def _secondary_metric_result_profile(
    metric_plan: dict[str, Any],
) -> tuple[str, str, str, str]:
    metric = _normalize_dimension_name(metric_plan.get("dimension_name", ""))
    for name, profile in SECONDARY_METRIC_RESULT_PROFILES.items():
        normalized_name = _normalize_dimension_name(name)
        if metric == normalized_name or metric.startswith(normalized_name):
            return profile
    label = str(metric_plan.get("professional_label", "")).strip() or "这项能力"
    return (
        "相关学习或实践任务",
        f"调动与“{label}”有关的能力",
        "这项能力会影响你理解要求、组织反应并把想法落实到任务中的方式",
        "任务复杂度、信息量和情境压力",
    )


def _secondary_scene_clause(scene: str) -> str:
    """Turn a metric scene into a fluent Chinese adverbial phrase."""
    scene = scene.strip().rstrip("。；，")
    if scene.endswith(("时", "中", "过程中", "情境下")):
        return scene
    return f"{scene}时"


def _metric_prose_variant(metric_plan: dict[str, Any]) -> int:
    """Choose stable wording variety without making report output random."""
    metric = str(metric_plan.get("dimension_name", ""))
    return sum(ord(char) for char in metric) % 3


def _fallback_result_analysis(
    metric_plan: dict[str, Any],
    report_stage: str = "elementary",
) -> str:
    """Keep the detail page analytical when a model response is unusable."""
    band = _classify_score_band(metric_plan)
    if report_stage in SECONDARY_REPORT_STAGES:
        scene, behavior, meaning, condition = _secondary_metric_result_profile(metric_plan)
        scene_clause = _secondary_scene_clause(scene)
        variant = _metric_prose_variant(metric_plan)
        if band == "advantage":
            templates = (
                (
                    f"在{scene_clause}，你通常能较稳定地{behavior}。"
                    f"{meaning}，也是你目前能够较稳定运用的发展资源。"
                ),
                (
                    f"面对{scene}，{behavior}是你目前较容易调用的能力。"
                    f"{meaning}，这种相对稳定的表现能为更复杂的学习或项目任务提供支撑。"
                ),
                (
                    f"当任务涉及{scene}，你较容易稳定地{behavior}。"
                    f"{meaning}，它已经构成现阶段较清楚的一项能力资源。"
                ),
            )
            return templates[variant]
        if band == "potential":
            templates = (
                (
                    f"在{scene_clause}，你目前还不总能稳定地{behavior}。"
                    f"{condition}发生变化时，这方面的表现可能更容易波动；"
                    f"{meaning}，因此是现阶段较明确的发展关注点。"
                ),
                (
                    f"面对{scene}，你可能需要更清楚的条件，才能较稳定地{behavior}。"
                    f"目前的波动往往与{condition}有关。{meaning}，这部分仍有较明确的发展空间。"
                ),
                (
                    f"当任务要求你{behavior}时，当前表现还会随{condition}而变化。"
                    f"{meaning}，现阶段在不同任务条件下的稳定程度仍有差异。"
                ),
            )
            return templates[variant]
        templates = (
            (
                f"在{scene_clause}，你已经能在一定程度上{behavior}。"
                f"{meaning}；当{condition}变化时，表现可能出现一定波动。"
            ),
            (
                f"面对{scene}，你已有可以依托的基础，通常能够{behavior}。"
                f"{condition}会影响发挥的稳定程度，而{meaning}。"
            ),
            (
                f"在{scene_clause}，{behavior}已经是你能够调用的能力之一。"
                f"{meaning}；目前呈现为正常发展中的稳定基础，突出程度有限，也没有明显受限。"
            ),
        )
        return templates[variant]
    if band == "advantage":
        return "在相关任务中，孩子较容易主动调动这项能力，并把它落实到当前的反应或行动中。这种较稳定的表现能够支持其更有序地完成学习任务和日常互动。"
    if band == "potential":
        return "在相关任务中，孩子的表现可能更受任务复杂度和情境压力影响。把要求拆得更清楚、从较小步骤开始，通常有助于表现逐步稳定。"
    return "在相关任务中，孩子已有可依托的基础；当信息增加、规则变化或要求提高时，表现仍可能随情境而变化。"


def _sanitize_result_analysis(
    metric_plan: dict[str, Any],
    result_analysis: str,
) -> str:
    """Remove factual layers and parent directives from a model analysis response."""
    analysis = re.sub(r"\s+", "", str(result_analysis or "")).strip()
    analysis = re.sub(r"^【[^】]+】", "", analysis).lstrip("：:。")
    if not analysis:
        return ""

    metric = str(metric_plan.get("dimension_name", "")).strip()
    label = str(metric_plan.get("professional_label", "")).strip()
    definition = str(metric_plan.get("definition", "")).strip()
    definition_sentences = [
        re.sub(r"\s+", "", sentence).strip("。！？；")
        for sentence in re.split(r"[。！？；]", definition)
    ]
    definition_sentences = [
        sentence for sentence in definition_sentences if len(sentence) >= 12
    ]
    level_pattern = r"(?:本项|该项|该指标|当前|结合本项).{0,36}(?:优势区|常态区|潜力区)"
    factual_markers = ("得分满分", "按本量表", "按规则", "当前结果", "当前处于")
    kept: list[str] = []
    directive_pattern = r"(?:家长|父母).{0,8}(?:可|可以|不妨|建议|留意|观察)|建议.{0,8}(?:家长|父母)"
    for sentence in re.split(r"(?<=[。！？；])", analysis):
        sentence = sentence.strip()
        if not sentence:
            continue
        repeats_factual_layer = (
            (metric and metric in sentence)
            or (label and label in sentence)
            or any(
                definition_sentence in sentence or sentence in definition_sentence
                for definition_sentence in definition_sentences
            )
            or bool(re.search(level_pattern, sentence))
            or any(marker in sentence for marker in factual_markers)
            or bool(re.search(directive_pattern, sentence))
        )
        if not repeats_factual_layer:
            kept.append(sentence)

    cleaned = "".join(kept).strip()
    # The continuation should be a compact result analysis, not a second report
    # or an instruction list. A malformed long response is safer to replace.
    if len(cleaned) < 18 or len(cleaned) > 140:
        return ""
    return cleaned


def _result_analysis_focus(
    metric_plan: dict[str, Any],
    report_stage: str = "elementary",
) -> str:
    """Expose a scene anchor without cueing the model to address the parent."""
    focus = str(metric_plan.get("parent_translation_focus", "")).strip()
    focus = re.sub(r"(?:家长|父母)(?:可|可以)?(?:留意|观察)?[，,:：]?", "", focus)
    if report_stage in SECONDARY_REPORT_STAGES:
        focus = re.sub(r"儿童|孩子|学生本人", "你", focus)
    return focus.strip("，,:： ")


def _result_analysis_policy(
    metric_plan: dict[str, Any],
    report_stage: str = "elementary",
) -> dict[str, str]:
    """Give each score band a distinct result-analysis job."""
    band = _classify_score_band(metric_plan)
    if report_stage not in SECONDARY_REPORT_STAGES:
        if band == "advantage":
            return {
                "target_length": "80-125 Chinese characters",
                "required": "Describe a stable current strength in relevant tasks, then explain the constructive support it can provide for learning, interaction, or self-management.",
                "forbidden": "Do not append a caveat about becoming weak, delayed, unstable, needing support, or deteriorating under complex, pressured, or distracting conditions unless the assessment input explicitly flags that risk.",
            }
        if band == "potential":
            return {
                "target_length": "65-105 Chinese characters",
                "required": "Describe the current support priority in relevant tasks and explain how clear steps, lower pressure, or practice may help the performance become more stable.",
                "forbidden": "Do not use defect, fixed-trait, diagnostic, or frightening language.",
            }
        return {
            "target_length": "60-100 Chinese characters",
            "required": "Describe the stable current foundation, then explain how performance may vary when task demands, information load, or rules change.",
            "forbidden": "Do not force either a weakness or a prominent strength.",
        }

    if band == "advantage":
        return {
            "target_length": "85-140 Chinese characters",
            "required": "Explain how this stable strength is likely to appear in a metric-specific task, then state its developmental value or what it can support.",
            "forbidden": "Do not add practice steps, advice, time or quantity requirements, review rules, or an automatic weakness caveat.",
        }
    if band == "potential":
        return {
            "target_length": "85-140 Chinese characters",
            "required": "Explain the current performance in a metric-specific task, the conditions that may make it fluctuate, and why the ability matters for development.",
            "forbidden": "Do not use defect, fixed-trait, diagnostic, or frightening language. Do not add exercises, instructions, or action plans.",
        }
    return {
        "target_length": "80-130 Chinese characters",
        "required": "Explain the usable current foundation in a metric-specific task, then describe the task conditions that may affect how steadily it appears.",
        "forbidden": "Do not force either a weakness or a prominent strength. Do not add practice steps, advice, or review rules.",
    }


class MetricWriterAgent:
    """Write independent detail blocks in small batches instead of one huge draft."""

    def __init__(self, client: OpenAI) -> None:
        self.client = client

    def run(self, writing_plan: dict[str, Any]) -> list[dict[str, str]]:
        plans = writing_plan.get("metric_plans", [])
        if not isinstance(plans, list) or not plans:
            return []
        batch_size = max(1, int(os.environ.get("TEXT_AGENT_METRIC_BATCH_SIZE", "6")))
        report_stage = str(writing_plan.get("report_stage", "elementary"))
        blocks: list[dict[str, str]] = []
        for start in range(0, len(plans), batch_size):
            batch = plans[start : start + batch_size]
            blocks.extend(
                self._write_batch(
                    batch,
                    report_stage=report_stage,
                )
            )
        return self._replace_duplicate_analyses(blocks, plans, report_stage)

    @staticmethod
    def _replace_duplicate_analyses(
        blocks: list[dict[str, str]],
        metric_plans: list[dict[str, Any]],
        report_stage: str,
    ) -> list[dict[str, str]]:
        """Replace repeated model prose with metric-specific local fallbacks."""
        plan_by_name = {
            str(item.get("dimension_name", "")).strip(): item
            for item in metric_plans
        }
        seen: set[str] = set()
        normalized_blocks: list[dict[str, str]] = []
        for block in blocks:
            name = str(block.get("dimension_name", "")).strip()
            body = str(block.get("body", "")).strip()
            analysis = _controlled_result_analysis(body)
            fingerprint = _normalized_analysis_fingerprint(analysis)
            if fingerprint and fingerprint in seen and name in plan_by_name:
                fallback = _fallback_result_analysis(plan_by_name[name], report_stage)
                body = _compose_controlled_metric_block(
                    plan_by_name[name],
                    fallback,
                    report_stage,
                )
                analysis = _controlled_result_analysis(body)
                fingerprint = _normalized_analysis_fingerprint(analysis)
            if fingerprint:
                seen.add(fingerprint)
            normalized_blocks.append({"dimension_name": name, "body": body})
        return normalized_blocks

    def _write_batch(
        self,
        metric_plans: list[dict[str, Any]],
        *,
        report_stage: str = "elementary",
    ) -> list[dict[str, str]]:
        expected_names = [str(item.get("dimension_name", "")).strip() for item in metric_plans]
        # The model only needs the result-analysis task. Definitions, visible score
        # conclusions and gold references remain local so it cannot echo them.
        model_metric_plans = [
            {
                "dimension_name": str(item.get("dimension_name", "")).strip(),
                "level": str(item.get("level", "")).strip(),
                "score": item.get("score"),
                "rating_basis": str(item.get("rating_basis", "")).strip(),
                "direction": str(item.get("direction", "")).strip(),
                "result_analysis_focus": _result_analysis_focus(item, report_stage),
                "result_analysis_policy": _result_analysis_policy(
                    item,
                    report_stage,
                ),
                "entry_pattern": str(item.get("entry_pattern", "construct_first")).strip(),
                "gold_method": [
                    reference.get("method_pattern", [])
                    for reference in item.get("gold_method_references", [])
                    if isinstance(reference, dict)
                ][:1],
            }
            for item in metric_plans
        ]
        output_schema = {
            "blocks": [
                {
                    "dimension_name": "",
                    "result_analysis": "",
                }
            ]
        }
        reader_guidance = (
            "The visible report speaks directly to the secondary-school student. "
            "Use natural second-person Chinese with “你”; do not call the reader "
            "“孩子” and do not address parents. Explain likely task meaning in "
            "study, collaboration, inquiry, or self-management."
            if report_stage in SECONDARY_REPORT_STAGES
            else
            "The visible report is parent-facing. Explain the child's likely task "
            "meaning in natural Chinese without turning the paragraph into a parent instruction."
        )
        system_prompt = f"""
You are MetricWriterAgent. Return strict JSON and exactly one Chinese
result_analysis for each requested metric.

Your text is only the final, reader-facing continuation of a locally composed
four-part block. The local system already writes, in this order: a condensed
professional title, an accurate professional definition, and the child's
verified score-level conclusion. Do not repeat, paraphrase, or mention any of
those factual layers.

Reader contract: {reader_guidance}

Write two or three fluent sentences. Follow the supplied result_analysis_policy
exactly, including its target_length, required content, and forbidden content.
        Every metric in this batch must have its own task scene, behavioral meaning, and
        developmental significance. Never reuse an identical sentence or an interchangeable
        score-band template for two different metrics.
This is a
result analysis, not an instruction list: first explain what the verified
        level is likely to look like in the relevant task or interaction, then explain
        its developmental value or a measured condition that affects its expression.
        Use the provided result_analysis_focus only as a
        scene anchor. Match openings to the reader contract; secondary reports normally
use “当你面对……时……”, while elementary reports may use
“在……任务中，孩子更可能……”.

Avoid mechanical AI hinges such as “不是……而是……”, “这提示……”, “这说明……”,
        “一个可操作的起点是……” and repeated “整体来看/本次结果显示”. State the
        task meaning directly. In a secondary report, this indicator block must not
        contain an exercise, action plan, time or quantity requirement, tool, visible
        artifact, review rule, or imperative sentence. All actionable support belongs
        only in the final growth-support suggestions.

Never include: the metric name, a professional label, a professional definition,
score, percentile, 优势区/常态区/潜力区, 本项/该指标/当前结果, headings, Markdown,
or direct parent instructions such as “家长可留意”“家长可以”“建议家长”. Do not
claim an existing habit, school event, relationship, motivation, or personality.
Do not diagnose or make brain, fixed-trait, absolute-praise, frightening, or
unsupported claims.

The supplied focus is an observation direction, not evidence of an existing
experience. The optional gold_method is a structured, non-verbatim retrieval
from an excellent report: use it only to preserve the sequence “score-calibrated
meaning → conditional result analysis”; never copy another child's prose,
activity, relationship, or conclusion. Return only the JSON schema below,
without code fences.

Selected report stage: {report_stage}

{_metric_writer_context(report_stage)}

Output schema:
{compact_json(output_schema)}
""".strip()
        user_prompt = f"""
Write the following result analyses. The score fields are the source of truth.
Expected dimensions, in order: {compact_json(expected_names)}
Metric plans:
{compact_json(model_metric_plans)}
""".strip()
        text = chat_text(
            self.client,
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            json_output=True,
        )
        parsed = parse_json_object(text)
        raw_blocks = parsed.get("blocks", [])
        if not isinstance(raw_blocks, list):
            raise ValueError("MetricWriterAgent returned a non-list blocks field")
        by_name = {
            str(block.get("dimension_name", "")).strip(): str(
                block.get("result_analysis", "")
            ).strip()
            for block in raw_blocks
            if isinstance(block, dict)
        }
        missing = [name for name in expected_names if not by_name.get(name)]
        unexpected = [name for name in by_name if name not in expected_names]
        if missing or unexpected:
            raise ValueError(
                "MetricWriterAgent block contract failed: "
                f"missing={missing}; unexpected={unexpected}"
            )
        normalized_blocks = []
        plan_by_name = {
            str(item.get("dimension_name", "")).strip(): item
            for item in metric_plans
        }
        for name in expected_names:
            body = _compose_controlled_metric_block(
                plan_by_name[name],
                by_name[name],
                report_stage,
            )
            normalized_blocks.append({"dimension_name": name, "body": body})
        return normalized_blocks


def _compose_detail_body(detail_blocks: list[dict[str, str]]) -> str:
    return "\n\n".join(
        str(item.get("body", "")).strip()
        for item in detail_blocks
        if str(item.get("body", "")).strip()
    )


def _inject_detail_blocks(report: str, detail_blocks: list[dict[str, str]]) -> str:
    """Preserve the macro report while making metric coverage deterministic."""
    parsed, _ = parse_report_json(report)
    if parsed is None:
        return report
    sections = parsed.get("sections")
    if not isinstance(sections, list):
        return report
    body = _compose_detail_body(detail_blocks)
    for section in sections:
        if isinstance(section, dict) and section.get("section_id") == "detailed_indicator_analysis":
            section["body"] = body
            evidence = [
                str(item.get("dimension_name", ""))
                for item in detail_blocks
                if str(item.get("dimension_name", ""))
            ]
            section["evidence_used"] = evidence[:5]
            break
    return json.dumps(parsed, ensure_ascii=False, indent=2)


def _compact_retrieval_for_composer(retrieval_result: dict[str, Any]) -> dict[str, Any]:
    """Avoid paying prompt tokens twice for metric-level material already written."""
    return {
        "retrieval_profile": retrieval_result.get("retrieval_profile", {}),
        "retrieved_standard_segments": retrieval_result.get(
            "retrieved_standard_segments", []
        ),
        "gold_section_references": retrieval_result.get("gold_section_references", []),
        "retrieval_summary": retrieval_result.get("retrieval_summary", {}),
    }


class GeneratorAgent:
    def __init__(self, client: OpenAI) -> None:
        self.client = client

    def run(
        self,
        assessment_result: dict[str, Any],
        retrieval_result: dict[str, Any],
        feedback: dict[str, Any] | None = None,
        writing_plan: dict[str, Any] | None = None,
        detail_blocks: list[dict[str, str]] | None = None,
    ) -> str:
        report_stage = resolve_report_stage(assessment_result)
        agent_context = build_runtime_agent_context("generator", assessment_result)
        subject_label = "中学生" if report_stage != "elementary" else "儿童"
        student_facing = report_stage in SECONDARY_REPORT_STAGES
        suggestion_categories = suggestion_category_order_for_stage(assessment_result)
        suggestion_section_title = (
            "成长支持与生涯规划建议"
            if student_facing
            else "成长支持建议"
        )
        visible_reader_contract = (
            "本报告直接写给学生本人。全文以“你”为主要称谓，像一位尊重学生的老师或辅导者在对话；"
            "不得把正文写成给家长的说明信。家长和老师只在支持角色中出现。"
            if student_facing
            else
            "本报告主要写给家长。以“孩子”描述被试，以“您”称呼家长；不要混用学生本人视角。"
        )
        suggestion_field_contract = (
            "兼容字段 parent_suggestions 仍保留。action 写学生自己可执行的动作；"
            "parent_wording 写学生需要协作时可对家长或老师说的一句话；"
            "first_step 写本周即可尝试的一小步。"
            if student_facing
            else
            "action 写家长可采用的支持动作；parent_wording 写家长可使用的话术；"
            "first_step 写家庭可以立即开始的一小步。"
        )

        system_prompt = f"""
你是 GeneratorAgent，职责是生成{subject_label}综合素质评估报告正文。

你的任务边界：
1. 只负责写报告，不负责给自己打分。
2. 必须基于测评 JSON、检索资料和反馈指令写作。
3. 不得编造用户经历，不得做医学诊断。
4. 必须输出合法 JSON 对象，字段应符合 report_text 的 input/output contract；如果被明确要求输出纯正文，再输出正文。
5. 不要写“好的”“以下是报告”等聊天式开场。
6. 不要使用 markdown 分隔线。
7. JSON 字符串内部如需引用短语，只能使用中文引号“”，不要使用未转义的英文双引号。
8. 可见报告文字不要写“心理测评”，优先写“本次评估”“综合素质评估”“发展观察”或“本次结果”。
9. {visible_reader_contract}

{agent_context}
""".strip()

        feedback_text = "无"
        if feedback:
            feedback_text = compact_json(feedback)
        writing_plan_text = compact_json(writing_plan) if writing_plan else "无"
        detail_blocks_text = compact_json(detail_blocks) if detail_blocks else "无"
        composer_retrieval = _compact_retrieval_for_composer(retrieval_result)

        user_prompt = f"""
请根据以下信息生成或修订{subject_label}综合素质评估报告。

确定性学段路由：{report_stage}。小学版是默认值；只有该值不是 elementary 时才使用中学版写作规则。

测评结果 JSON：
{compact_json(assessment_result)}

RetrievalAgent 提供的参考资料：
{compact_json(composer_retrieval)}

FeedbackAgent 提供的修改要求：
{feedback_text}

ReportPlannerAgent 提供的写作计划：
{writing_plan_text}

MetricWriterAgent 已写好的详细指标块：
{detail_blocks_text}

parent_suggestions contract (return exactly these fields for each item):
{compact_json({
  "category": suggestion_categories[0] if suggestion_categories else "",
  "scene": "",
  "data_basis": "指标名 1、指标名 2",
  "action": "",
  "parent_wording": "",
  "first_step": ""
})}

字段语义：{suggestion_field_contract}

报告结构：
- 前言
- 核心成长画像
- 详细指标分析
- {suggestion_section_title}
- 报告说明

输出要求：
- 读者合同：{visible_reader_contract}
- 中学版的 audience 顶层字段写 `student`；小学版写 `parents`。不得由输入中的旧 audience 字段或检索案例改变确定性学段对应的可见读者。
- 每个章节都要能追溯到测评分数、层级、解释或明确背景。
- 必须返回合法 JSON，包含 data_sketch、sections、parent_suggestions、self_check；不要输出 markdown 代码块、注释、尾随逗号或伪 JSON。
- sections 必须且只能使用这 5 个固定 section_id：preface、core_growth_portrait、detailed_indicator_analysis、growth_support_suggestions、boundary_note。
- detailed_indicator_analysis 可以在 body 内用【维度名】分段，但不要拆成 detailed_design、detailed_science 等额外 section_id。
- MetricWriterAgent 提供的详细指标块是唯一权威版本：逐字写入 detailed_indicator_analysis，不得重写其专业解释、层级结论或读者化说明，也不得补充第二套指标块。它已覆盖测评 JSON 中每一个已测指标。
- 完整 JSON 的篇幅预算：详细指标分析不超过 3300 个中文字符；parent_suggestions 固定写 3 条，每个教育场景各 1 条；每个 section 的 evidence_used 只保留 1-5 个最相关指标，不要把 26 项全部重复写入列表。务必在输出上限内完成 sections、parent_suggestions 与 self_check 的所有闭合括号。
- core_growth_portrait 必须逐项执行 writing_plan.macro_plan.portrait_blueprint：用其 selected_evidence 作为唯一画像证据，按 paragraph_jobs 形成“画像主线—优势机制与价值—支持桥梁”，而不是把高低分重新列一遍。evidence_used 必须与 selected_evidence 一致且不超过 5 项。
- 中学版 core_growth_portrait 写 360-500 个中文字符，分成四个短段，完整呈现“画像主线—优势如何共同作用—支持重点出现的任务条件—优势带动与自主复盘原则”。不得因为直接面向学生就缩成几句泛泛鼓励。
- 核心画像中的日常表现只能写成由测评推导出的条件式趋势。除非 respondent_profile 明确提供了背景，不得写“孩子喜欢/经常/能够”“在班里/小组中/学校里”等已经发生的事实。
- section.body 要适合放进 PDF，不要无限铺开；详细建议可放入 parent_suggestions，避免正文和结构化建议大段重复。
- 如果 FeedbackAgent 指出“仅需追加”或“其他部分保持不变”，必须尽量保留当前报告已有章节正文，只修改 fix 指定的部分。
- 如果 RetrievalAgent 提供 retrieved_standard_segments，只能参考其章节组织、表达克制程度和建议写法。
- 详细指标页的专业解释来自量表 Excel“维度详解”的第一完整句，由本地 MetricWriter 直接写入；这不是供你改写的素材。历史范文只可用于学习“结果分析 → 条件式场景解释”的组织方法，不能复制其中孩子经历、夸张修辞或人格判断。
- 中学版详细指标分析只承担结果解读：写清“对应任务中的可能表现 + 发展价值或影响发挥的条件”。不得在指标块中加入练习步骤、时长、数量、工具、产物、复盘规则或命令句；所有行动方案统一放入最后的 parent_suggestions。
- 检索到的历史样例可能保留旧版的夸张比喻、未经解释的神经科学术语或过度断言；这些内容不可照搬。expert_definition_method.md、安全边界和当前评分输入优先于历史样例措辞。
- 不得复制其他孩子的事实、画像、分数结论、家庭/学校经历或原句。
- assessment_metadata.source_student_id 仅是行政编号，只能用于文件与报告识别；不得把编号写进画像、指标分析或建议，更不得据此推断任何特质、经历、分数或背景。
- 输入没有提供具体日常经历。详细指标分析中禁止写“喜欢上学”“与同学老师相处融洽”“经常参加……”等已经发生的事实。小学版改成“当任务需要……时，孩子更可能……”；中学版改成“当你面对……时，你更可能……”。具体活动可以作为建议，但不能伪装成已经发生的经历。
- parent_suggestions 中的 parent_wording/action/first_step 必须是可替换的家庭场景，不得编造“上次、昨天、班里、老师、同学、某次数学题、养过某物”等输入没有提供的具体经历。
- 前言必须明确完成“定位现阶段—认识可用资源—看见可发展方向—选择可验证行动”，不要只说“先呈现整体画像”。
- 写作前做一次自然度检查：删除模板化的“不是……而是……”“这提示/这说明”“按输入的量表解释”“一个可操作的起点是”，减少“资源、成长空间、支持方向、整体来看、综合来看、可以、建议、逐步、安全感、脚手架”等模板词的重复；中学版还要避免每句都以“你可以”开头。少用软性比喻，多写具体行为和场景。
- 每条建议必须包含“触发场景 + 明确动作 + 数量/时间/工具 + 可观察结果 + 复核方式”。只写“加强、培养、多练习、提升能力”属于未完成建议。
- 详细指标块由本地受控流程完成“Excel 专业解释 → 输入校准后的层级结论 → 对应学段的条件式场景说明”。你只需在首页画像、前言、建议和说明中保持相同的专业、温和、非诊断口径；不要在其它章节重复解释每一个指标。
- 不得将单次分数写成“性格里的谨慎”、固定人格、永久动机或长期发展史；改用“现阶段的行为策略、反应风格、互动倾向”等可变化表述。
- 每条 parent_suggestions 必须有 category，且本学段只能使用：{"、".join(suggestion_categories)}。三条建议必须各覆盖一类；确有不适用类别时，在 growth_support_suggestions.risk_flags 说明数据依据。
- 初中版三个方向依次承担不同任务：“自我成长与学习规划”强调目标、方法和复盘；“兴趣探索与项目实践”强调问题意识、真实任务与过程证据；“生涯启发与发展规划”只提出可验证的方向假设和体验活动，不得仅凭测评分数断言“适合某专业/职业”。家长与老师作为资源支持写入卡片内部，不再另设“亲子互动”类别。
- 对每个写入 data_sketch 的维度，必须带 source_level，并逐字复制测评 JSON 的 level；level 字段只能保留同一层级或使用以 source_level 开头的中性表述，绝不能把“较高/top_30”擅自改成“优势区”，或把“中等偏低”擅自改成“潜力区”。
- 未出现在测评 JSON 的指标一律视为未知，不得因为完整量表中存在该指标就补写结论。对“负性情绪”、抑制控制(Nogo)、抑制控制(go)等指标，必须依赖输入 direction 或 interpretation 判断方向；两者缺失时在 risk_flags 标记“缺少层级或方向规则”。
- 若 scale_config.classification_basis 为 class_rank_percentile，则优先沿用输入的 level、rating_basis 与 rank_percentile：不得用原始 score 的 20/60/80、55/70 等数值自行评级。若输入的 rating_basis 为 extreme_score_override，应明确以该满分/有利方向最低分规则为准；若 rating_basis 为 expert_report_gold_reference，必须以专家原报告图表的 level 为准，不得引用本地重算的 rank_percentile；其余指标才可写“按同班参照处于某区间”。
- 对 lower_is_better 指标，direction 只说明“什么方向有利”，而输入的 level 才是当前孩子的最终结论。若输入 level 是潜力区，绝不能因为原始分数看起来较低而写“负担较低、较少受困扰、很少被负性情绪影响”；应写为“当前更需要关注不愉快情绪的出现频率、持续时间与恢复方式”。
- 测评 JSON 的 input_quality.flags 是生成前数据检查结果。若其中列出某一指标，必须遵守该提示：不把它写成确定性区间结论，并在相关 section.risk_flags 中保留相同风险说明。
""".strip()

        text = chat_text(
            self.client,
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            json_output=True,
        )
        report = normalize_cjk_spacing(strip_markdown_code_fence(text))
        report = normalize_report_contract(report, assessment_result)
        report = _normalize_core_portrait_labels(report, assessment_result)
        if detail_blocks:
            report = _inject_detail_blocks(report, detail_blocks)
        return report


class TextAgent(GeneratorAgent):
    """Project-facing name for the report text writer; kept compatible with GeneratorAgent."""


def _contains_any(text: str, terms: list[str]) -> bool:
    return any(term in text for term in terms)


def _contains_positive_term(text: str, terms: list[str]) -> bool:
    return bool(_positive_term_hits(text, terms))


def _positive_term_hits(text: str, terms: list[str]) -> list[str]:
    hits = []
    for term in terms:
        start = 0
        while True:
            index = text.find(term, start)
            if index < 0:
                break
            context = text[max(0, index - 12) : index + len(term) + 2]
            if not _is_negated_or_guardrail_context(context):
                hits.append(term)
                break
            start = index + len(term)
    return hits


def _is_negated_or_guardrail_context(context: str) -> bool:
    guardrails = [
        "不",
        "不是",
        "不要",
        "无需",
        "无须",
        "不能",
        "避免",
        "防止",
        "并非",
        "别",
        "不评价",
        "不追求",
        "不要写成",
    ]
    return any(word in context for word in guardrails)


def _iter_score_items(assessment_result: dict[str, Any]) -> list[dict[str, Any]]:
    scores = assessment_result.get("scores", {})
    items: list[dict[str, Any]] = []

    if isinstance(scores, dict):
        for key, value in scores.items():
            if isinstance(value, dict):
                item = dict(value)
                item.setdefault("key", key)
                item.setdefault("dimension_name", key)
                items.append(item)
            else:
                items.append(
                    {
                        "key": key,
                        "dimension_name": key,
                        "score": value,
                    }
                )
    elif isinstance(scores, list):
        for index, value in enumerate(scores):
            if isinstance(value, dict):
                item = dict(value)
                item.setdefault("key", str(index))
                item.setdefault("dimension_name", item.get("name", str(index)))
                items.append(item)

    return items


def _classify_score_band(item: dict[str, Any]) -> str:
    percentile_band = str(item.get("percentile_band", "")).lower()
    level = str(item.get("level", ""))

    if percentile_band in {"top_30", "top", "high", "advantage"}:
        return "advantage"
    if percentile_band in {"bottom_30", "bottom", "low", "potential"}:
        return "potential"
    if percentile_band in {"middle", "normal"}:
        return "normal"

    if "优势" in level or level in {"高", "较高"}:
        return "advantage"
    if "潜力" in level or "发展" in level or "偏低" in level or level in {"低", "较低"}:
        return "potential"
    if "常态" in level or "中等" in level or "平均" in level:
        return "normal"

    return ""


def _find_dimension_windows(
    report: str,
    names: list[str],
    *,
    window: int = 120,
) -> list[str]:
    windows = []
    seen = set()
    for name in names:
        if not name or len(name) < 2:
            continue

        heading_pattern = re.compile(
            rf"【\s*{re.escape(name)}\s*】(?P<body>.*?)(?=\n【|$)",
            re.DOTALL,
        )
        for match in heading_pattern.finditer(report):
            snippet = f"【{name}】{match.group('body')}".strip()
            if snippet not in seen:
                windows.append(snippet)
                seen.add(snippet)

        if windows:
            continue

        start = 0
        while True:
            index = report.find(name, start)
            if index < 0:
                break
            left = max(0, index - window)
            right = min(len(report), index + len(name) + window)
            snippet = report[left:right]
            if snippet not in seen:
                windows.append(snippet)
                seen.add(snippet)
            start = index + len(name)
    return windows


class RuleChecker:
    inflated_terms = [
        "极其",
        "极度",
        "完美",
        "顶尖",
        "一流",
        "无懈可击",
        "第一梯队",
        "天生的",
        "绝不",
        "必然",
        "疯狂",
        "脑洞大开",
    ]

    potential_inflated_terms = [
        "优势突出",
        "表现卓越",
        "极佳",
        "极强",
        "顶尖",
        "一流",
        "完美",
    ]

    normal_overstated_terms = [
        "优势突出",
        "表现卓越",
        "极佳",
        "极强",
        "顶尖",
        "一流",
        "完美",
    ]

    normal_overnegative_terms = [
        "严重不足",
        "明显落后",
        "很差",
        "问题严重",
        "缺陷",
    ]

    advantage_downplay_terms = [
        "只是中等",
        "中等水平",
        "没有优势",
        "不明显",
        "比较一般",
    ]

    banned_patterns = [
        r"(患有|确诊|诊断为|属于).{0,12}(疾病|障碍|多动|自闭|抑郁|焦虑|智力低下)",
        r"(天生|注定|永远|这辈子).{0,8}(改不了|学不好|如此)",
        r"(危险人格|人格缺陷|品行不端|内心阴暗|懒惰|狡猾)",
    ]

    fixed_trait_attribution_patterns = [
        r"性格里的.{0,12}(谨慎|内向|外向|胆小|敏感|固执)",
        r"(反映|说明|表明).{0,12}(固定性格|人格特质|人格)",
        r"单项.{0,12}(性格|人格)",
    ]

    ai_opening_patterns = [
        r"^好的[，,]",
        r"^以下是",
        r"^当然[，,]",
    ]

    boundary_patterns = [
        r"(不能|无法|不应|不可).{0,8}(替代|代替).{0,12}(专业|诊断|咨询|医疗|医学|评估|建议)",
        r"(不构成|不等同于|不能等同于).{0,12}(诊断|医疗|医学|咨询|治疗|专业建议)",
        r"(仅作|只是).{0,8}(参考|测评参考|状态参考)",
    ]

    sensitive_visible_terms = [
        "心理测评",
    ]

    required_sections = [
        "前言",
        "核心成长画像",
        "详细指标分析",
    ]

    def run(self, report: str, assessment_result: dict[str, Any] | None = None) -> list[str]:
        issues = []
        report_stage = resolve_report_stage(assessment_result)
        student_facing = report_stage in SECONDARY_REPORT_STAGES

        for pattern in self.banned_patterns:
            if re.search(pattern, report):
                issues.append(f"[hard] 命中禁用或诊断化表达：{pattern}")

        for pattern in self.fixed_trait_attribution_patterns:
            if re.search(pattern, report):
                issues.append(
                    "[major] 单次测评分数被归因为固定性格/人格，建议改写为现阶段的行为策略、反应风格或互动倾向："
                    + pattern
                )

        for pattern in self.ai_opening_patterns:
            if re.search(pattern, report.strip()):
                issues.append(f"[minor] 存在聊天式/AI式开场：{pattern}")

        ai_contrast_count = len(
            re.findall(r"不是[^。！？\n]{0,36}而是", report)
        )
        if ai_contrast_count:
            severity = "major" if ai_contrast_count >= 2 else "minor"
            issues.append(
                f"[{severity}] 出现 {ai_contrast_count} 次机械的“不是……而是……”转折；"
                "请直接陈述现阶段表现、任务条件或下一步动作"
            )

        inference_hinge_count = len(re.findall(r"这(?:提示|说明)", report))
        if inference_hinge_count:
            severity = "major" if inference_hinge_count >= 2 else "minor"
            issues.append(
                f"[{severity}] 出现 {inference_hinge_count} 次模板化的“这提示/这说明”；"
                "请把推论改写为具体任务表现或可执行动作"
            )

        if "按输入的量表解释" in report:
            issues.append(
                "[major] 可见正文泄露内部管线措辞“按输入的量表解释”；"
                "固定层级句应写为“本项指标目前处于……”"
            )

        if "一个可操作的起点是" in report:
            issues.append(
                "[minor] 使用了模板化建议句“一个可操作的起点是”；"
                "请直接写明动作、数量/时间和完成结果"
            )

        inflated_hits = _positive_term_hits(report, self.inflated_terms)
        if inflated_hits:
            issues.append(f"[minor] 出现夸张、绝对化或网络化表达：{', '.join(inflated_hits)}")

        sensitive_hits = [
            term for term in self.sensitive_visible_terms if term in report
        ]
        if sensitive_hits:
            issues.append(
                "[minor] 可见报告文字出现易引发家长焦虑的表述，建议改为“本次评估/综合素质评估/发展观察”："
                + ", ".join(sensitive_hits)
            )

        repeated_definition_count = report.count("该维度反映") + report.count("该指标反映")
        if repeated_definition_count >= 4:
            issues.append(
                "[minor] 详细指标分析多次重复“该维度/该指标反映”句式，建议改为“专业界定 + 日常行为翻译”的变化表达"
            )

        has_boundary_note = any(
            re.search(pattern, report) for pattern in self.boundary_patterns
        )
        if not has_boundary_note:
            issues.append("[major] 缺少清晰的非诊断/不能替代专业评估说明")

        if student_facing:
            direct_you_count = len(re.findall(r"你(?:在|会|更|可|能|的|目前|已经|也)", report))
            if direct_you_count < 3:
                issues.append("[major] 中学版没有稳定使用面向学生本人的“你”视角")
            third_person_child_count = len(
                re.findall(r"儿童|孩子|学生本人", report)
            )
            if third_person_child_count:
                issues.append(
                    f"[major] 中学版仍有 {third_person_child_count} 处“儿童/孩子”第三人称；"
                    "可见正文必须统一为面向学生本人的“你”视角"
                )
            if re.search(r"家长您好|家长/老师您好|家长可以这样说", report):
                issues.append("[major] 中学版混入小学家长版的直接称呼或行动话术")
            secondary_academic_terms = (
                "底层逻辑的内驱力",
                "大脑神经信息加工速率",
                "短时记忆编码效率",
                "大脑的高级指挥官",
                "大脑中枢神经系统的执行唤醒效率",
                "多层级因果推演",
                "空间矩阵分析",
                "内心的抗衡状态",
                "终身学习者的最深层内在动力",
            )
            academic_hits = [
                term for term in secondary_academic_terms if term in report
            ]
            if academic_hits:
                severity = "major" if len(academic_hits) >= 2 else "minor"
                issues.append(
                    f"[{severity}] 中学版仍含学生难以直接理解的学术化表达："
                    + "、".join(academic_hits)
                    + "；请保留指标含义，但改写为学习、项目、讨论或情绪恢复中的可理解语言"
                )
        elif "家长" not in report and "父母" not in report and "老师" not in report:
            issues.append("[major] 小学版没有明显面向家长/老师的读者定位")

        if assessment_result and not student_facing:
            audience = str(
                assessment_result.get("audience")
                or assessment_result.get("respondent_profile", {}).get("audience")
                or ""
            ).lower()
            if audience in {"parents", "parent", "家长", "父母"} and re.search(
                r"家长\s*[／/和与、]\s*老师|家长及老师|家长和老师",
                report,
            ):
                issues.append(
                    "[minor] 输入受众为家长，但正文直接称呼了家长/老师，建议只称呼家长"
                )

        required_section_markers = {
            "前言": ("前言", "写在前面", '"section_id": "preface"'),
            "核心成长画像": (
                "核心成长画像",
                "综合画像",
                '"section_id": "core_growth_portrait"',
            ),
            "详细指标分析": (
                "详细指标分析",
                "详细指标解读",
                '"section_id": "detailed_indicator_analysis"',
            ),
        }
        missing_sections = [
            label
            for label, markers in required_section_markers.items()
            if not any(marker in report for marker in markers)
        ]
        if "成长支持" not in report:
            missing_sections.append("成长支持建议")
        if missing_sections:
            issues.append(f"[major] 缺少正式报告结构或等价章节：{', '.join(missing_sections)}")

        if "评价指标" in report or "详细评价" in report:
            issues.append("[minor] 章节命名含“评价”，建议改为“详细指标分析”等低评判感表达")

        if "成长支持" in report:
            advice_keywords = (
                [
                    "自我成长与学习规划",
                    "兴趣探索与项目实践",
                    "生涯启发与发展规划",
                    "方向假设",
                    "体验验证",
                ]
                if student_facing
                else
                [
                    "整体",
                    "总体来看",
                    "综合来看",
                    "支持方向",
                    "分场景",
                    "学习方面",
                    "思维方面",
                    "亲子方面",
                    "交友方面",
                    "生活方面",
                ]
            )
            advice_domain_count = sum(
                1 for keyword in advice_keywords if keyword in report
            )
            if advice_domain_count == 0:
                issues.append("[minor] 成长支持建议缺少整体反馈或分领域建议线索")

        if len(report) < 600:
            issues.append("[minor] 报告长度偏短，可能没有充分展开维度分析和建议")

        if assessment_result:
            issues.extend(self._score_band_issues(report, assessment_result))

        return issues

    def _score_band_issues(
        self,
        report: str,
        assessment_result: dict[str, Any],
    ) -> list[str]:
        issues = []
        for item in _iter_score_items(assessment_result):
            band = _classify_score_band(item)
            if not band:
                continue

            names = [
                str(item.get("dimension_name") or ""),
                str(item.get("key") or ""),
            ]
            windows = _find_dimension_windows(report, names)
            if not windows:
                continue

            combined = "\n".join(windows)
            dimension_name = item.get("dimension_name") or item.get("key")
            direction = str(item.get("direction", "")).strip().lower()
            if direction == "lower_is_better" and band == "potential":
                reversed_direction_terms = [
                    "负担较低",
                    "较少受到",
                    "很少被",
                    "较少被",
                    "不太受",
                ]
                if _contains_any(combined, reversed_direction_terms):
                    issues.append(
                        f"[hard] 方向与层级矛盾：{dimension_name} 的有利方向为低分，但输入结论为潜力区，"
                        "报告不可写成负担较低或较少受困扰"
                    )
            if band == "potential" and _contains_positive_term(
                combined, self.potential_inflated_terms
            ):
                issues.append(
                    f"[hard] 分数层级矛盾：{dimension_name} 为潜力/发展区，但报告局部写得像突出优势"
                )
            elif band == "normal" and _contains_positive_term(
                combined, self.normal_overstated_terms
            ):
                issues.append(
                    f"[major] 分数层级偏高：{dimension_name} 为常态区，但报告局部写得过高"
                )
            elif band == "normal" and _contains_any(combined, self.normal_overnegative_terms):
                issues.append(
                    f"[major] 分数层级偏低：{dimension_name} 为常态区，但报告局部写得过低或过负面"
                )
            elif band == "advantage" and _contains_any(combined, self.advantage_downplay_terms):
                issues.append(
                    f"[major] 分数层级偏低：{dimension_name} 为优势区，但报告局部写成中等或没有优势"
                )

        return issues


class UnsupportedInferenceChecker:
    """Catches common unsupported claims before we have a stronger evidence checker."""

    unsupported_patterns = {
        r"成绩下降": "输入通常只提供测评分数，没有提供真实考试成绩变化",
        r"家庭.*(忽视|控制|打击|不支持)": "输入没有提供家庭互动事实，不能推断家长行为",
        r"父母.*(忽视|控制|打击|不支持)": "输入没有提供父母互动事实，不能推断父母行为",
        r"老师.*(批评|否定|排斥|不喜欢)": "输入没有提供教师行为事实，不能推断老师态度",
        r"(同伴|同学).*(排斥|孤立|欺负)": "输入没有提供同伴关系事实，不能推断同伴事件",
        r"(创伤|病史|疾病史|治疗史)": "输入没有提供创伤、病史或治疗史",
        r"(从小|长期以来).{0,12}(如此|这样|一直)": "输入没有提供长期发展史，不能把一次测评写成长期事实",
    }

    def run(self, report: str) -> list[str]:
        issues = []
        for pattern, reason in self.unsupported_patterns.items():
            if re.search(pattern, report):
                issues.append(f"疑似无依据推断：{pattern}。{reason}")
        return issues


class ScoreCalibrator:
    """Applies deterministic guardrails to LLM checker scores."""

    def __init__(self, rubric: dict[str, Any]) -> None:
        self.rubric = rubric
        self.calibration = rubric.get("calibration", {})
        self.pass_score = get_pass_score(rubric)

    def run(
        self,
        llm_result: dict[str, Any],
        rule_issues: list[str],
        unsupported_issues: list[str],
    ) -> dict[str, Any]:
        result = dict(llm_result)
        minor_issues = list(result.get("minor_issues", []))
        major_issues = list(result.get("major_issues", []))
        hard_failures = list(result.get("hard_failures", []))
        contract_errors = _stringify_issue_list(result.get("contract_errors", []))
        fabrication_risks = _stringify_issue_list(result.get("fabrication_risks", []))

        if contract_errors:
            major_issues.extend(f"结构契约问题：{item}" for item in contract_errors)
        if fabrication_risks:
            major_issues.extend(f"疑似编造经历：{item}" for item in fabrication_risks)

        false_positive_text = "\n".join(
            issue for issue in minor_issues + major_issues if "规则误报" in issue
        )
        if rule_issues:
            for issue in rule_issues:
                severity, message = _split_rule_issue(issue)
                if issue in false_positive_text or message in false_positive_text:
                    continue
                if severity == "hard":
                    hard_failures.append(f"规则检查：{message}")
                elif severity == "major":
                    major_issues.append(f"规则检查：{message}")
                else:
                    minor_issues.append(f"规则检查提示：{message}")

        if unsupported_issues:
            major_issues.extend(unsupported_issues)

        total_score = int(result.get("total_score", 0))
        no_gold_max = int(self.calibration.get("no_gold_reference_max_score", 94))
        minor_max = int(self.calibration.get("minor_issue_max_score", 92))
        major_max = int(self.calibration.get("major_issue_max_score", 79))
        hard_failure_max = int(self.calibration.get("hard_failure_max_score", 69))

        if total_score >= 100:
            minor_issues.append("评分校准：未经过人工审核或黄金样例对照时，不应给满分")
            total_score = no_gold_max

        if minor_issues:
            total_score = min(total_score, minor_max)

        if major_issues:
            total_score = min(total_score, major_max)

        if hard_failures:
            total_score = min(total_score, hard_failure_max)

        result["minor_issues"] = _dedupe(minor_issues)
        result["major_issues"] = _dedupe(major_issues)
        result["hard_failures"] = _dedupe(hard_failures)
        result["contract_errors"] = _dedupe(contract_errors)
        result["fabrication_risks"] = _dedupe(fabrication_risks)
        result["total_score"] = total_score
        result["pass"] = (
            bool(result.get("pass"))
            and total_score >= self.pass_score
            and not result["hard_failures"]
            and not result["major_issues"]
        )

        if not result["pass"] and not result.get("revision_instructions"):
            result["revision_instructions"] = [
                "删除或改写无依据推断，只保留输入 JSON 中有分数、等级或解释支持的内容",
                "把宽泛判断改成“测评结果提示”“可能意味着”等更谨慎表达",
            ]

        return result


def _dedupe(items: list[str]) -> list[str]:
    seen = set()
    result = []
    for item in items:
        if item not in seen:
            result.append(item)
            seen.add(item)
    return result


def _stringify_issue_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []

    items = []
    for item in value:
        if isinstance(item, str):
            items.append(item)
        elif isinstance(item, dict):
            items.append(compact_json(item))
        else:
            items.append(str(item))
    return items


def _split_rule_issue(issue: str) -> tuple[str, str]:
    for severity in ("hard", "major", "minor"):
        prefix = f"[{severity}] "
        if issue.startswith(prefix):
            return severity, issue[len(prefix):]
    return "minor", issue


class CheckerAgent:
    def __init__(self, client: OpenAI) -> None:
        self.client = client
        self.rubric = load_report_rubric()
        self.rule_checker = RuleChecker()
        self.unsupported_checker = UnsupportedInferenceChecker()
        self.score_calibrator = ScoreCalibrator(self.rubric)

    def run(
        self,
        assessment_result: dict[str, Any],
        report: str,
    ) -> dict[str, Any]:
        report_check_text = extract_report_check_text(report)
        contract_issues = run_output_contract_checks(report, assessment_result)
        rule_issues = contract_issues + self.rule_checker.run(
            report_check_text,
            assessment_result,
        )
        unsupported_issues = self.unsupported_checker.run(report_check_text)
        llm_result = self._run_llm_check(assessment_result, report, rule_issues)
        calibrated_result = self.score_calibrator.run(
            llm_result=llm_result,
            rule_issues=rule_issues,
            unsupported_issues=unsupported_issues,
        )
        return {
            "rule_issues": rule_issues,
            "unsupported_issues": unsupported_issues,
            "llm_result": calibrated_result,
            "raw_llm_result": llm_result,
        }

    def passed(self, check_result: dict[str, Any]) -> bool:
        llm_result = check_result.get("llm_result", {})
        return (
            bool(llm_result.get("pass"))
            and int(llm_result.get("total_score", 0)) >= get_pass_score(self.rubric)
            and not llm_result.get("hard_failures")
        )

    def _run_llm_check(
        self,
        assessment_result: dict[str, Any],
        report: str,
        rule_issues: list[str],
    ) -> dict[str, Any]:
        report_stage = resolve_report_stage(assessment_result)
        checker_context = build_runtime_agent_context("checker", assessment_result)
        subject_label = "中学生" if report_stage != "elementary" else "儿童"
        expected_suggestion_categories = suggestion_category_order_for_stage(
            assessment_result
        )
        reader_check = (
            "本报告必须直接面向学生本人：主要称谓为“你”，建议由学生拥有行动，"
            "家长和老师只提供结构、信息、反馈或情绪支持。出现家长信口吻、"
            "幼儿化奖励或成人全程监督，应写入 audience_errors。"
            if report_stage in SECONDARY_REPORT_STAGES
            else
            "本报告必须主要面向家长：以“孩子”描述被试，并提供家长可执行的支持动作。"
        )
        score_schema = build_score_schema(self.rubric)
        output_schema = {
            "pass": True,
            "total_score": 0,
            "scores": score_schema,
            "hard_failures": [],
            "major_issues": [],
            "minor_issues": [],
            "score_band_errors": [],
            "evidence_gaps": [],
            "structure_errors": [],
            "contract_errors": [],
            "fabrication_risks": [],
            "audience_errors": [],
            "revision_instructions": [],
            "needs_human_review": False,
        }
        rubric_prompt = format_rubric_for_prompt(self.rubric)

        system_prompt = f"""
你是 CheckerAgent，职责是严格检查{subject_label}综合素质评估报告质量。你不负责改写报告。

你必须依据测评 JSON、报告正文、规则检查结果和评分标准判断。
如果规则检查结果非空，你必须逐条判断：
- 如果是真问题，写入 major_issues 或 minor_issues，并扣分。
- 如果规则检查结果以 [hard] 开头，除非能明确证明是误报，否则必须写入 hard_failures。
- 如果规则检查结果以 [major] 开头，除非能明确证明是误报，否则必须写入 major_issues。
- 如果是误报，在 minor_issues 中说明“规则误报：原因”。

你必须严格使用下面的外置评分配置，不要自行创造新的评分维度。
你必须重点检查：分数层级是否写偏、是否符合本学段读者合同、是否有前言和边界说明、建议是否来自前文数据。
本次读者合同：{reader_check}
你还必须检查 TextAgent 输出是否能稳定进入 renderer/API：合法 JSON、固定 section_id、parent_suggestions 字段完整。
你还必须检查：每个输入中已测指标是否都有独立的【指标名】解读块，并具备“专业界定 + 对应学段的通俗解释”两层；是否把单项分数归因为固定性格；当建议不少于三条时，是否严格按本学段三类组织：{"、".join(expected_suggestion_categories)}。
若为中学版，还要检查生涯建议是否只是有数据依据、可通过课程/项目/访谈/体验验证的方向假设；把测评分数直接写成“适合某专业、应该报考或未来会从事某职业”必须列为 major_issues。
如果 scale_config.classification_basis 是 class_rank_percentile，还必须检查报告是否忠实沿用输入的班级排名评级，且没有把原始 score 当作 20/60/80 或 55/70 的评级阈值。
你还必须逐项核对 data_sketch：source_level 是否逐字复制输入 level，level 是否擅自加强或贬低。若输入没有本量表版本的层级/方向规则，报告不得把原始分数写成确定性“优势区/常态区/潜力区”。
如果家长话术或建议把输入没有提供的过去经历写成真实事件，必须写入 fabrication_risks，并要求改成可替换场景。
核心成长画像必须是一段有主线的画像论证，而不是指标清单：检查它是否说明优势之间的联系、优势的发展价值，以及优势如何成为支持待发展能力的起点。输入未提供背景时，画像中任何“孩子喜欢/经常/能够”“在班里/小组中/学校里”的事实断言都必须写入 fabrication_risks。
还要执行最新教师逐句批注：前言是否明确说明报告能帮助读者定位现阶段、认识资源、看见发展方向并选择行动；正文是否反复使用“不是……而是……”“这提示/这说明”或“按输入的量表解释”等机械句式。中学版详细指标只负责解释当前表现、发展含义和影响条件；若混入训练步骤、时长、工具或命令句，必须列入 major_issues。最终三条成长建议才负责行动方案，并必须写清触发场景、动作、数量/时间/工具、可观察产物和复核信号；缺少第一步、完成产物或判断标准，或者只写“加强/培养/多练习/继续探索”，必须列入 major_issues。

{rubric_prompt}

输出必须是合法 JSON，不要输出 markdown。

JSON 格式必须是：
{compact_json(output_schema)}

{checker_context}
""".strip()

        user_prompt = f"""
请检查下面这份{subject_label}综合素质评估报告。

确定性学段路由：{report_stage}。不得用其他学段的案例标准覆盖本次规则。

测评结果 JSON：
{compact_json(assessment_result)}

规则检查结果：
{compact_json(rule_issues)}

报告正文：
{report}
""".strip()

        text = chat_text(
            self.client,
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            json_output=True,
        )
        return parse_json_object(text)


class FeedbackAgent:
    def __init__(self, client: OpenAI) -> None:
        self.client = client

    def run(
        self,
        assessment_result: dict[str, Any],
        report: str,
        check_result: dict[str, Any],
    ) -> dict[str, Any]:
        report_stage = resolve_report_stage(assessment_result)
        feedback_context = build_runtime_agent_context("feedback", assessment_result)
        stage_revision_rule = (
            "Use conditional student-facing wording with “你”. Keep detailed metric "
            "analysis interpretive and advice-free; preserve student-owned actions and "
            "adult support boundaries only in the final growth-support suggestions."
            if report_stage in SECONDARY_REPORT_STAGES
            else
            "Use conditional parent-observation wording and parent-owned support actions."
        )

        system_prompt = f"""
Every fix must name a section_id or dimension. Never request a full-report rewrite.
Do not suggest invented history as a way to make the report vivid. {stage_revision_rule}
你是 FeedbackAgent，职责是把检查结果转化为 GeneratorAgent 可执行的修改指令。

本次确定性学段路由为 {report_stage}；修改指令必须保持该学段的语言和建议结构。

你不直接重写完整报告，只输出结构化反馈 JSON。
反馈必须具体、可执行，避免“更自然一点”这种空泛要求。

输出必须是合法 JSON，不要输出 markdown。

JSON 格式必须是：
{{
  "revision_goal": "",
  "priority": "major",
  "keep": [],
  "fix": [
    {{
      "section_id": "",
      "dimension": "",
      "problem": "",
      "instruction": "",
      "evidence_to_use": []
    }}
  ],
  "avoid": [],
  "rag_guidance": {{
    "use_retrieved_segments": true,
    "preferred_section_types": [],
    "do_not_copy_case_facts": true
  }},
  "specific_instructions": []
}}

{feedback_context}
""".strip()

        user_prompt = f"""
请根据检查结果，为 GeneratorAgent 生成下一轮改写指令。
优先把 hard_failures、major_issues、分数层级不匹配、无依据推断、结构缺失和建议空泛转成具体 fix 项。
如果问题涉及某个章节或维度，必须写入 section_id 或 dimension。
如果本轮可使用本地标准报告 RAG，请在 rag_guidance.preferred_section_types 中列出适合参考的章节类型。

测评结果 JSON：
{compact_json(assessment_result)}

当前报告：
{report}

CheckerAgent 检查结果：
{compact_json(check_result)}
""".strip()

        text = chat_text(
            self.client,
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            json_output=True,
        )
        return enrich_feedback_targets(
            parse_json_object(text),
            assessment_result,
            check_result,
        )


def _feedback_issue_entries(
    check_result: dict[str, Any],
) -> list[tuple[str, str, str]]:
    llm_result = check_result.get("llm_result", {})
    if not isinstance(llm_result, dict):
        llm_result = {}
    fields = (
        ("hard", "hard_failures"),
        ("major", "major_issues"),
        ("major", "score_band_errors"),
        ("major", "fabrication_risks"),
        ("major", "audience_errors"),
        ("major", "contract_errors"),
        ("major", "structure_errors"),
        ("major", "evidence_gaps"),
    )
    entries: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for severity, key in fields:
        for issue in _stringify_issue_list(llm_result.get(key, [])):
            normalized = issue.strip()
            if normalized and normalized not in seen:
                entries.append((severity, key, normalized))
                seen.add(normalized)

    for issue in _stringify_issue_list(check_result.get("rule_issues", [])):
        severity, message = _split_rule_issue(issue)
        if severity not in {"hard", "major"}:
            continue
        normalized = message.strip()
        if normalized and normalized not in seen:
            entries.append((severity, "rule_issues", normalized))
            seen.add(normalized)

    for issue in _stringify_issue_list(check_result.get("unsupported_issues", [])):
        normalized = issue.strip()
        if normalized and normalized not in seen:
            entries.append(("major", "unsupported_issues", normalized))
            seen.add(normalized)
    return entries


def _feedback_target_for_issue(
    issue: str,
    known_dimensions: list[str],
) -> tuple[str, list[str]]:
    dimensions = [
        dimension
        for dimension in sorted(known_dimensions, key=len, reverse=True)
        if dimension and dimension in issue
    ]
    if dimensions:
        return "detailed_indicator_analysis", dimensions

    if re.search(r"建议|parent_suggestions|学习与日常|课外与探索|亲子互动|自我成长|项目实践|生涯", issue):
        return "growth_support_suggestions", []
    if re.search(r"核心|画像|综合画像|整体画像|core_growth_portrait", issue):
        return "core_growth_portrait", []
    if re.search(r"前言|称呼|您好|开场|sections\[preface\]", issue):
        return "preface", []
    if re.search(r"边界|报告说明|医学诊断|疾病|治疗|咨询", issue):
        return "boundary_note", []
    if re.search(r"指标|专业界定|结果分析|层级|分数|优势区|常态区|潜力区|解读块|重复", issue):
        return "detailed_indicator_analysis", []
    if re.search(r"读者|口吻|面向家长|面向学生|第二人称|第三人称", issue):
        return "core_growth_portrait", []
    return "core_growth_portrait", []


def _feedback_instruction(source: str, issue: str) -> str:
    if source == "score_band_errors" or re.search(r"层级|优势区|常态区|潜力区|分数", issue):
        return (
            "逐字沿用输入 JSON 的原始分数和等级；按固定常模与计分方向改正结果分析，"
            "不得自行升高、降低或模糊等级。"
        )
    if source in {"fabrication_risks", "unsupported_issues"}:
        return (
            "删除输入未提供的既往经历和确定性行为断言；只保留测评支持的能力解释，"
            "把生活场景改成“在……时可留意/可以尝试”的条件化表达。"
        )
    if source == "audience_errors":
        return (
            "按本次确定性学段路由重写称谓、行动主体和支持边界；"
            "小学版面向家长，中学版直接面向学生本人。"
        )
    if source in {"contract_errors", "structure_errors"}:
        return (
            "恢复固定 section_id、指标标题和建议字段，补齐缺失内容；"
            "只修改指定章节，不改变其他已通过部分。"
        )
    if source == "evidence_gaps":
        return (
            "让每个结论紧邻对应的分数、等级或指标定义，并说明这一结果在相应学段"
            "可能呈现的具体方式；不要用泛化套话代替证据。"
        )
    if re.search(r"机械|模板化|不是……而是|这提示|这说明|按输入的量表解释", issue):
        return (
            "删除被点名的机械连接句，直接陈述现阶段位置、任务表现或下一步动作；"
            "不得用另一句“整体来看/这说明”替换。"
        )
    if re.search(r"指标.*(?:混入|包含).*行动建议|详细指标.*(?:只解释|结果解读)", issue):
        return (
            "删除该指标块中的练习步骤、时长、工具、产物和命令句；"
            "只补充当前层级在该指标特有任务中的可能表现、发展价值以及影响发挥的条件。"
            "具体行动不得留在详细指标页，应由成长支持建议统一承接。"
        )
    if re.search(
        r"概念性建议|概念层面|first_step|第一步|具体动作|可观察|复核信号",
        issue,
    ):
        return (
            "把建议改成“触发场景 + 明确动作 + 数量/时间/工具 + 可观察结果 + "
            "复核方式”，确保读者今天或本周就能执行。"
        )
    return (
        "针对该检查问题做局部改写，保留已通过内容；改写后再次核对事实依据、"
        "学段口吻、指标差异和结构契约。"
    )


def enrich_feedback_targets(
    feedback: dict[str, Any],
    assessment_result: dict[str, Any],
    check_result: dict[str, Any],
) -> dict[str, Any]:
    """Guarantee that unresolved checker findings produce patchable targets."""
    result = dict(feedback) if isinstance(feedback, dict) else {}
    fixes = [
        dict(item)
        for item in result.get("fix", [])
        if isinstance(item, dict)
    ]
    scores = assessment_result.get("scores", {})
    known_dimensions = (
        [str(name).strip() for name in scores if str(name).strip()]
        if isinstance(scores, dict)
        else []
    )
    existing_targets = {
        (
            str(item.get("section_id", "")).strip(),
            str(item.get("dimension", "")).strip(),
        )
        for item in fixes
    }
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    highest_priority = str(result.get("priority") or "major")

    for severity, source, issue in _feedback_issue_entries(check_result):
        if severity == "hard":
            highest_priority = "hard"
        section_id, dimensions = _feedback_target_for_issue(issue, known_dimensions)
        target_dimensions = dimensions or [""]
        for dimension in target_dimensions:
            key = (section_id, dimension)
            if key in existing_targets:
                continue
            entry = grouped.setdefault(
                key,
                {
                    "section_id": section_id,
                    "dimension": dimension,
                    "problem_parts": [],
                    "instruction_parts": [],
                    "evidence_to_use": [],
                },
            )
            if issue not in entry["problem_parts"]:
                entry["problem_parts"].append(issue)
            instruction = _feedback_instruction(source, issue)
            if instruction not in entry["instruction_parts"]:
                entry["instruction_parts"].append(instruction)
            evidence = (
                f"输入 JSON 中“{dimension}”的原始分数、等级和指标定义"
                if dimension
                else "输入 JSON 中的已测分数、等级和已知背景"
            )
            if evidence not in entry["evidence_to_use"]:
                entry["evidence_to_use"].append(evidence)

    for entry in grouped.values():
        fixes.append(
            {
                "section_id": entry["section_id"],
                "dimension": entry["dimension"],
                "problem": "；".join(entry["problem_parts"]),
                "instruction": " ".join(entry["instruction_parts"]),
                "evidence_to_use": entry["evidence_to_use"],
            }
        )

    result["priority"] = highest_priority
    result["fix"] = fixes
    if not str(result.get("revision_goal", "")).strip():
        result["revision_goal"] = "逐项解决未通过检查的问题，同时保留已经合格的章节。"
    result["keep"] = list(result.get("keep", []))
    result["avoid"] = _dedupe(
        [
            *[str(item) for item in result.get("avoid", [])],
            "整份报告推倒重写",
            "编造被试经历或把测评分数写成固定性格",
            "混用小学版和中学版的称谓与建议结构",
        ]
    )
    rag_guidance = result.get("rag_guidance", {})
    if not isinstance(rag_guidance, dict):
        rag_guidance = {}
    rag_guidance["use_retrieved_segments"] = True
    rag_guidance["do_not_copy_case_facts"] = True
    rag_guidance.setdefault("preferred_section_types", [])
    result["rag_guidance"] = rag_guidance
    result["specific_instructions"] = _dedupe(
        [
            *[str(item) for item in result.get("specific_instructions", [])],
            "修改完成后逐项对照 CheckerAgent 的未解决问题，不得只做同义改写。",
            "每个被点名指标必须保留独立、非重复的结果分析。",
        ]
    )
    return result


def _section_body(report_json: dict[str, Any], section_id: str) -> str:
    sections = report_json.get("sections", [])
    if not isinstance(sections, list):
        return ""
    for section in sections:
        if isinstance(section, dict) and section.get("section_id") == section_id:
            return str(section.get("body", ""))
    return ""


def _replace_detail_block(body: str, dimension_name: str, replacement: str) -> str:
    heading = re.escape(dimension_name.strip())
    pattern = re.compile(
        rf"【\s*{heading}\s*】.*?(?=\n\s*【|\Z)",
        re.DOTALL,
    )
    if not pattern.search(body):
        # A missing heading is a recoverable coverage gap, not a reason to lose
        # the full report. Append the exact target so the next checker can verify it.
        return body.rstrip() + "\n\n" + replacement.strip()
    return pattern.sub(replacement.strip(), body, count=1)


def apply_targeted_patch(report: str, patch: dict[str, Any]) -> str:
    """Apply only allow-listed report fragments and retain the original contract."""
    parsed, error = parse_report_json(report)
    if parsed is None:
        raise ValueError(f"Cannot patch invalid report JSON: {error}")
    sections = parsed.get("sections")
    if not isinstance(sections, list):
        raise ValueError("Cannot patch a report without sections")
    section_by_id = {
        str(section.get("section_id", "")): section
        for section in sections
        if isinstance(section, dict)
    }

    allowed_section_ids = {
        "preface",
        "core_growth_portrait",
        "detailed_indicator_analysis",
        "growth_support_suggestions",
        "boundary_note",
    }
    for item in patch.get("section_bodies", []):
        if not isinstance(item, dict):
            continue
        section_id = str(item.get("section_id", "")).strip()
        body = str(item.get("body", "")).strip()
        if section_id not in allowed_section_ids or not body:
            continue
        if section_id not in section_by_id:
            raise ValueError(f"Patch target section does not exist: {section_id}")
        section_by_id[section_id]["body"] = body

    detail_section = section_by_id.get("detailed_indicator_analysis")
    if detail_section is not None:
        detail_body = str(detail_section.get("body", ""))
        for item in patch.get("detail_blocks", []):
            if not isinstance(item, dict):
                continue
            dimension_name = str(item.get("dimension_name", "")).strip()
            body = str(item.get("body", "")).strip()
            if not dimension_name or not body:
                continue
            required_heading = f"【{dimension_name}】"
            if not body.startswith(required_heading):
                body = required_heading + body
            detail_body = _replace_detail_block(detail_body, dimension_name, body)
        detail_section["body"] = detail_body

    suggestions = patch.get("parent_suggestions")
    if isinstance(suggestions, list) and suggestions:
        parsed["parent_suggestions"] = suggestions
    return json.dumps(parsed, ensure_ascii=False, indent=2)


class ReportPatchAgent:
    """Repair selected report paths instead of asking the model to rewrite a report."""

    def __init__(self, client: OpenAI) -> None:
        self.client = client

    def run(
        self,
        assessment_result: dict[str, Any],
        report: str,
        writing_plan: dict[str, Any],
        feedback: dict[str, Any],
    ) -> str:
        parsed, error = parse_report_json(report)
        if parsed is None:
            raise ValueError(f"Cannot patch invalid report JSON: {error}")
        report_stage = resolve_report_stage(assessment_result)
        patch_context = build_runtime_agent_context("feedback", assessment_result)
        reader_rule = (
            "This is a student-facing secondary-school report. Address the student as “你”, "
            "keep actions student-owned, and treat family/teachers as optional support."
            if report_stage in SECONDARY_REPORT_STAGES
            else
            "This is an elementary parent report. Describe the child conditionally and give "
            "parents observable, practical support actions."
        )
        targets = self._targets_from_feedback(feedback, writing_plan)
        if not targets["sections"] and not targets["dimensions"]:
            return report
        expected_suggestion_categories = suggestion_category_order_for_stage(
            assessment_result
        )
        repairing_suggestions = "growth_support_suggestions" in targets["sections"]

        fragments = {
            "sections": [
                {
                    "section_id": section_id,
                    "body": _section_body(parsed, section_id),
                }
                for section_id in targets["sections"]
            ],
            "detail_blocks": [
                {
                    "dimension_name": dimension,
                    "body": self._detail_fragment(parsed, dimension),
                }
                for dimension in targets["dimensions"]
            ],
        }
        if "growth_support_suggestions" in targets["sections"]:
            fragments["parent_suggestions"] = parsed.get("parent_suggestions", [])
        target_plans = [
            item
            for item in writing_plan.get("metric_plans", [])
            if item.get("dimension_name") in targets["dimensions"]
        ]
        output_schema = {
            "section_bodies": [{"section_id": "", "body": ""}],
            "detail_blocks": [{"dimension_name": "", "body": ""}],
            "parent_suggestions": [],
        }
        suggestion_repair_contract = ""
        if repairing_suggestions:
            suggestion_repair_contract = f"""
The growth-support target is structurally mandatory. Return exactly three
parent_suggestions in this category order:
{compact_json(expected_suggestion_categories)}
Every item must contain non-empty category, scene, data_basis, action,
parent_wording, and first_step fields. Each item must use a different category.
Keep the advice tied to named assessment indicators. Write a concrete trigger,
action, quantity/time/tool, observable result, and review rule. Do not invent
past events. parent_wording is still required for the full two-page fallback,
even when the compact PDF layout may hide it.
""".strip()
        system_prompt = f"""
You are ReportPatchAgent. Repair only the requested fragments of a Chinese assessment report.
Never output a full report. Return strict JSON matching this schema:
{compact_json(output_schema)}

Deterministic stage route: {report_stage}. {reader_rule}
Keep every claim tied to the assessment input. Do not invent a child's past event,
relationship, preference, or response. A detail replacement must start with the exact
heading 【指标名】 and use professional definition -> supplied level -> stage-appropriate
conditional interpretation. Different indicators must not receive identical result analysis.
For an advantage result, explain its stable developmental value without adding an obligatory
weakness. For a normal result, describe the available foundation and realistic fluctuation.
For a potential result, describe supportable development space without labeling the student.
Only return section IDs and dimensions supplied in the target fragments. Omit fields that need no change.

{suggestion_repair_contract}

{patch_context}
""".strip()
        user_prompt = f"""
Assessment input:
{compact_json(assessment_result)}

Target writing plans:
{compact_json(target_plans)}

Checker feedback:
{compact_json(feedback)}

Only these fragments may change:
{compact_json(fragments)}
""".strip()
        text = chat_text(
            self.client,
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            json_output=True,
        )
        patch_payload = parse_json_object(text)
        if repairing_suggestions:
            repaired_suggestions = patch_payload.get("parent_suggestions")
            if not isinstance(repaired_suggestions, list) or len(repaired_suggestions) != 3:
                raise ValueError(
                    "Suggestion patch must return exactly three parent_suggestions"
                )
            repaired_categories = [
                str(item.get("category", "")).strip()
                for item in repaired_suggestions
                if isinstance(item, dict)
            ]
            if repaired_categories != expected_suggestion_categories:
                raise ValueError(
                    "Suggestion patch categories must match the stage-specific order"
                )
            for index, item in enumerate(repaired_suggestions):
                if not isinstance(item, dict):
                    raise ValueError(f"parent_suggestions[{index}] must be an object")
                missing = [
                    key
                    for key in REQUIRED_PARENT_SUGGESTION_KEYS
                    if not str(item.get(key, "")).strip()
                ]
                if missing:
                    raise ValueError(
                        f"parent_suggestions[{index}] is missing: {', '.join(missing)}"
                    )
        return apply_targeted_patch(report, patch_payload)

    def _targets_from_feedback(
        self,
        feedback: dict[str, Any],
        writing_plan: dict[str, Any],
    ) -> dict[str, list[str]]:
        sections: list[str] = []
        dimensions: list[str] = []
        allowed_sections = set(REQUIRED_SECTION_IDS)
        known_dimensions = {
            str(item.get("dimension_name", "")).strip()
            for item in writing_plan.get("metric_plans", [])
            if isinstance(item, dict) and str(item.get("dimension_name", "")).strip()
        }
        for item in feedback.get("fix", []):
            if not isinstance(item, dict):
                continue
            section_id = str(item.get("section_id", "")).strip()
            dimension = str(item.get("dimension", "")).strip()
            suggestion_target = (
                section_id.startswith("parent_suggestions")
                or dimension.startswith("parent_suggestions")
            )
            if suggestion_target:
                section_id = "growth_support_suggestions"
                dimension = ""
            if section_id in allowed_sections and section_id not in sections:
                sections.append(section_id)
            if dimension in known_dimensions and dimension not in dimensions:
                dimensions.append(dimension)
        return {"sections": sections, "dimensions": dimensions}

    def _detail_fragment(self, report_json: dict[str, Any], dimension_name: str) -> str:
        body = _section_body(report_json, "detailed_indicator_analysis")
        heading = re.escape(dimension_name.strip())
        match = re.search(rf"【\s*{heading}\s*】.*?(?=\n\s*【|\Z)", body, re.DOTALL)
        return match.group(0).strip() if match else ""


class ReportOrchestrator:
    def __init__(
        self,
        client: OpenAI,
        max_rounds: int = 2,
        quality_target_score: int | None = None,
        polish_minor_issues: bool = False,
    ) -> None:
        self.retrieval_agent = RetrievalAgent()
        self.planner_agent = ReportPlannerAgent()
        self.metric_writer_agent = MetricWriterAgent(client)
        self.generator_agent = TextAgent(client)
        self.checker_agent = CheckerAgent(client)
        self.feedback_agent = FeedbackAgent(client)
        self.patch_agent = ReportPatchAgent(client)
        self.max_rounds = max_rounds
        self.quality_target_score = quality_target_score
        self.polish_minor_issues = polish_minor_issues

    def _needs_quality_polish(self, check_result: dict[str, Any]) -> bool:
        llm_result = check_result.get("llm_result", {})
        total_score = int(llm_result.get("total_score", 0))
        minor_issues = llm_result.get("minor_issues", [])
        if self.quality_target_score is not None and total_score < self.quality_target_score:
            return True
        return self.polish_minor_issues and bool(minor_issues)

    def _graph_runner(self):
        from report_pipeline.graph import GraphDeps
        from report_pipeline.runner import GraphReportOrchestrator

        return GraphReportOrchestrator(
            GraphDeps(
                normalize_assessment=normalize_assessment_result,
                retrieval_agent=self.retrieval_agent,
                planner_agent=self.planner_agent,
                metric_writer_agent=self.metric_writer_agent,
                generator_agent=self.generator_agent,
                checker_agent=self.checker_agent,
                feedback_agent=self.feedback_agent,
                patch_agent=self.patch_agent,
                needs_quality_polish=self._needs_quality_polish,
                transient_errors=(
                    APIConnectionError,
                    APITimeoutError,
                    InternalServerError,
                    RateLimitError,
                    httpx.HTTPError,
                ),
                max_rounds=self.max_rounds,
            )
        )

    def run(self, assessment_result: dict[str, Any]) -> dict[str, Any]:
        impl = os.environ.get("REPORT_ORCHESTRATOR_IMPL", "legacy").strip().lower()
        if impl == "langgraph":
            return self._graph_runner().run(assessment_result)
        if impl != "legacy":
            raise ValueError(
                "REPORT_ORCHESTRATOR_IMPL must be 'legacy' or 'langgraph', "
                f"got {impl!r}"
            )
        return self._run_legacy(assessment_result)

    def _run_legacy(self, assessment_result: dict[str, Any]) -> dict[str, Any]:
        assessment_result = normalize_assessment_result(assessment_result)
        retrieval_result = self.retrieval_agent.run(assessment_result)
        writing_plan = self.planner_agent.run(assessment_result, retrieval_result)
        retrieval_result["writing_plan"] = writing_plan
        iterations = []
        feedback = None
        final_report = ""
        final_check: dict[str, Any] = {}
        approved_candidate: dict[str, Any] | None = None
        detail_blocks: list[dict[str, str]] | None = None

        for round_index in range(1, self.max_rounds + 1):
            repair_mode = "initial_generation" if round_index == 1 else "targeted_patch"
            repair_note = ""
            try:
                if round_index == 1:
                    detail_blocks = self.metric_writer_agent.run(writing_plan)
                    report = self.generator_agent.run(
                        assessment_result=assessment_result,
                        retrieval_result=retrieval_result,
                        writing_plan=writing_plan,
                        detail_blocks=detail_blocks,
                    )
                else:
                    try:
                        report = self.patch_agent.run(
                            assessment_result=assessment_result,
                            report=final_report,
                            writing_plan=writing_plan,
                            feedback=feedback or {},
                        )
                    except ValueError as exc:
                        # A malformed model patch must not terminate a batch. Recompose
                        # once with the same targeted feedback while reinjecting the
                        # controlled metric blocks, then let CheckerAgent judge it.
                        repair_mode = "targeted_recompose_fallback"
                        repair_note = f"{type(exc).__name__}: {exc}"
                        report = self.generator_agent.run(
                            assessment_result=assessment_result,
                            retrieval_result=retrieval_result,
                            feedback=feedback or {},
                            writing_plan=writing_plan,
                            detail_blocks=detail_blocks,
                        )
                check_result = self.checker_agent.run(assessment_result, report)
            except (
                APIConnectionError,
                APITimeoutError,
                InternalServerError,
                RateLimitError,
                httpx.HTTPError,
            ) as exc:
                iterations.append(
                    {
                        "round": round_index,
                        "passed": False,
                        "runtime_error": f"{type(exc).__name__}: {exc}",
                    }
                )
                if approved_candidate is not None:
                    break
                raise
            passed = self.checker_agent.passed(check_result)

            iteration: dict[str, Any] = {
                "round": round_index,
                "report": report,
                "check_result": check_result,
                "passed": passed,
                "repair_mode": repair_mode,
            }
            if repair_note:
                iteration["repair_note"] = repair_note

            final_report = report
            final_check = check_result

            if passed:
                # A later polish pass must never discard an already approved report.
                # The first approved artifact remains the delivery fallback if a rewrite
                # regresses on structure, safety, or an upstream API response.
                approved_candidate = {
                    "report": report,
                    "check": check_result,
                    "round": round_index,
                }
                needs_polish = self._needs_quality_polish(check_result)
                iteration["needs_quality_polish"] = needs_polish
                if not needs_polish or round_index >= self.max_rounds:
                    iterations.append(iteration)
                    return {
                        "status": "approved",
                        "retrieval_result": retrieval_result,
                        "iterations": iterations,
                        "final_report": final_report,
                        "final_check": final_check,
                    }

                try:
                    feedback = self.feedback_agent.run(
                        assessment_result=assessment_result,
                        report=report,
                        check_result=check_result,
                    )
                except (
                    APIConnectionError,
                    APITimeoutError,
                    InternalServerError,
                    RateLimitError,
                    httpx.HTTPError,
                ) as exc:
                    iteration["polish_runtime_error"] = (
                        f"{type(exc).__name__}: {exc}"
                    )
                    iterations.append(iteration)
                    break
                iteration["feedback"] = feedback
                iteration["polish_reason"] = "passed_but_below_quality_target_or_has_minor_issues"
                iterations.append(iteration)
                continue

            if round_index < self.max_rounds:
                feedback = self.feedback_agent.run(
                    assessment_result=assessment_result,
                    report=report,
                    check_result=check_result,
                )
                iteration["feedback"] = feedback

            iterations.append(iteration)

        if approved_candidate is not None:
            return {
                "status": "approved",
                "retrieval_result": retrieval_result,
                "iterations": iterations,
                "final_report": approved_candidate["report"],
                "final_check": approved_candidate["check"],
                "approval_note": (
                    "A later optional polish round was not approved; "
                    f"retained the approved report from round {approved_candidate['round']}."
                ),
            }

        return {
            "status": "needs_human_review",
            "retrieval_result": retrieval_result,
            "iterations": iterations,
            "final_report": final_report,
            "final_check": final_check,
        }
