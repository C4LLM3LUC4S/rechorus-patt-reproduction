# Changelog

## 0.1.0a4 — MRR eligibility from known prefixes

- Added a bounded fractional-label linear NDCG reference case. The original binary-exact fractional grades stay unchanged; only an oracle copy is scaled to integer gains, with explicit mapping and input-integrity controls. Fractional exponential gain and extreme-value parity remain outside this check.
- Unsupported-extension errors identify the appropriate `--input-format` or `--qrels-format` CLI flag alongside the Python argument. Input parsing and format selection remain explicit.
- MRR can include a query when the first relevant rank is already determined by known labels, even if later candidates remain unknown. An unknown before that first relevant item still excludes the query; fully known top-k lists with no relevant item contribute zero.
- Missing labels, assumption counts, NDCG, Recall and exact tie-bound rules are unchanged. Broader MRR coverage changes the eligible subset and can change its average; it is not evidence of improved ranking scores.
- MRR results record `eligibility_rule=known_first_relevant_prefix` in JSON and HTML coverage details. MRR deltas require the same explicit rule on both sides; reports without it must be recomputed from their original inputs before comparison.
- This refines the deliberately conservative 0.1.0a3 eligibility contract. Preserve earlier reports with their version and do not subtract old and new conditional averages.

## Unreleased — installation, explicit input conversion and reference checks

- Explain the reranking versus complete-retrieval follow-up directly in candidate-set warning actions, without encouraging candidate intersections, invented scores or judgment changes to force matching. Metrics, JSON findings and protocol selection are unchanged.
- Add an optional fixed public CLE-LMD/CLE-DFR native pair check: verify both original runs under a separately declared complete-retrieval protocol, preserve default unknown-label and same-pool controls, and record native rounding separately.

- Connect public case findings to executed actions, recheck evidence and still-pending follow-ups. Separate real public inputs from the synthetic score-provenance control.
- Include the actual physical parser-stop line in CSV parsing errors, including multiline records and headers, with quoting/delimiter recovery guidance; do not label a stale `DictReader` position as the malformed record's start.
- Report JSONL parser-depth failures with a file, line and flat-export recovery route, returning CLI exit 2 instead of an uncaught traceback/exit 1; preserve source bytes, supported nested metadata and unknown labels.
- Mark exact tie bounds as partial when they cover only eligible submitted queries or a limited metric reference, and include excluded-query scope instead of implying whole-run coverage.
- Give a direct recovery message when `--out` is a file, and diagnose report-name directories before suggesting `--overwrite`; existing files and directories remain untouched.
- Keep enough digits in HTML when a near-whole metric or comparison delta would otherwise display as an exact whole number; JSON metric values and calculations are unchanged.
- Reserve both report filenames before a no-overwrite write, so concurrent jobs cannot both succeed at the same output path and silently replace each other's report. A late collision preserves the other writer's file and uses the existing recovery message.
- Exercise invalid-input rejection, corrected retry and existing-report preservation through both freshly installed entry points. Add first-use recovery guidance for interpreter selection, explicit TREC formats, invalid scores and existing reports.
- Preserve accepted integer scores in the documented MTEB converter instead of rejecting values that the core CSV reader now handles exactly. Check malformed-input rejection before any CSV is written and a clean retry of the actual recipe, including distinct adjacent large integers and unknown labels.
- Exercise RecBole's official dataset preparation and full-sort evaluation loader on eight original interactions, including a dataset user absent from the test population. Verify requested-user selection, actual batch masks and positive pairs before the existing score/export/report checks; keep this optional native environment isolated from the core.
- Identify nested diagnostic entries by their query ID in the disclosure title, so users can select the affected query before opening its full evidence. Titles remain escaped; metric calculations and JSON are unchanged.
- Add a pinned native gdeval source-policy check on original miniature inputs for nonpositive judgments, topic selection and default versus `-c` averaging. It does not establish RankProbe metric parity, historical 2011 equivalence or an automatic grade conversion.
- Accept an optional UTF-8 BOM in the BEIR source preflight while retaining exact headers and repeated-pair checks; verify native loading and mapped TREC transfer preserve declared grades while the original BOM source bytes stay unchanged.
- Check ordinary BEIR split TSV pair uniqueness before loading it into mappings, with a read-only preflight and pinned native controls for row-order-dependent judgment overwrites. Preserve source rows rather than selecting a judgment automatically.
- Keep BEIR split loading independent with a fresh-loader recipe and fixed-source native controls for merged judgments, mutable returned references and disjoint-query failures. The core does not detect consistently stale inputs or alter source judgments.
- Link TREC judgment recovery errors to the public alpha input guide so installed users can find it from a different working directory; parsing and rejection rules are unchanged.
- Explain source-specific negative TREC judgments in errors and the input guide. Unsupported grades remain rejected even with missing-label or completeness options; no annotations are dropped or remapped.
- Add a tested local CI orchestration recipe that handles findings failures before returning their original status, rejects stale output, and distinguishes invalid runs and partial metrics. The example lists local report files; host artifact retention remains an explicit integration step.
- Explain the ordinary-versus-subtopic judgment boundary in TREC duplicate errors and the input guide. Four-column shape alone cannot identify intent semantics; valid nonzero ordinary iterations and existing accepted labels remain unchanged.
- Record a path-free core-source identity in CLI reports so unreleased builds sharing a version can be distinguished. Per-file and aggregate hashes describe available source bytes, not loaded bytecode, the complete environment or evaluation quality; unreadable source is recorded as unavailable.
- Add separate Windows/Ubuntu Python 3.15 core source-build and isolated-wheel installation checks, with versioned aggregate artifacts. The existing full-test matrix is unchanged; adapters, native frameworks and Python 3.14 are outside this added coverage.
- Add an original score-provenance case linked to Pyserini's rank-only export and reciprocal-rank conversion, with separate unknown-label and planted-label controls; include its TSV input in source distributions.
- Select a small declared RecBole user subset from the current nonsequential evaluation loader, with guidance for requested users absent from that split and explicit population boundaries.
- Add a fingerprinted real TREC-COVID run-pair walkthrough and explain why expected end-to-end candidate changes, same-pool comparison status and metric eligibility answer different questions.
- Preserve representable small exp2 gain ratios against large grades using split exponent scaling, without changing the linear rule or the existing large-branch calculation for grades at least one.
- Explain CSV field-size failures, including unused text/metadata columns, with prediction- and qrels-specific recovery guidance that preserves supplied labels and the parser limit.
- Add direct RankProbe package and first-report links to both introductions and the trial invitation, making the alpha's entry point explicit within the shared reproduction repository.
- Explain why a positive singleton candidate pool can have NDCG@1 = 1 without testing the ordering of alternatives, with zero, unknown and independent-qrels contrasts.
- Add a bounded ReChorus repeated-negative comparison alongside the existing tie probe. Original synthetic duplicate columns expose column-rank versus unique-item differences; normal exported labels remain unknown, with a separate planted-label control. The guide links the dataset-specific sampler source without changing the core or a benchmark protocol.
- Explain RecBole comparison scope using the pinned evaluator's held-out positive counts and user average. A selected-user export must align its users and judgments before comparison; a native Recall value does not justify declaring complete qrels or changing unknown labels.
- Diagnose malformed Unicode query/item IDs during input validation. JSONL errors now identify the source, line and field instead of failing later while writing UTF-8 reports; direct API qrels receive the same Unicode check. Valid identifiers are preserved without normalization.
- Reject unsupported numeric objects in `Row` and `Protocol` with a field-specific error. Previously some `numbers.Real` thresholds, including `Fraction` and NumPy scalars, could complete an audit and then fail JSON report serialization. Supported integer values are retained without float conversion; the core gains no dependency.
- Clarified BEIR's empty-query run-file boundary: preserve intended evaluation IDs separately and check them against predictions and qrels. Broader judgment scope cannot justify automatic zero filling, and queries absent from both files cannot be recovered by an audit.
- Preserved accepted integer scores, grades and relevance thresholds instead of rounding them through float. Adjacent large integers now retain ordering, label conflicts and threshold decisions; NDCG also avoids rounding an integer when mixed with an integer-valued float. Decimal/scientific notation and metric results remain floating point. Recompute affected older reports from their original inputs before comparison.
- Prevented console-encoding failures from turning a completed audit into a traceback. Report paths and domain errors use escaped text only when the output stream cannot encode a character; UTF-8 output, files and finding-based exit statuses are preserved. Output I/O failures still propagate.
- Made BEIR/RecBole/ReChorus export-to-core handoffs explicit across working directories. ReChorus sampled conversion can use its NumPy-only source helper in the existing model environment; the core audit consumes the recorded absolute file paths without installing a model framework. RecBole no longer asks for an unnecessary RankProbe installation in the model environment.
- Kept the real TREC-COVID walkthrough on the first-report virtual-environment interpreter, with explicit Windows and macOS/Linux commands. Copying the audit command no longer relies on shell activation or the system Python having RankProbe installed.
- Added a complete, isolated installation recipe for the optional MTEB check. It shares 19 dependency requests with CI, which records installed package names/versions and exercises the documented CLI. The source distribution includes the dependency file; the requests and snapshot are not a full dependency lock.
- Added an optional, isolated MTEB native workflow check on original in-memory inputs. It exercises real prediction saving, the copied guide conversion and RankProbe reports, with offline runtime, separate caches and sparse-label controls; the core dependencies and metric contracts are unchanged.
- Added a source-grounded MTEB retrieval prediction recipe using the existing CSV interface. It makes model-output directories, metric-cache bypass, subset/split selection, independent judgments and pre-scoring candidate scope explicit; no framework dependency, core loader or native-parity claim was added.
- Published the complete trial feedback record and linked it from the first-report walkthrough. It separates prior knowledge, concrete actions and repeat use from intent, and active human effort from machine waits; unmeasured times and absent comparison baselines cannot support time-saving claims. No adoption results are implied.
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
