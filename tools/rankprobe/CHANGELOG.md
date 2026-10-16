# Changelog

## 0.1.0a4 — MRR eligibility from known prefixes

- MRR can include a query when the first relevant rank is already determined by known labels, even if later candidates remain unknown. An unknown before that first relevant item still excludes the query; fully known top-k lists with no relevant item contribute zero.
- Missing labels, assumption counts, NDCG, Recall and exact tie-bound rules are unchanged. Broader MRR coverage changes the eligible subset and can change its average; it is not evidence of improved ranking scores.
- MRR results record `eligibility_rule=known_first_relevant_prefix` in JSON and HTML coverage details. MRR deltas require the same explicit rule on both sides; reports without it must be recomputed from their original inputs before comparison.
- This refines the deliberately conservative 0.1.0a3 eligibility contract. Preserve earlier reports with their version and do not subtract old and new conditional averages.

## Unreleased — installation, explicit input conversion and reference checks

- Added an opt-in real-input reference checker for the checksummed TREC-COVID Round 1 pair. It compares an explicitly declared nonrelevant assumption and aligned tie order with the current pinned NIST implementation, preserving sparse source judgments, the default unknown audit and incomplete-qrels status. Historical score agreement does not authenticate the original evaluator.
- Added a checksummed, file-only TREC-COVID Round 1 walkthrough using actual archived predictions and matching judgments. It documents explicit format selection, sparse judgment coverage and tied scores without bundling upstream files or claiming benchmark parity, adoption or time saved.
- Restricted branch-push CI to `main` while retaining PR, tag and declared manual triggers, avoiding duplicate ten-job suites for feature PR updates. The validation matrix and job contents are unchanged; feature branches without PRs no longer start checks automatically.
- Clarified how to retain sampled-negative assumptions in audit reports: keep unknown labels in the exported CSV, then explicitly declare the audit policy when the source protocol supports it. Materialized zero labels and the exporter's separate metadata are distinguished from report-recorded assumptions.
- Added a separately scoped pinned-reference exp2 NDCG case for original integer grades 0–3. Only an oracle qrels copy receives the gain mapping; 12 per-query/macro comparisons supplement the existing linear checks and preserve the original inputs.
- Added a report-local explanation when a perfect metric value covers only a subset of submitted queries. The hint uses exact values and valid eligibility counts, without changing JSON, labels, metrics or finding severity.
- Explained why positive-only judgments can produce conditional MRR@1 = 1 with incomplete query coverage, using a four-row original example. Excluded queries stay unknown; the metric and eligibility rules are unchanged.
- Corrected the first NPZ recipes to preserve undeclared labels instead of preselecting nonrelevant candidates. English/Chinese entry points now offer a public source ZIP, explicit virtual-environment interpreters, and a documented framework-export/core-audit handoff. No metric or default exporter policy changed.
- Pinned the three CI actions to reviewed Node24 commits, replacing Node20-targeted actions that were forced onto Node24. All checkouts disable credential persistence; the existing validation matrix and artifact ZIP settings are retained. See `docs/ci-runtime.md` for scope and acceptance.
- Added an isolated built-wheel gate to the existing cross-platform CI matrix.
- The gate installs only the specified local wheel, verifies the installed package location and versions, and exercises the real module/console entry points plus a synthetic retrieval comparison outside the checkout.
- Runtime code, metric definitions, and the `0.1.0a3` package version are unchanged by this CI improvement.
- Added an explicit source-checkout TREC normalization helper for runs with expendable trailing fields, with validation before creating a new file and source/output hashes. Strict core imports and all judgment policies remain unchanged.
- Added a pinned trec_eval reference job and an executable checker for shared-protocol MRR/NDCG/Recall, with separate probes documenting expected judgment, tie and averaging differences. Core metric definitions remain unchanged.
- Added a BEIR export/evaluation recipe and optional actual-module integration check covering in-place same-ID filtering, default export truncation, qrels transfer, unknown labels and matched-pool reports. No framework or model dependency was added to the core.
- Added a NumPy-only source helper for nonsequential RecBole full-sort exports, with explicit padding/history exclusions, external-token alignment and rejection of unexpected nonfinite eligible scores. A separate pinned actual-helper CI check exercises synthetic scores and the existing RankProbe CLI; labels are not inferred.
- Added a public ReChorus sampled-evaluation capture recipe and optional actual-dataset/runner check for the existing NPZ bridge, addressing the native top-100 presentation CSV's lost candidate/target information and documenting expected pessimistic tie-rule differences.
- Added opt-in source identities to the NPZ exporter for comparisons: explicit unique event IDs and original item tokens avoid false matched pools from independently generated local pseudonyms. Default local identities and unknown-label behavior are preserved. Output hard links to the source NPZ are rejected even with overwrite.
- Added an actual-reader boundary probe and separate NumPy-only helper for the checked base ReChorus full-sort dev/test contract. Column zero is an observed target; stable event IDs, exact native item IDs, target positives, unknown eligible non-target labels and overlapping train/residual/target-copy mask reasons are preserved. The checker verifies safe CSV export and a separate installed-CLI report after raw NPZ rejection; broader model families remain outside scope.
- The ReChorus integration exercises the official default evaluation cache, verifies cached feed identities remain unchanged, and probes a sampled-to-full-sort mode switch without rebuilding the dataset. Guidance requires a fresh prepared dataset after mode/source changes; stale candidates are not repaired or treated as aligned.

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
