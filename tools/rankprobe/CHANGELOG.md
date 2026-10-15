# Changelog

## Unreleased — installation, explicit input conversion and reference checks

- Added an isolated built-wheel gate to the existing cross-platform CI matrix.
- The gate installs only the specified local wheel, verifies the installed package location and versions, and exercises the real module/console entry points plus a synthetic retrieval comparison outside the checkout.
- Runtime code, metric definitions, and the `0.1.0a3` package version are unchanged by this CI improvement.
- Added an explicit source-checkout TREC normalization helper for runs with expendable trailing fields, with validation before creating a new file and source/output hashes. Strict core imports and all judgment policies remain unchanged.
- Added a pinned trec_eval reference job and an executable checker for shared-protocol MRR/NDCG/Recall, with separate probes documenting expected judgment, tie and averaging differences. Core metric definitions remain unchanged.

## 0.1.0a3 — readable comparisons and numerical stability

- Fixed HTML metric-delta tables that omitted the actual delta value.
- Added side-by-side submitted and matched-pool comparison results with metric coverage, reference scope, and JSON locations.
- Exposed bounded metric-coverage details and practical next steps for common findings.
- Recorded the exact excluded prediction-query IDs for each metric so coverage problems can be located without reconstructing the eligible set.
- Corrected exponential NDCG gain ratios at extremely small finite relevance values without changing the declared gain function.

The report improvements change presentation, not which queries are eligible or which metric deltas are permitted. The numerical correction applies to the finite-number input contract; it does not establish new benchmark results.

## 0.1.0a2 — retrieval input and judgment coverage

- Direct six-column TREC run and four-column qrels input, with explicit format overrides for ambiguous file names.
- Explicit `-1` judgments remain unknown; contradictory complete-qrels declarations fail clearly.
- Input formats and score-based TREC ordering are recorded with source hashes.
- Corrected `judged_candidates` to count known labels; `resolved_candidates` separately includes explicit assumptions.
- A hand-checkable retrieval case exposes score changes caused by omitted queries, plus a short independent-use guide.
- Report destinations cannot replace an input file, including explicitly formatted inputs named `report.json` or `report.html` and existing file aliases.

The format reader does not imply metric parity with `trec_eval`; tie rules, unknown handling, and the macro query universe remain explicit.

## 0.1.0a1 — initial implementation

- Local CSV/JSONL candidate-score auditing and independent relevance judgments.
- Explicit ordering, relevance, gain, and denominator choices.
- Exact-score tie sensitivity, duplicate-candidate diagnostics, and run-pool comparison.
- Self-contained HTML and JSON reports.
- Original miniature cases with inspectable expected results.
- Optional independently implemented NPZ exporter for a documented ReChorus-style matrix convention.
- English and Chinese introductions, capability boundaries, and an external-use validation plan.

This entry describes the initial code scope. It is not evidence of a PyPI publication, successful remote CI run, third-party adoption, or revenue. Check local validation records and workflow runs for executed checks.
