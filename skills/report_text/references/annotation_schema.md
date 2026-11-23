# Annotation Schema

Use this schema to convert expert comments into reusable training data.

## Expert Feedback File

```json
{
  "report_id": "report_001",
  "expert": "pan",
  "audience": "parents",
  "assessment_type": "innovation_potential",
  "anonymized": true,
  "overall": {
    "deliverable": false,
    "main_strengths": [],
    "main_issues": []
  },
  "segments": [
    {
      "segment_id": "report_001_s01",
      "section": "core_portrait",
      "original_text": "",
      "expert_comment": "",
      "issue_types": [],
      "severity": "minor|major|hard_failure",
      "rewrite_direction": "",
      "positive_pattern": "",
      "negative_pattern": "",
      "data_basis": []
    }
  ],
  "principles_extracted": []
}
```

## Issue Types

Use these labels:

- internal_contradiction
- unsupported_inference
- diagnostic_or_clinical
- parent_blame
- negative_label
- absolute_wording
- too_academic
- generic_advice
- weak_data_link
- self_report_as_fact
- repetitive_template
- good_concrete_description
- good_warm_low_score
- good_actionable_advice

## Severity

- hard_failure: diagnosis, blame, severe contradiction, unsupported harmful claim
- major: contradiction, advice not linked to data, strong labeling, repeated absolute wording
- minor: wording too academic, slightly generic, not parent-friendly enough
