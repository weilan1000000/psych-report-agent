# Project Skills

- `report_text/`: parent-facing report writing rules, definitions and examples.
- `report_checker/`: output, safety, score-band and readability checks.
- `report_rewriter/`: targeted revision contracts.
- `chart_designer.md`, `layout_designer.md`, `pdf_style_guide.md`: chart and PDF
  design guidance.
- `safety_boundary.md`: shared non-diagnostic and child-protection boundary.

Runtime files are selected explicitly in `agent_team.py`; placing a file here does
not automatically send it to DeepSeek. When adding a required skill, update the
runtime manifest and the offline validation together.
