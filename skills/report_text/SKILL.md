---
name: report-text
description: Psychological and educational assessment report writing for Chinese elementary and secondary-school reports. Use when generating, revising, or checking data-faithful, score-calibrated, non-diagnostic, low-AI report prose. Elementary reports are parent-facing; explicitly selected secondary reports are student-facing and emphasize agency, study methods, exploration, and adult support boundaries.
---

# Report Text Skill

Use this skill to write psychological or educational assessment report text.

Apply two layers in order:

1. Common quality layer: data faithfulness, score calibration, professional definitions, non-diagnostic safety, no invented experience, restrained low-AI prose.
2. Stage layer: elementary reports speak to parents about the child; explicitly selected secondary reports speak directly to the student and place adults in a supporting role.

Use the elementary-school variant by default. Load
`references/school_stage_router.md` before selecting a stage. Load
`references/secondary_school_writing_style.md` and
`references/secondary_school_support_advice.md` only when the assessment input
explicitly requests a middle-, junior-high-, senior-high-, or youth-report
variant. A retrieved secondary-school example must never switch the stage.

For the elementary variant, the report is mainly for parents and may also be read by teachers. If the input audience is `parents`, directly address parents only; do not use "家长/老师" as the visible salutation.

For `secondary`, `junior_high`, or `senior_high`, the visible report is for the student. Use direct second-person Chinese such as “你可以留意”“当你面对……时”. Parents and teachers appear only as people from whom the student can request structure, information, feedback, or emotional support.

The secondary-school indicator analysis and final advice have separate jobs.
Indicator blocks explain the current task performance, developmental meaning,
and conditions that may affect expression; they do not contain exercises or
action plans. Student-owned actions, visible outputs, and review rules belong
only in the final three secondary-school support suggestions. Never inject the
secondary student-facing voice or advice categories into an elementary report.

A good elementary report should make the adult reader feel:

1. "This is my child."
2. "I understand what the result means."
3. "I know what I can do next."

A good secondary report should make the student feel:

1. "This sounds like my current way of working, not a label."
2. "I understand what these results mean in real tasks."
3. "I have one or two methods I can test next."

## Core Rule

Write truthfully, plainly, warmly, and usefully:

- Truthfully: every judgment must be supported by assessment data.
- Calibrated: wording strength must match the score band or level.
- Plainly: the selected reader should understand without psychological jargon.
- Warmly: low scores are framed as development, not blame.
- Usefully: suggestions must connect to the student's data and assign actions to the correct stage-specific reader.

## Score Source Of Truth

Treat every supplied metric as a source record, not as a number that can be freely relabeled:

- A report can contain only a subset of the `students_scores_100` metric catalog. Never infer a conclusion from a missing metric.
- Preserve the input `level`, `percentile_band`, `interpretation`, and `direction`. Do not use a generic score threshold to rename “较高” or `top_30` as “优势区”, or “中等偏低” as “潜力区”.
- If the input has only a raw score and no scale-version-specific classification rule, state the score cautiously and add `缺少层级或方向规则` to the affected section's `risk_flags`.
- Do not assume that a larger number is better. Metrics such as 负性情绪 and task-based cognitive indicators require their supplied direction or interpretation.
- In `data_sketch`, each selected dimension must include `source_level` copied from the input. Any visible level wording must be equal to, or more neutral than, that source wording.

## Required Workflow

1. Read the assessment JSON before writing.
2. Read retrieved standard report segments if RetrievalAgent provides them.
   - Use them as references for section structure, wording restraint, and suggestion patterns.
   - Do not copy another child's facts, score pattern, family/school situation, or exact portrait.
   - Prefer examples with similar high dimensions, developing dimensions, and section type.
3. Build a data sketch:
   - strengths: dimensions explicitly marked as a strength/high level by the supplied scale metadata
   - developing areas: dimensions in 潜力区 or clearly low/developing level
   - middle areas: dimensions in 常态区; mention only when needed for balance
4. Assign a writing strength to each selected dimension:
   - 优势区: clear but restrained strength
   - 常态区: balanced, ordinary, stable, neither inflated nor alarming
   - 潜力区: developmental support, not a defect
5. Check consistency across dimensions before writing. Do not let the core growth portrait contradict detailed indicators.
6. Draft the core growth portrait using only prominent strengths and prominent developing areas.
7. Explain dimensions in parent/teacher-readable language. Translate scores into observable tendencies, not labels.
   - Every supplied score must have one independent `【指标名】` block in `detailed_indicator_analysis`; do not explain only one representative indicator per module.
   - Use the two-layer pattern for each indicator: a short professional definition first, then a plain-language explanation of the current child's likely tendency and observable scenes.
   - Never explain one score as a fixed personality. Use “现阶段的行为策略/反应风格/互动倾向” rather than “性格里的...”.
   - In a secondary report, keep each indicator interpretation advice-free. Explain the metric-specific task manifestation, developmental value, and conditions that may affect stability. Do not add a weekly exercise, tool, quantity, artifact, or review step here.
8. Write low-score or developing areas with the sandwich pattern:
   - normalize: many children at this stage may...
   - concrete behavior: in this data, the child currently tends to...
   - path forward: parents can support by...
9. Write suggestions that grow from data:
   - elementary category: 学习与日常、课外与探索、亲子互动与沟通
   - junior-high category: 自我成长与学习规划、兴趣探索与项目实践、生涯启发与发展规划
   - scene
   - action
   - support wording for the selected reader
   - small first step
10. Apply `references/teacher_annotation_universal_rules.md`:
   - state the report purpose as `定位现阶段 -> 认识资源 -> 看见发展方向 -> 选择可验证行动`
   - remove mechanical hinges such as `不是……而是……`、`这提示……` and `按输入的量表解释……`
   - make each final support suggestion include a scene, exact action, observable result, and review signal
11. Self-check for hard failures before returning.

## Must Read When Needed

- `references/writing_principles.md`: Pan teacher's macro criteria and one-vote-fail rules.
- `references/tang_teacher_standards.md`: Tang teacher's score-band calibration, section naming, preface, and suggestion logic.
- `references/multi_expert_guidance.md`: consolidated guidance from all four overall guidance documents.
- `references/final_report_patterns.md`: stable patterns extracted from revised expert reports and how to use them safely.
- `references/expert_style_guide.md`: parent-facing tone, wording preferences, and low-AI style.
- `references/humanized_parent_style.md`: domain-safe low-AI writing rules for parent-facing reports.
- `references/senior_pdf_feedback.md`: professional-definition + parent-translation writing, non-personality attribution, full-profile, and scenario-grouped suggestion rules.
- `references/common_errors.md`: common problems found in the first five reviewed reports.
- `references/safety_boundary.md`: diagnosis, ethics, and child-protection boundaries.
- `references/section_structure.md`: recommended section-level writing structure.
- `references/expert_definition_method.md`: the runtime method for turning an expert construct definition into a parent-readable, data-faithful indicator block.
- `references/indicator_definition_catalog.json`: a local reference index for maintaining terminology and checking coverage; it is not a script to copy directly into a report.
- `references/rag_usage.md`: how to use retrieved standard report segments without copying another child's facts.
- `references/agent_workflow.md`: staged planning, metric-batch writing, gold-report RAG boundaries, and patch-only revision rules.
- `references/metric_reference_cards.md`: Excel-derived professional terminology and score-band references that must be paraphrased, never copied.
- `references/expert_writing_core.md`: the cross-expert evidence ladder, profile method, level calibration, and parent-facing writing method that govern all RAG use.
- `references/core_portrait_method.md`: deterministic evidence selection and the required portrait argument for the first-page core growth portrait.
- `references/input_output_contract.md`: structured TextAgent input and output schema.
- `references/annotation_schema.md`: schema for converting expert comments into reusable data.
- `references/school_stage_router.md`: deterministic default-to-elementary stage selection.
- `references/secondary_school_writing_style.md`: secondary-school voice, portrait, indicator, and junior/senior distinctions; load only after an explicit secondary-stage selection.
- `references/secondary_school_support_advice.md`: student-led support and career-exploration method; load only after an explicit secondary-stage selection.
- `references/teacher_annotation_universal_rules.md`: latest teacher corrections for precise report purpose, readable developmental language, low-AI sentence structure, and genuinely actionable suggestions; load for every stage.

Use `examples/*.json` as few-shot material when the task asks for examples, case-based writing, rewriting, or RAG preparation.

Use `retrieved_standard_segments` from RetrievalAgent when available. These are preferred over static examples because they come from the local expert report corpus and include metadata such as expert source, section type, high dimensions, low dimensions, and matched score bands.

## Output Discipline

Prefer structured JSON for TextAgent outputs unless the user explicitly asks for prose only.

When returning JSON, return a strict JSON object. Do not use markdown fences, comments, trailing commas, or unescaped English double quotes inside string values. If a string needs quotation marks in Chinese prose, use Chinese quotation marks “”.

In visible parent-facing prose, avoid "心理测评". Prefer "本次评估", "综合素质评估", "发展观察", or "本次结果".

Each section should include:

- section_id
- title
- body
- evidence_used
- parent_action if the section contains advice

Do not invent experiences, family background, diagnoses, learning history, or emotional causes that are not in the input.

Keep section bodies PDF-friendly. Put detailed repeated action steps in `parent_suggestions` instead of duplicating a long list inside `sections.body`.

Default section titles:

- 前言
- 核心成长画像
- 详细指标分析
- 成长支持建议
- 报告说明

Default section IDs must stay fixed:

- `preface`
- `core_growth_portrait`
- `detailed_indicator_analysis`
- `growth_support_suggestions`
- `boundary_note`
