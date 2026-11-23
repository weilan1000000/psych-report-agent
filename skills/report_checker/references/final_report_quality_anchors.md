# Final Report Quality Anchors

Use these anchors when comparing generated reports against the revised expert report corpus.

## Corpus Snapshot

- 30 revised reports currently indexed
- 973 RAG segments
- section distribution:
  - preface: 30
  - core_growth_portrait: 75
  - detailed_indicator_analysis: 767
  - growth_support_suggestions: 101

The corpus is an expert reference set, but not a hard gold standard. CheckerAgent must still apply hard safety and score-band rules.

## Excellent Report Anchors

A deliverable report should:

- make the parent/teacher feel "this is my child"
- explain every selected score level accurately
- include both strengths and development space
- avoid labels, diagnosis, blame, and fatalism
- use plain parent-readable language
- give advice that can be tried in daily life
- include a boundary note that the report is not a diagnosis

## Common Residual Risks In The Corpus

Even revised reports may contain:

- inflated words such as "极其", "完美", "第一梯队", "绝不"
- over-stylized metaphors
- occasional professional jargon
- advice that is vivid but too broad or not tightly linked to data

Do not let these pass just because they appear in a revised example.

## Checker Scoring Anchor

Scores should be conservative:

- 90+: safe, data-faithful, calibrated, structured, actionable, natural
- 85-89: acceptable but may need light human review
- 75-84: useful material but requires TextAgent revision
- below 75: return to prompt, input, or scale explanation

Hard failures cap the score at 69 regardless of fluency.
