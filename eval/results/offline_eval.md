# Offline evaluation (synthetic Toolkit)

Synthetic data with the live site's structure and invented wording. Run `cdp evaluate --live` on a machine that can reach the Toolkit for real-data numbers.

## Clean run

| Metric | Value |
|---|---|
| activities_in_site | 46 |
| drafted | 46 |
| blocked (false blocks on clean data) | 0 |
| fidelity pass rate | 1.0 |
| mean source coverage | 1.0 |
| activities with warnings | 30 |
| broken links | 0 |
| media uploaded | 92 |
| seconds | 0.22 |

## Planted problems: outcome per guardrail configuration

| Problem | all guardrails on | fidelity gate off | PII and instruction gate off | approval and hash gate off | all guardrails off | Caught by (all on) |
|---|---|---|---|---|---|---|
| changed step time | blocked | let through | blocked | let through | let through | fidelity |
| dropped step | blocked | let through | blocked | let through | let through | fidelity |
| paraphrased goal | blocked | let through | blocked | let through | let through | fidelity |
| inserted 'not' | blocked | let through | blocked | let through | let through | fidelity |
| dropped journal prompt | blocked | let through | blocked | let through | let through | fidelity |
| instruction to the AI on the page | blocked | blocked | let through | let through | let through | pii |
| email address on the page | blocked | blocked | let through | let through | let through | pii |
| commenter name leaked | blocked | blocked | let through | let through | let through | pii |
| edited after checks | blocked | blocked | blocked | let through | let through | approval/hash |

## Summary

| Configuration | Planted problems let through |
|---|---|
| all guardrails on | 0 of 9 |
| fidelity gate off | 5 of 9 |
| PII and instruction gate off | 3 of 9 |
| approval and hash gate off | 9 of 9 |
| all guardrails off | 9 of 9 |
