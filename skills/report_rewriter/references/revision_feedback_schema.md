# Revision Feedback Schema

FeedbackAgent should return JSON:

```json
{
  "revision_goal": "",
  "priority": "major",
  "keep": [],
  "fix": [
    {
      "section_id": "",
      "dimension": "",
      "problem": "",
      "instruction": "",
      "evidence_to_use": []
    }
  ],
  "avoid": [],
  "rag_guidance": {
    "use_retrieved_segments": true,
    "preferred_section_types": [],
    "do_not_copy_case_facts": true
  },
  "specific_instructions": []
}
```

If a field is unknown, use an empty string or empty list.

Use `priority` values:

- `hard_failure`
- `major`
- `minor`
- `polish`
