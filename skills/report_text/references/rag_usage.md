# RAG Usage For Standard Reports

Use retrieved standard report segments as local expert examples, not as facts about the current child.

## What RAG Segments Can Provide

- section structure
- wording rhythm
- parent/teacher-facing tone
- examples of low-score developmental framing
- examples of actionable growth support suggestions
- examples of how strengths and potential areas are connected

## What RAG Segments Must Not Provide

- another child's personal portrait
- another child's score conclusion
- family, school, teacher, peer, or history details
- exact copied sentences unless they are generic section boilerplate
- exaggerated wording that conflicts with current skill rules

## Retrieval Metadata

Each retrieved segment may include:

- `expert_source`: source version such as 潘专家版、汤专家版、陈专家版、综合版
- `section_type`: preface, core_growth_portrait, detailed_indicator_analysis, growth_support_suggestions
- `dimensions`: dimensions explicitly mentioned in the segment
- `top_dimensions`: high-score dimensions in that case
- `low_dimensions`: low-score dimensions in that case
- `match_score`: local retrieval score

Prefer segments with:

- similar section type to the current writing task
- overlap with current high and developing dimensions
- restrained language that matches score-band calibration
- concrete suggestions rather than abstract encouragement

## Writing Rule

Before drafting each section, use retrieved segments only to answer:

1. What structure does this kind of expert section use?
2. How does it explain scores to parents/teachers?
3. How does it turn a developing area into a concrete support action?

Then write new text strictly from the current assessment JSON.

## Dimension Detail Template RAG

When `dimension_detail_templates` is present, it contains one Excel “维度详解” pattern selected by the current indicator's raw score band.

- Use `source_definition` to check construct vocabulary and `score_band` to calibrate writing intensity.
- Treat `source_behavior_pattern` as a style pattern only; do not copy it verbatim.
- Rewrite or remove `legacy_risk_terms`, absolute claims, brain-diagnosis language, and invented events.
- Keep the current assessment JSON as the only source for the child's level, rating basis, direction, and conclusion.
- Record the returned `template_id` in `retrieval_trace.json` so a reviewer can see which template informed the run.
