# Text-Agent Workflow

Use the writing system as a staged pipeline. Do not ask one model call to decide score meaning, plan a report, write every indicator, and repair every issue at once.

1. Treat the assessment JSON as the only source of child-specific facts. Preserve `level`, `rating_basis`, `direction`, and any upstream interpretation.
2. Build a `writing_plan` for every supplied metric. The plan records the professional definition, score interpretation, parent-translation focus, and permitted RAG references.
3. Write detailed indicators in batches of four to six. Each batch returns only exact `【指标名】` blocks. Verify that every supplied metric has one block before composition.
4. Compose the preface, core portrait, support suggestions, and boundary note around the fixed indicator blocks.
5. Run deterministic contract, score-fidelity, safety, and coverage checks before an LLM style review.
6. When revision is needed, patch only the indicated section, suggestion, or metric block. Do not regenerate an otherwise valid full report.

## Gold Report RAG

The five manually selected reports in `rag_examples/gold_comprehensive_reports/` are a small gold set. They may teach:

- the order of professional definition, result interpretation, and parent translation
- sentence density, paragraph rhythm, and degree of restraint
- how a support idea is made concrete

They must never supply facts, scores, labels, diagnoses, events, relationships, or wording to copy into a new child's report. They are unpaired with assessment JSON and therefore must not recalibrate the current child’s score label.

## Revision Gate

Classify issues before revision:

- `contract_or_safety`: must be corrected before delivery.
- `score_or_coverage`: patch the named metric or section.
- `style`: patch only when a concrete location and rewrite instruction are available; do not use a generic request to “make it more natural” as a reason to rewrite the full report.
