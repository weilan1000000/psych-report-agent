---
name: report-checker
description: Formal quality checking for child psychological/educational assessment reports. Use when CheckerAgent evaluates parent/teacher-facing Chinese report text for data faithfulness, score-band calibration, safety boundaries, structure, actionability, and low-AI professional style using Pan and Tang teacher standards.
---

# Report Checker Skill

Use this skill to evaluate child assessment report text before delivery or before sending revision feedback to TextAgent.

The checker does not rewrite the report. It identifies risks, scores quality, and produces concrete revision targets.

## Required Inputs

- assessment JSON, including scores, levels, percentile bands, dimension interpretations, and constraints
- report text or structured report JSON
- deterministic rule-check findings, if provided
- scoring rubric from `config/report_rubric.json`

## Core Checks

1. Safety boundary: no diagnosis, no medical conclusion, no fixed trait label, no unsupported family/school history.
2. Data faithfulness: every important claim must trace to scores, levels, interpretations, or explicit background.
3. Score-band calibration: 优势区、常态区、潜力区 must use different wording strength.
4. Parent/teacher readability: plain language, respectful tone, low jargon, no internet slang.
5. Structure: include 前言、核心成长画像、详细指标分析、成长支持建议、报告说明 or equivalent fields.
6. Suggestions: advice must connect to earlier strengths and developing areas, then give scenes and actions.
7. Style: professional, warm, restrained, non-template, low AI tone.
8. Visible wording: avoid anxiety-provoking labels such as "心理测评"; prefer "本次评估", "综合素质评估", or "发展观察".

## Must Read When Needed

- `references/hard_failures.md`: one-vote-fail conditions.
- `references/score_band_checks.md`: deterministic and LLM score-band calibration rules.
- `references/final_report_quality_anchors.md`: quality anchors from revised expert reports and residual risks in the corpus.
- `references/structure_and_fabrication_checks.md`: strict JSON, fixed section IDs, parent suggestion schema, and invented-experience checks.
- `references/parent_teacher_readability.md`: parent/teacher readability and tone checks.
- `references/output_schema.md`: required CheckerAgent JSON shape.

Also use `report_text` skill content when available, because the checker must judge against the same writing standards the generator follows.

## Decision Rules

- If a hard failure appears, set `pass=false` even if the prose is fluent.
- If any major issue appears, set `pass=false` and cap the score according to rubric calibration.
- If the report has no explicit score-band calibration and the input provides levels, treat this as at least a major issue.
- If the report is warm but not data-faithful, fail it.
- If the report is data-faithful but too technical or parent-unreadable, require revision.
- If advice is not visibly derived from the child's data, require revision.
- If TextAgent output is not valid JSON or misses fixed section IDs needed by the renderer/API, require revision even when the prose is fluent.
- If parent wording invents a specific past school, family, peer, teacher, or activity experience not present in the assessment JSON, require revision.

## Feedback Discipline

Revision instructions must be specific enough for TextAgent to act:

- name the section or dimension
- name the problem
- say what to replace or add
- preserve useful accurate content when possible

Avoid vague instructions such as “写得更自然一点” or “更专业一点”.
