# Structure And Fabrication Checks

Use this reference when checking TextAgent output for API/PDF readiness and data faithfulness.

## Strict JSON Contract

The TextAgent output must be a valid JSON object, not pseudo-JSON.

Required top-level fields:

- `audience`
- `report_type`
- `data_sketch`
- `sections`
- `parent_suggestions`
- `self_check`

Required `sections[*].section_id` values:

- `preface`
- `core_growth_portrait`
- `detailed_indicator_analysis`
- `growth_support_suggestions`
- `boundary_note`

Do not accept substitute IDs such as:

- `growth_support_suggestions_preview`
- `detailed_design`
- `detailed_science`
- `summary`
- `conclusion`

If detailed indicators are split internally, they should still live inside the single `detailed_indicator_analysis` section body.

## Parent Suggestion Contract

Each parent suggestion should include:

- `scene`
- `data_basis`
- `action`
- `parent_wording`
- `first_step`

Suggestions should be concrete, but not invented.

## Unsupported Specific Experience

Flag parent wording or advice that makes an unprovided child experience sound real.

Problematic:

- "上次你提到班里有同学养了蚕..."
- "还记得你昨天数学题做得很好吗..."
- "老师上周表扬你..."
- "你和同学合作时总是..."

Safer:

- "如果孩子最近提到某个自然现象，可以..."
- "可以选一道孩子已经完成的题..."
- "在一次普通的小组或家庭合作后，可以..."

Use the assessment JSON as the only source of child-specific facts. RAG examples may provide writing patterns, not facts.
