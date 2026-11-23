import os
from openai import OpenAI

api_key = os.environ.get("DEEPSEEK_API_KEY")

if not api_key:
    raise RuntimeError("没有找到 DEEPSEEK_API_KEY，请先在 PowerShell 设置环境变量。")

client = OpenAI(
    api_key=api_key,
    base_url="https://api.deepseek.com"
)

response = client.chat.completions.create(
    model=os.environ.get("DEEPSEEK_MODEL", "deepseek-chat"),
    messages=[
        {
            "role": "system",
            "content": "你是一名专业、温和、谨慎的心理测评报告写作助手。"
        },
        {
            "role": "user",
            "content": "请用自然、不像AI模板的中文，简短解释这个测评结果：压力分数78，焦虑分数62，睡眠分数55。"
        }
    ],
    stream=False
)

print(response.choices[0].message.content)
