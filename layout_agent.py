# -*- coding: utf-8 -*-
"""EXPERIMENTAL: single-page LayoutAgent prototype.

It is retained for layout research. It does not consume the current TextAgent
final_report.json and is not the production-equivalent PDF entry point.
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from openai import OpenAI


ROOT_DIR = Path(__file__).resolve().parent
DEFAULT_ASSESSMENT_PATH = ROOT_DIR / "sample_assessment.json"
DEFAULT_OUTPUT_DIR = ROOT_DIR / "output" / "deepseek_demo"
LAYOUT_OUTPUT_NAME = "deepseek_layout.json"
MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(value, file, ensure_ascii=False, indent=2)


def require_api_key() -> str:
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise RuntimeError(
            "没有找到 DEEPSEEK_API_KEY。请先在 PowerShell 中运行："
            '$env:DEEPSEEK_API_KEY="你的DeepSeek API Key"'
        )
    return api_key


def load_available_themes() -> list[dict[str, Any]]:
    themes_dir = ROOT_DIR / "config" / "themes"
    themes = []
    for path in sorted(themes_dir.glob("*.json")):
        theme = read_json(path)
        themes.append(
            {
                "name": theme["name"],
                "label": theme.get("label", theme["name"]),
                "best_for": theme.get("best_for", []),
            }
        )
    return themes


def build_context() -> str:
    skill_names = ["layout_designer", "chart_designer", "pdf_style_guide"]
    sections = []
    for name in skill_names:
        sections.append(f"# {name}\n{read_text(ROOT_DIR / 'skills' / f'{name}.md')}")
    return "\n\n".join(sections)


def build_messages(assessment: dict[str, Any]) -> list[dict[str, str]]:
    assessment_json = json.dumps(assessment, ensure_ascii=False, indent=2)
    themes_json = json.dumps(load_available_themes(), ensure_ascii=False, indent=2)
    context = build_context()

    system_prompt = f"""
你是 LayoutAgent，负责把本地心理测评 JSON 转换成可渲染的 PDF 页面 layout JSON。

你不直接输出 HTML，也不直接生成 PDF。你的输出会被本地 renderer/render_layout.js 读取。

你必须遵守：
1. 只输出合法 JSON，不要输出 markdown，不要解释。
2. 当前只生成一页 demo，page_type 固定为 "dimension_detail"。
3. layout 必须适配“一页一个主题、上方图表、下方文字解释”的排版。
4. chart.type 当前只能使用 "horizontal_bar"。
5. text_blocks 必须是 3 个，每个包含 type、title、body。
6. 文字要简洁，避免单页拥挤，每个 body 建议 45-80 个中文字符。
7. 不得输出医学诊断，不得编造用户经历。
8. 根据 report_type 选择合适主题；如果你不确定，可以只设置 report_type，让 ThemeAgent 自动选择。

可用 report_type / theme 参考：
{themes_json}

排版技能上下文：
{context}
""".strip()

    schema_example = {
        "document_title": "情绪与压力状态测评报告",
        "report_type": "emotion_stress",
        "page": {
            "page_type": "dimension_detail",
            "title": "压力与恢复",
            "subtitle": "STRESS AND RECOVERY PROFILE",
            "section_badge": "状态概览：本页聚焦压力、焦虑和睡眠恢复之间的相互影响。",
        },
        "chart": {
            "type": "horizontal_bar",
            "title": "情绪压力维度表现",
            "x_max": 100,
            "series": [
                {"label": "压力感", "score": 78, "reference": 50, "highlight": True},
                {"label": "焦虑感", "score": 62, "reference": 50},
                {"label": "睡眠恢复", "score": 55, "reference": 60},
            ],
            "legend": [
                {"label": "参考水平", "color": "green"},
                {"label": "当前得分", "color": "green_dark"},
            ],
        },
        "text_blocks": [
            {
                "type": "highlight_bullet",
                "title": "压力感 —— 当前最突出",
                "body": "测评结果提示，近期主观负荷感较明显，需要优先关注恢复节奏。",
            }
        ],
        "footer": {"band": True},
    }

    user_prompt = f"""
请根据下面的本地测评 JSON，生成一份 demo PDF 页面所需的 layout JSON。

要求：
- 根据量表名称和内容选择 report_type。
- 把 scores 中的维度转成 chart.series。
- 如果缺少参考值，reference 使用 50 或 60 这类中性参考值即可。
- 找出最需要强调的维度，将 highlight 设为 true。
- text_blocks 写 3 个解释块：突出维度、相互影响、调整方向。
- 输出结构必须与示例一致。

layout JSON 示例：
{json.dumps(schema_example, ensure_ascii=False, indent=2)}

本地测评 JSON：
{assessment_json}
""".strip()

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def parse_json_object(text: str) -> dict[str, Any]:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(0))


def generate_layout(assessment: dict[str, Any]) -> dict[str, Any]:
    client = OpenAI(api_key=require_api_key(), base_url=BASE_URL)
    response = client.chat.completions.create(
        model=MODEL,
        messages=build_messages(assessment),
        response_format={"type": "json_object"},
        stream=False,
    )
    layout = parse_json_object(response.choices[0].message.content)
    return normalize_layout(layout, assessment)


def normalize_layout(layout: dict[str, Any], assessment: dict[str, Any]) -> dict[str, Any]:
    layout.setdefault("document_title", assessment.get("scale_name", "心理测评报告"))
    layout.setdefault("report_type", infer_report_type(assessment))
    layout.setdefault("footer", {"band": True})

    page = layout.setdefault("page", {})
    page.setdefault("page_type", "dimension_detail")
    page.setdefault("title", "测评结果概览")
    page.setdefault("subtitle", "ASSESSMENT PROFILE")
    page.setdefault("section_badge", "状态概览：本页展示主要维度表现与解释。")

    chart = layout.setdefault("chart", {})
    chart.setdefault("type", "horizontal_bar")
    chart.setdefault("title", "主要维度表现")
    chart.setdefault("x_max", 100)
    chart.setdefault(
        "legend",
        [
            {"label": "参考水平", "color": "green"},
            {"label": "当前得分", "color": "green_dark"},
        ],
    )
    if not chart.get("series"):
        chart["series"] = build_series_from_assessment(assessment)

    for item in chart["series"]:
        item.setdefault("reference", 50)
        item["score"] = coerce_number(item.get("score", 0))
        item["reference"] = coerce_number(item.get("reference", 50))

    if not any(item.get("highlight") for item in chart["series"]):
        max_item = max(chart["series"], key=lambda item: item.get("score", 0), default=None)
        if max_item:
            max_item["highlight"] = True

    blocks = layout.setdefault("text_blocks", [])
    blocks[:] = blocks[:3]
    while len(blocks) < 3:
        blocks.append(
            {
                "type": "highlight_bullet",
                "title": "解释补充",
                "body": "本页内容基于测评结果生成，用于辅助理解当前状态，不替代专业判断。",
            }
        )
    for block in blocks:
        block.setdefault("type", "highlight_bullet")
        block.setdefault("title", "解释")
        block.setdefault("body", "本段用于解释图表结果。")

    return layout


def infer_report_type(assessment: dict[str, Any]) -> str:
    text = json.dumps(assessment, ensure_ascii=False)
    if any(keyword in text for keyword in ["压力", "焦虑", "睡眠", "情绪"]):
        return "emotion_stress"
    if any(keyword in text for keyword in ["个性", "人格", "职业"]):
        return "personality"
    if any(keyword in text for keyword in ["认知", "注意", "记忆"]):
        return "cognitive_growth"
    if any(keyword in text for keyword in ["创新", "高阶思维", "青少年"]):
        return "youth_innovation"
    return "emotion_stress"


def build_series_from_assessment(assessment: dict[str, Any]) -> list[dict[str, Any]]:
    series = []
    for key, value in assessment.get("scores", {}).items():
        label = {
            "stress": "压力感",
            "anxiety": "焦虑感",
            "sleep": "睡眠恢复",
        }.get(key, key)
        series.append(
            {
                "label": label,
                "score": coerce_number(value.get("score", 0)),
                "reference": 50,
            }
        )
    return series or [{"label": "综合状态", "score": 60, "reference": 50, "highlight": True}]


def coerce_number(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0
    return int(number) if number.is_integer() else number


def render_pdf(layout_path: Path, output_dir: Path) -> None:
    command = [
        "node",
        str(ROOT_DIR / "renderer" / "render_layout.js"),
        str(layout_path),
        str(output_dir),
    ]
    subprocess.run(command, cwd=ROOT_DIR, check=True)


def main() -> None:
    assessment_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_ASSESSMENT_PATH
    output_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    assessment = read_json(assessment_path)
    layout = generate_layout(assessment)
    layout_path = output_dir / LAYOUT_OUTPUT_NAME
    write_json(layout_path, layout)
    render_pdf(layout_path, output_dir)

    print(json.dumps({
        "assessment_path": str(assessment_path),
        "layout_path": str(layout_path),
        "output_dir": str(output_dir),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
