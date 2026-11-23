# Score Band Checks

Score-band calibration is central to Tang teacher's standards.

## Expected Bands

Use explicit input levels when provided:

- 优势区 / 高 / 较高 / top_30 -> advantage
- 常态区 / 中等 / 中等偏上 / middle -> normal
- 潜力区 / 发展中 / 中等偏低 / bottom_30 -> potential

If score and level conflict, flag it for human review instead of guessing.

## Fixed Norm Raw-Score Checks

When `scale_config.classification_basis` is `fixed_norm_20_80_raw_score`:

- Bands must come from raw score compared with fixed norm P20/P80.
- The report must not describe the band as class rank, peer percentile, or a 0-100 converted score.
- Main charts should show the raw-score position with an arrow on three bands: 潜力区, 常态区, 优势区.
- Main charts should not print the raw numeric score beside the arrow; keep raw scores and norm boundaries in appendix or structured data.
- If `level` conflicts with `raw_score`, `norm_p20`, and `norm_p80`, flag for human review rather than silently changing prose.

## Wording Rules

Advantage:

- Allowed: “较明显优势”“表现较突出”“更容易投入”“有较好基础”.
- Avoid: “天生”“顶尖”“完美”“第一梯队”“无懈可击”“绝对”.

Normal:

- Allowed: “整体稳定”“有一定基础”“多数情境下能够保持”“仍可继续巩固”.
- Avoid: “突出优势”“极好”“明显落后”“严重不足”.

Potential:

- Allowed: “仍在发展”“需要更多支持”“可以通过具体练习逐步提升”.
- Avoid: “表现卓越”“优势突出”“差”“弱”“问题严重”“很糟糕”.

## LLM Checker Requirements

For every important dimension mentioned in the report:

1. Locate its input level or percentile band.
2. Locate the report's wording strength.
3. Judge whether wording strength matches the level.
4. If mismatched, record `score_band_errors` with dimension, expected band, offending text, and revision target.

If the report never explains the levels while the input provides them, deduct under score-band calibration and detailed analysis.
