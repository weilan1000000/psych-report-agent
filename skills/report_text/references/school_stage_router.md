# School Stage Router

Treat school-stage selection as an explicit product decision, not an inference
from a score pattern or a retrieved example.

## Default

Use the elementary-school writing variant unless the assessment input explicitly
requests a secondary-school report.

## Explicit Secondary-School Signals

Enable the secondary-school variant only when a top-level field or
`respondent_profile` field such as `report_type`, `report_stage`, `school_stage`,
`education_stage`, `age_group`, `report_variant`, or `writing_variant` contains:

- `middle_school`, `secondary`, `中学`, or `青少年`
- `junior_high` or `初中`
- `senior_high` or `高中`

Resolve `初中` to `junior_high`, `高中` to `senior_high`, and an unqualified
`中学/青少年` request to `secondary`.

Do not switch variants merely because:

- a retrieved report was written for an older student
- a metric name also appears in a secondary-school scale
- the student's age could plausibly fall in secondary school
- the report contains career-related metrics without an explicit stage field

The selected stage must be recorded in the deterministic writing plan and used
by TextAgent, MetricWriterAgent, CheckerAgent, and FeedbackAgent.

## Stage Isolation

- Always load the common quality layer.
- Load the elementary overlay only for `elementary`.
- Load the secondary writing and support overlays only for `secondary`,
  `junior_high`, or `senior_high`.
- Select the suggestion category contract from the same stage: elementary
  family scenes for `elementary`, and self-growth/project/career-development
  categories for secondary school.
- Retrieve only examples tagged for the selected stage. An untagged elementary
  example must not enter a secondary prompt.
- Select illustration assets from the same deterministic stage. A retrieved
  text example can never change the illustration set.
