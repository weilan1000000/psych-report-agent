# Input Output Contract

## TextAgent Input

Use this structure when possible:

```json
{
  "assessment_result": {
    "report_type": "innovation_potential",
    "audience": "parents_and_teachers",
    "respondent_profile": {
      "report_subject_label": "刘X彤",
      "age_group": "小学阶段"
    },
    "assessment_metadata": {
      "source_student_id": "1"
    },
    "school_stage": "elementary",
    "scores": {},
    "dimension_interpretations": {},
    "scale_notes": {},
    "scale_config": {
      "catalog_id": "students_scores_100_v1",
      "classification_rule_version": "",
      "score_reference_lines": []
    }
  },
  "writing_task": {
    "mode": "generate",
    "sections": ["preface", "core_growth_portrait", "detailed_indicator_analysis", "growth_support_suggestions", "boundary_note"],
    "max_chars_per_section": {
      "core_portrait": 220,
      "dimension_analysis": 160,
      "parent_suggestions": 220
    }
  },
  "retrieved_context": {
    "excellent_examples": [],
    "bad_examples": [],
    "expert_feedback_patterns": [],
    "retrieved_standard_segments": [
      {
        "segment_id": "",
        "expert_source": "",
        "section_type": "",
        "section_title": "",
        "matched_score_name": "",
        "matched_score_bands": {},
        "high_dimensions": [],
        "low_dimensions": [],
        "text": ""
      }
    ],
    "retrieved_standard_segments_by_section": {
      "preface": [],
      "core_growth_portrait": [],
      "detailed_indicator_analysis": [],
      "growth_support_suggestions": []
    },
    "retrieval_profile": {
      "dimensions": [],
      "top_dimensions": [],
      "low_dimensions": [],
      "levels": {}
    }
  },
  "revision_feedback": null
}
```

`school_stage` or an equivalent explicit field controls the writing variant.
Use `elementary`, `junior_high`, `senior_high`, or `secondary`. When it is
missing or unclear, the runtime must use `elementary`; RAG examples must not
change the selected stage.

`assessment_metadata.source_student_id` is an administrative identifier only.
It may be a numeric string such as `"1"` or a display string such as `"1号"`.
The renderer may show it on the cover and task list, but TextAgent must not use
it as psychological evidence, repeat it in narrative sections, or infer any
trait, behavior, score, background, or identity from it.

## TextAgent Output

Prefer JSON:

```json
{
  "audience": "parents_and_teachers",
  "report_type": "innovation_potential",
  "data_sketch": {
    "advantage_dimensions": [],
    "developing_dimensions": [],
    "middle_dimensions": [],
    "possible_conflicts": [],
    "score_band_calibration": []
  },
  "sections": [
    {
      "section_id": "core_growth_portrait",
      "title": "核心成长画像",
      "body": "",
      "evidence_used": [],
      "rag_reference_used": [],
      "risk_flags": []
    }
  ],
  "parent_suggestions": [
    {
      "category": "学习与日常",
      "scene": "",
      "data_basis": "",
      "action": "",
      "parent_wording": "",
      "first_step": ""
    }
  ],
  "self_check": {
    "no_diagnosis": true,
    "no_unsupported_inference": true,
    "no_extreme_wording": true,
    "internally_consistent": true,
    "score_band_calibrated": true,
    "advice_linked_to_data": true,
    "parent_teacher_readable": true
  }
}
```

`category` is stage-specific:

- elementary: `学习与日常`、`课外与探索`、`亲子互动与沟通`
- junior high: `自我成长与学习规划`、`兴趣探索与项目实践`、`生涯启发与发展规划`

When at least three suggestions are written, cover all three categories for the
selected stage unless a section-level `risk_flags` entry explains why a
category is not suitable for the supplied data. Keep the legacy JSON field
names for compatibility; their visible semantics follow the stage overlay.

## Evidence Rules

## Metric Source Rules

An assessment may include only a subset of the canonical metric catalog. Omitted metrics are unknown, not negative findings.

For every supplied score object, upstream should provide the following whenever available:

```json
{
  "dimension_name": "问题好奇心",
  "score": 78,
  "level": "较高",
  "percentile_band": "top_30",
  "rank_percentile": 86.4,
  "interpretation": "...",
  "direction": "higher_is_more"
}
```

- `level`, `percentile_band`, `rank_percentile`, `interpretation`, and `direction` belong to the scoring service and are the source of truth.
- When `scale_config.classification_basis` is `class_rank_percentile`, `rank_percentile` describes the class-peer position after applying the metric's supplied `direction`; use its supplied `level` rather than deriving a level from raw `score`.
- When `scale_config.classification_basis` is `fixed_norm_20_80_raw_score`, use `raw_score`, `norm_p20`, and `norm_p80` as the rating evidence: `raw_score <= norm_p20` is 潜力区, `norm_p20 < raw_score < norm_p80` is 常态区, and `raw_score >= norm_p80` is 优势区. Do not describe this as class rank or peer percentile.
- In `fixed_norm_20_80_raw_score` mode, chart text should say the figure uses original raw scores from the first score worksheet and fixed norm boundaries. Do not ask the model to convert raw scores into 0-100 chart coordinates.
- A generic renderer or writer must not convert `top_30` or a score of 78 into the visible label “优势区” unless `level` explicitly says so.
- `score_reference_lines` are optional. Only render a line such as 55/70 if this scale version explicitly supplies it.
- When `direction` or a scale-specific level rule is missing, use a cautious description and add `缺少层级或方向规则` to `risk_flags`.

Every section must list `evidence_used`.

When RAG segments are used, also list `rag_reference_used` with segment IDs or source labels.

RAG segments are references, not facts about the current child. Use them for:

- section rhythm
- wording restraint
- parent-facing explanation patterns
- advice structure

Do not use RAG segments for:

- another child's score conclusion
- another child's family, school, peer, or behavior facts
- unsupported causes or diagnoses
- verbatim copying

Evidence may include:

- score key
- dimension level
- percentile band
- interpretation text
- explicit background field

For each `data_sketch` item, use this minimum form when source level metadata exists:

```json
{
  "dimension_name": "问题好奇心",
  "score": 78,
  "source_level": "较高",
  "level": "较高"
}
```

If evidence is missing, write cautiously or ask for data instead of inventing.
