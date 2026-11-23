---
name: report-rewriter
description: Convert CheckerAgent findings into concrete revision instructions for child assessment report generation. Use when FeedbackAgent needs to guide TextAgent/GeneratorAgent to revise parent/teacher-facing Chinese psychological or educational assessment reports based on rubric, score-band, safety, structure, RAG, and style issues.
---

# Report Rewriter Skill

Use this skill to turn CheckerAgent results into actionable instructions for TextAgent.

FeedbackAgent does not rewrite the whole report. It tells TextAgent exactly what to preserve, fix, remove, and add.

## Required Workflow

1. Read CheckerAgent result first.
2. Separate hard failures, major issues, minor issues, score-band errors, evidence gaps, structure errors, and audience errors.
3. Preserve accurate, data-faithful, parent-readable content.
4. Convert each problem into a concrete rewrite target.
5. Prioritize safety and data faithfulness before style polish.
6. Mention the relevant section or dimension whenever possible.

## Priority Order

1. Remove diagnosis, labels, unsupported claims, and dangerous advice.
2. Fix score-band mismatches.
3. Fix contradictions between core growth portrait and detailed indicator analysis.
4. Restore required structure: 前言、核心成长画像、详细指标分析、成长支持建议、报告说明。
5. Make advice data-linked and actionable.
6. Reduce AI tone, jargon, and inflated wording.

## Must Read When Needed

- `references/revision_feedback_schema.md`: output JSON schema.
- `references/revision_targets.md`: common rewrite targets and wording.

## Output Discipline

Return valid JSON only. Do not output markdown.

Keep instructions short but executable.
