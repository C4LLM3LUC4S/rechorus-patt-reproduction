# Changelog

## 0.1.0a2 — retrieval input and judgment coverage

- Direct six-column TREC run and four-column qrels input, with explicit format overrides for ambiguous file names.
- Explicit `-1` judgments remain unknown; contradictory complete-qrels declarations fail clearly.
- Input formats and score-based TREC ordering are recorded with source hashes.
- Corrected `judged_candidates` to count known labels; `resolved_candidates` separately includes explicit assumptions.
- A hand-checkable retrieval case exposes score changes caused by omitted queries, plus a short independent-use guide.

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
