# Output Schema

CheckerAgent should return valid JSON. Use concise but actionable language.

```json
{
  "pass": false,
  "total_score": 0,
  "scores": {
    "faithfulness": 0,
    "score_band_calibration": 0,
    "safety_boundary": 0,
    "structure_completeness": 0,
    "parent_teacher_readability": 0,
    "actionability": 0,
    "humanlike_style": 0
  },
  "hard_failures": [],
  "major_issues": [],
  "minor_issues": [],
  "score_band_errors": [
    {
      "dimension": "",
      "expected_band": "",
      "offending_text": "",
      "revision_target": ""
    }
  ],
  "evidence_gaps": [],
  "structure_errors": [],
  "contract_errors": [],
  "fabrication_risks": [],
  "audience_errors": [],
  "revision_instructions": [],
  "needs_human_review": false
}
```

If a list has no items, return an empty list.

Do not return Markdown.
