from __future__ import annotations

import hashlib
import re
from typing import Any

from .models.issues import QualityIssue


ISSUE_SOURCES: tuple[tuple[str, str, str, bool], ...] = (
    ("hard_failures", "safety_or_blocker", "blocker", False),
    ("score_band_errors", "score_band", "major", True),
    ("fabrication_risks", "fabrication_risk", "major", True),
    ("audience_errors", "audience", "major", True),
    ("contract_errors", "output_contract", "major", True),
    ("structure_errors", "structure", "major", True),
    ("evidence_gaps", "evidence_gap", "major", True),
    ("major_issues", "other_major", "major", True),
    ("minor_issues", "writing_quality", "minor", True),
    ("rule_issues", "rule_check", "major", True),
    ("unsupported_issues", "unsupported_claim", "major", True),
)

CATEGORY_PRIORITY = {
    "safety_or_blocker": 100,
    "fabrication_risk": 90,
    "score_band": 85,
    "unsupported_claim": 80,
    "audience": 75,
    "output_contract": 70,
    "structure": 65,
    "evidence_gap": 60,
    "writing_quality": 40,
    "other_major": 30,
    "rule_check": 20,
}
SEVERITY_PRIORITY = {"notice": 0, "minor": 1, "major": 2, "blocker": 3}

SECTION_CUES = {
    "综合画像": "core_portrait",
    "核心画像": "core_portrait",
    "详细指标": "detailed_indicator_analysis",
    "指标解读": "detailed_indicator_analysis",
    "结果分析": "detailed_indicator_analysis",
    "成长支持": "growth_support_suggestions",
    "成长建议": "growth_support_suggestions",
    "报告结束语": "closing_note",
}

PREFIXES = (
    "[hard] ",
    "[major] ",
    "[minor] ",
    "规则检查：",
    "疑似编造经历：",
    "结构契约问题：",
)


def _text(value: Any) -> str:
    if value in (None, ""):
        return ""
    if isinstance(value, list):
        return "；".join(filter(None, (_text(item) for item in value)))
    if isinstance(value, dict):
        return "；".join(
            f"{key}: {_text(item)}" for key, item in value.items() if item not in (None, "", [])
        )
    return str(value).strip()


def _problem_text(value: Any) -> str:
    if isinstance(value, dict):
        for key in ("problem", "issue", "message", "description", "text"):
            text = _text(value.get(key))
            if text:
                return text
    return _text(value)


def _identity(text: str) -> str:
    value = re.sub(r"\s+", " ", text).strip()
    for prefix in PREFIXES:
        value = value.removeprefix(prefix).strip()
    return value.rstrip("。；; ")


def _issue_id(identity: str) -> str:
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:12]
    return f"qi_{digest}"


def _metric_from(value: Any, problem: str) -> str:
    if isinstance(value, dict):
        for key in ("metric", "dimension", "dimension_name", "indicator"):
            text = _text(value.get(key))
            if text:
                return text
    match = re.search(r"【\s*([^】]{1,40})\s*】", problem)
    return match.group(1).strip() if match else ""


def _section_from(value: Any, problem: str) -> str:
    if isinstance(value, dict):
        explicit = _text(value.get("section_id") or value.get("section"))
        if explicit:
            return explicit
    for cue, section_id in SECTION_CUES.items():
        if cue in problem:
            return section_id
    return ""


def _severity(source: str, default: str, problem: str) -> str:
    lowered = problem.lower()
    if source == "rule_issues":
        if lowered.startswith("[hard]"):
            return "blocker"
        if lowered.startswith("[minor]"):
            return "minor"
    return default


def _category(source: str, default: str, problem: str) -> str:
    text = problem.lower()
    if source in {"major_issues", "rule_issues"}:
        if any(cue in text for cue in ("编造", "未提供的经历", "无依据事实", "fabricat")):
            return "fabrication_risk"
        if any(cue in text for cue in ("分数", "等级", "常模", "优势区", "潜力区")):
            return "score_band"
        if any(cue in text for cue in ("小学版", "初中版", "家长口吻", "学生口吻", "读者")):
            return "audience"
    return default


def _raw_items(check_result: dict[str, Any], source: str) -> list[Any]:
    llm_result = check_result.get("llm_result", {})
    llm_result = llm_result if isinstance(llm_result, dict) else {}
    value = check_result.get(source) if source in {"rule_issues", "unsupported_issues"} else llm_result.get(source)
    return value if isinstance(value, list) else []


def normalize_check_issues(check_result: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert legacy Checker lists into deterministic, deduplicated issue objects."""

    merged: dict[str, QualityIssue] = {}
    order: list[str] = []
    for source, default_category, default_severity, default_fixable in ISSUE_SOURCES:
        for raw in _raw_items(check_result, source):
            problem = _problem_text(raw)
            identity = _identity(problem)
            if not identity:
                continue
            key = identity.casefold()
            category = _category(source, default_category, problem)
            severity = _severity(source, default_severity, problem)
            if key not in merged:
                raw_dict = raw if isinstance(raw, dict) else {}
                merged[key] = QualityIssue(
                    issue_id=_issue_id(identity),
                    severity=severity,
                    category=category,
                    sources=[source],
                    section_id=_section_from(raw, problem),
                    metric=_metric_from(raw, problem),
                    problem=identity,
                    current_excerpt=_text(raw_dict.get("current_excerpt") or raw_dict.get("excerpt")),
                    evidence=_text(raw_dict.get("evidence") or raw_dict.get("evidence_to_use")),
                    expected=_text(raw_dict.get("expected") or raw_dict.get("expected_behavior")),
                    fix_instruction=_text(
                        raw_dict.get("fix_instruction")
                        or raw_dict.get("instruction")
                        or raw_dict.get("revision_instruction")
                    ),
                    confidence=float(raw_dict.get("confidence", 0.0) or 0.0),
                    auto_fixable=bool(raw_dict.get("auto_fixable", default_fixable)),
                    raw_text=_text(raw),
                )
                order.append(key)
                continue
            issue = merged[key]
            if source not in issue.sources:
                issue.sources.append(source)
            if CATEGORY_PRIORITY.get(category, 0) > CATEGORY_PRIORITY.get(issue.category, 0):
                issue.category = category
            if SEVERITY_PRIORITY.get(severity, 0) > SEVERITY_PRIORITY.get(issue.severity, 0):
                issue.severity = severity  # type: ignore[assignment]
            issue.auto_fixable = issue.auto_fixable and default_fixable
    return [merged[key].model_dump() for key in order]
