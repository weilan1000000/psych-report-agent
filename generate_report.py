# -*- coding: utf-8 -*-
"""LEGACY PROTOTYPE: one-shot text generation, not the production report pipeline.

Use scripts/generate_full_pdf_report.py for production-equivalent local runs.
"""
import json
import os
import sys
from pathlib import Path

from openai import OpenAI

from agent_context import build_agent_context


MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
DEFAULT_INPUT_PATH = Path(__file__).with_name("sample_assessment.json")


def require_api_key() -> str:
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise RuntimeError(
            "没有找到 DEEPSEEK_API_KEY。请先在 PowerShell 中运行："
            '$env:DEEPSEEK_API_KEY="你的新APIKey"'
        )
    return api_key


def load_assessment_result(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"找不到测评 JSON 文件：{path}")

    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def build_messages(result: dict) -> list[dict[str, str]]:
    result_json = json.dumps(result, ensure_ascii=False, indent=2)
    agent_context = build_agent_context(
        skill_names=["report_writer", "safety_boundary"],
        memory_names=["style_guide", "scale_knowledge"],
    )

    system_prompt = """
你是一名心理测评报告写作助手，负责把结构化测评结果改写成自然、温和、专业的中文报告。

必须遵守：
1. 只能基于输入中的分数、等级和解释写作，不能编造用户经历。
2. 本报告只能作为心理测评结果解释，不能写成医学诊断。
3. 不使用“你患有”“你一定”“严重疾病”等诊断化、绝对化表达。
4. 语言要像专业人员写给真实用户，避免“首先、其次、综上所述”等模板感。
5. 建议要具体、可执行，不要只写“保持积极心态”。
6. 可以温和指出风险，但不要制造恐慌。
7. 直接输出报告正文，不要写“好的”“以下是报告”等开场白。
8. 不要使用 markdown 分隔线。

你还必须遵守下面的 Agent 上下文：
{agent_context}
""".strip()
    system_prompt = system_prompt.format(agent_context=agent_context)

    user_prompt = f"""
请根据下面的心理测评结果，生成一份中文心理测评报告。

报告结构：
- 总体印象：用一段话概括主要状态。
- 维度分析：分别解释压力、焦虑、睡眠三个维度。
- 可能的相互影响：说明这些维度之间可能如何互相影响。
- 调整建议：给出 3 条具体、可执行的建议。
- 边界说明：说明本报告仅作测评参考，不能替代专业诊断。

测评结果 JSON：
{result_json}
""".strip()

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def main() -> None:
    input_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_INPUT_PATH
    assessment_result = load_assessment_result(input_path)

    client = OpenAI(
        api_key=require_api_key(),
        base_url="https://api.deepseek.com",
    )

    response = client.chat.completions.create(
        model=MODEL,
        messages=build_messages(assessment_result),
        stream=False,
    )

    print(response.choices[0].message.content)


if __name__ == "__main__":
    main()
