"""Human-readable quality review summaries for generated reports."""

from __future__ import annotations

from html import escape
from typing import Any

from report_pipeline.quality_issues import normalize_check_issues


ISSUE_GROUPS = (
    (
        "hard_failures",
        "阻断问题",
        "danger",
        "报告暂时不能交付。请先核对安全边界、输入数据或结构完整性，再重新生成。",
    ),
    (
        "score_band_errors",
        "分数与等级",
        "warning",
        "请对照原始分数和固定常模，确认等级、方向及文字解释一致。",
    ),
    (
        "fabrication_risks",
        "无依据事实",
        "warning",
        "删除输入 JSON 未提供的经历或表现，把它们改成条件化的观察提示。",
    ),
    (
        "audience_errors",
        "读者与语气",
        "warning",
        "确认小学版面向家长、中学版面向学生本人，避免两套口吻混用。",
    ),
    (
        "contract_errors",
        "输出结构",
        "warning",
        "检查缺失章节、字段或指标标题；结构不完整时应重新生成。",
    ),
    (
        "structure_errors",
        "内容组织",
        "warning",
        "调整章节组织、指标覆盖或建议分类，使报告满足固定模板。",
    ),
    (
        "evidence_gaps",
        "证据不足",
        "warning",
        "补充与测评分数或已知背景的对应关系，不要用泛化结论替代结果分析。",
    ),
    (
        "major_issues",
        "其他主要问题",
        "danger",
        "这些问题会影响报告准确性或可读性，需要修正后重新检查。",
    ),
    (
        "minor_issues",
        "文字优化",
        "notice",
        "这些问题通常不涉及事实错误，可在人工抽查时做语言润色。",
    ),
)


def _string_items(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        if isinstance(item, str):
            text = item.strip()
        elif isinstance(item, dict):
            text = "；".join(
                f"{key}: {value}" for key, value in item.items() if value not in ("", None, [])
            )
        else:
            text = str(item).strip()
        if text and text not in result:
            result.append(text)
    return result


def _issue_identity(value: str) -> str:
    text = value.strip()
    for prefix in (
        "[hard] ",
        "[major] ",
        "[minor] ",
        "规则检查：",
        "疑似编造经历：",
        "结构契约问题：",
    ):
        text = text.removeprefix(prefix).strip()
    return text


def _round_history(iterations: Any) -> list[dict[str, Any]]:
    if not isinstance(iterations, list):
        return []
    result: list[dict[str, Any]] = []
    for index, item in enumerate(iterations, start=1):
        if not isinstance(item, dict):
            continue
        check = item.get("check_result", {})
        llm_result = check.get("llm_result", {}) if isinstance(check, dict) else {}
        result.append(
            {
                "round": int(item.get("round", index)),
                "score": int(llm_result.get("total_score", 0) or 0),
                "passed": bool(item.get("passed")),
                "feedback_generated": isinstance(item.get("feedback"), dict),
                "repair_mode": str(item.get("repair_mode") or ""),
                "repair_note": str(item.get("repair_note") or ""),
                "major_issue_count": len(_string_items(llm_result.get("major_issues"))),
                "hard_failure_count": len(_string_items(llm_result.get("hard_failures"))),
            }
        )
    return result


def build_quality_review(
    result: dict[str, Any],
    *,
    target_score: int,
    review_draft_rendered: bool = False,
) -> dict[str, Any]:
    """Translate CheckerAgent output into an actionable colleague-facing report."""
    status = str(result.get("status") or "needs_human_review")
    check_result = result.get("final_check", {})
    if not isinstance(check_result, dict):
        check_result = {}
    llm_result = check_result.get("llm_result", {})
    if not isinstance(llm_result, dict):
        llm_result = {}
    normalized_issues = normalize_check_issues(check_result)

    groups: list[dict[str, Any]] = []
    seen: set[str] = set()
    for key, title, tone, action in ISSUE_GROUPS:
        items = []
        for item in _string_items(llm_result.get(key)):
            normalized = _issue_identity(item)
            if normalized in seen:
                continue
            seen.add(normalized)
            items.append(item)
        if items:
            groups.append(
                {
                    "key": key,
                    "title": title,
                    "tone": tone,
                    "count": len(items),
                    "items": items,
                    "action": action,
                }
            )

    rule_items = []
    for item in _string_items(check_result.get("rule_issues")):
        normalized = _issue_identity(item)
        if normalized not in seen:
            seen.add(normalized)
            rule_items.append(item)
    if rule_items:
        groups.append(
            {
                "key": "rule_issues",
                "title": "规则检查提示",
                "tone": "notice",
                "count": len(rule_items),
                "items": rule_items,
                "action": "按提示定位到对应章节或指标，确认是实际问题还是规则误报。",
            }
        )

    score = int(llm_result.get("total_score", 0) or 0)
    hard_count = len(_string_items(llm_result.get("hard_failures")))
    major_count = len(_string_items(llm_result.get("major_issues")))
    passed = status == "approved"
    requires_human_review = not passed
    history = _round_history(result.get("iterations"))
    feedback_rounds = sum(1 for item in history if item["feedback_generated"])

    if passed:
        headline = "质量检查已通过，可进入交付前抽查"
        delivery_status = "ready_for_spot_check"
        summary = (
            f"最终得分 {score} 分，未发现阻断交付的问题。"
            "建议仍抽查姓名、分数、等级和版式后再正式发送。"
        )
    elif hard_count:
        headline = f"发现 {hard_count} 项阻断问题，必须人工介入"
        delivery_status = "blocked"
        summary = (
            "当前报告不能直接交付。自动修订已结束，但仍存在安全、数据或结构层面的阻断问题。"
        )
    elif major_count:
        headline = f"自动修订后仍有 {major_count} 项主要问题，需要人工复核"
        delivery_status = "review_draft_only" if review_draft_rendered else "blocked"
        summary = (
            "当前文件只可作为审核稿。请按下方问题逐项修正，并再次运行质量检查后再交付。"
        )
    else:
        headline = "未达到交付阈值，需要人工确认"
        delivery_status = "review_draft_only" if review_draft_rendered else "blocked"
        summary = (
            f"最终得分 {score} 分，低于目标 {target_score} 分。"
            "请结合下方检查提示确认内容是否可接受，或修正后重新生成。"
        )

    next_actions = []
    if requires_human_review:
        next_actions.append("不要把当前审核稿直接发送给学生或家长。")
        next_actions.append("先处理“阻断问题”和“主要问题”，再处理文字优化项。")
        next_actions.append("修正后重新生成，并确认状态变为“已通过”。")
    else:
        next_actions.append("抽查被试信息、原始分数、等级和负向计分指标。")
        next_actions.append("确认小学版/中学版口吻与成长建议场景没有混用。")
        next_actions.append("打开 PDF 检查分页、图表和文字是否遮挡。")

    return {
        "status": status,
        "delivery_status": delivery_status,
        "requires_human_review": requires_human_review,
        "headline": headline,
        "summary": summary,
        "score": score,
        "target_score": int(target_score),
        "review_draft_rendered": bool(review_draft_rendered),
        "automatic_repair": {
            "round_count": len(history),
            "feedback_rounds": feedback_rounds,
            "history": history,
        },
        "problem_groups": groups,
        "issues": normalized_issues,
        "next_actions": next_actions,
        "revision_instructions": _string_items(llm_result.get("revision_instructions")),
    }


def _issue_groups_html(groups: list[dict[str, Any]]) -> str:
    if not groups:
        return '<div class="empty">未发现需要列出的未解决问题。</div>'
    cards = []
    for group in groups:
        items = "".join(f"<li>{escape(item)}</li>" for item in group["items"])
        cards.append(
            f"""
            <section class="issue-card {escape(group['tone'])}">
              <div class="issue-heading">
                <h2>{escape(group['title'])}</h2>
                <span>{int(group['count'])} 项</span>
              </div>
              <ol>{items}</ol>
              <p class="action"><strong>处理建议：</strong>{escape(group['action'])}</p>
            </section>
            """
        )
    return "\n".join(cards)


def render_quality_review_html(review: dict[str, Any]) -> str:
    """Render a standalone local HTML report without external dependencies."""
    repair = review.get("automatic_repair", {})
    history_rows = []
    for item in repair.get("history", []):
        status = "通过" if item.get("passed") else "未通过"
        repair_text = "已生成修改指令" if item.get("feedback_generated") else "未调用反馈"
        repair_mode = {
            "initial_generation": "初稿生成",
            "targeted_patch": "定向修订",
            "targeted_recompose_fallback": "定向修订失败后自动重组",
        }.get(item.get("repair_mode"), str(item.get("repair_mode") or "未记录"))
        repair_note = str(item.get("repair_note") or "").strip()
        if repair_note:
            repair_mode = f"{repair_mode}（已自动兜底）"
        history_rows.append(
            "<tr>"
            f"<td>第 {int(item.get('round', 0))} 轮</td>"
            f"<td>{int(item.get('score', 0))} 分</td>"
            f"<td>{escape(status)}</td>"
            f"<td>{escape(repair_mode)}</td>"
            f"<td>{escape(repair_text)}</td>"
            f"<td>{int(item.get('hard_failure_count', 0))} / "
            f"{int(item.get('major_issue_count', 0))}</td>"
            "</tr>"
        )
    if not history_rows:
        history_rows.append('<tr><td colspan="6">没有可用的轮次记录。</td></tr>')

    actions = "".join(f"<li>{escape(item)}</li>" for item in review.get("next_actions", []))
    revisions = "".join(
        f"<li>{escape(item)}</li>" for item in review.get("revision_instructions", [])
    )
    revision_section = (
        f"<section class='plain-card'><h2>Checker 修改指令</h2><ul>{revisions}</ul></section>"
        if revisions
        else ""
    )
    badge_class = "blocked" if review.get("requires_human_review") else "ready"
    badge_text = "需要人工复核" if review.get("requires_human_review") else "已通过"

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>报告质量复核说明</title>
  <style>
    :root {{ --ink:#1f2f38; --muted:#63747d; --line:#dce5e8; --teal:#155f5b;
      --danger:#a43d3d; --danger-soft:#fff2f1; --warning:#94631b;
      --warning-soft:#fff8e9; --notice:#315f78; --notice-soft:#f0f7fa; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; color:var(--ink); background:#f4f7f7;
      font-family:"Microsoft YaHei","Noto Sans CJK SC",sans-serif; }}
    main {{ width:min(980px,calc(100% - 32px)); margin:28px auto 56px; }}
    header {{ padding:28px 30px; background:#fff; border-top:7px solid var(--teal);
      border-bottom:1px solid var(--line); }}
    .eyebrow {{ margin:0 0 8px; color:var(--muted); font-size:13px; font-weight:700; }}
    h1 {{ margin:0; font-size:27px; line-height:1.35; }}
    .summary {{ margin:12px 0 0; color:#41515a; line-height:1.8; }}
    .badge {{ display:inline-block; margin-top:16px; padding:7px 11px; font-weight:800;
      border-left:4px solid; }}
    .badge.blocked {{ color:var(--danger); background:var(--danger-soft); }}
    .badge.ready {{ color:#27734f; background:#eaf7ef; }}
    .metrics {{ display:grid; grid-template-columns:repeat(4,1fr); gap:1px;
      margin-top:1px; background:var(--line); }}
    .metric {{ padding:16px 18px; background:#fff; }}
    .metric span {{ display:block; color:var(--muted); font-size:12px; }}
    .metric strong {{ display:block; margin-top:5px; font-size:20px; }}
    .content {{ display:grid; gap:14px; margin-top:18px; }}
    .issue-card,.plain-card {{ padding:20px 22px; background:#fff; border:1px solid var(--line);
      border-left-width:5px; }}
    .issue-card.danger {{ border-left-color:var(--danger); }}
    .issue-card.warning {{ border-left-color:#d39a34; }}
    .issue-card.notice {{ border-left-color:var(--notice); }}
    .issue-heading {{ display:flex; align-items:center; justify-content:space-between; gap:16px; }}
    h2 {{ margin:0; font-size:18px; }}
    .issue-heading span {{ color:var(--muted); font-size:12px; font-weight:700; }}
    ol,ul {{ margin:12px 0 0; padding-left:24px; }}
    li {{ margin:7px 0; line-height:1.65; }}
    .action {{ margin:14px 0 0; padding:10px 12px; color:#42515a; background:#f6f8f8;
      line-height:1.65; }}
    table {{ width:100%; margin-top:14px; border-collapse:collapse; }}
    th,td {{ padding:10px; border:1px solid var(--line); text-align:left; font-size:13px; }}
    th {{ color:#52636c; background:#f5f8f8; }}
    .empty {{ padding:22px; color:var(--muted); background:#fff; border:1px solid var(--line); }}
    @media (max-width:700px) {{ .metrics {{ grid-template-columns:1fr 1fr; }} }}
  </style>
</head>
<body>
  <main>
    <header>
      <p class="eyebrow">Psych Report Agent · 质量复核说明</p>
      <h1>{escape(str(review.get('headline', '报告质量检查结果')))}</h1>
      <p class="summary">{escape(str(review.get('summary', '')))}</p>
      <span class="badge {badge_class}">{badge_text}</span>
    </header>
    <section class="metrics">
      <div class="metric"><span>最终得分</span><strong>{int(review.get('score', 0))}</strong></div>
      <div class="metric"><span>目标分数</span><strong>{int(review.get('target_score', 0))}</strong></div>
      <div class="metric"><span>检查轮次</span><strong>{int(repair.get('round_count', 0))}</strong></div>
      <div class="metric"><span>反馈修订轮次</span><strong>{int(repair.get('feedback_rounds', 0))}</strong></div>
    </section>
    <div class="content">
      <section class="plain-card">
        <h2>同事下一步怎么做</h2>
        <ol>{actions}</ol>
      </section>
      {_issue_groups_html(review.get('problem_groups', []))}
      {revision_section}
      <section class="plain-card">
        <h2>自动检查与修订记录</h2>
        <table>
          <thead><tr><th>轮次</th><th>得分</th><th>状态</th><th>修订方式</th><th>反馈</th><th>阻断 / 主要问题</th></tr></thead>
          <tbody>{''.join(history_rows)}</tbody>
        </table>
      </section>
    </div>
  </main>
</body>
</html>
"""
