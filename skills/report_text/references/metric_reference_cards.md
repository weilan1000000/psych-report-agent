# Metric Reference Cards

Read `expert_writing_core.md` first. Build
`rag_examples/metric_reference_cards.jsonl` from the Excel-derived
`dimension_detail_templates.jsonl` before a TextAgent run.

For each current metric, retrieve only the card matching its raw-score band.

1. Use `professional_definition` and `professional_label` for terminology.
2. Use `parent_translation_focus` to select a conditional observation context.
3. Use the score band only to calibrate wording strength.
4. Use the assessment JSON, not the card, for the child's level and conclusion.

Treat the card as RAG knowledge, not as a sentence template. Never copy its
historical behavioral prose or use it to claim a child has an experience,
relationship, or fixed personality trait.
