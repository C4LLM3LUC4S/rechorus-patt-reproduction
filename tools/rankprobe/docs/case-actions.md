# From a report finding to a checked action

Use this page to decide what a finding lets you change and what to check afterward. It connects existing walkthroughs to execution evidence; each case retains its own declared protocol and scope. Evidence reviewed through 2026-10-21 for `0.1.0a4`.

| Case | Input evidence | Action and recheck status |
| --- | --- | --- |
| [Missing query](#missing-query-synthetic-control) | Original invented TREC runs and judgments | Explicit complete control restores the supplied q2 records; coverage, metric populations and remaining unknowns rechecked |
| [TREC format selection](#trec-format-selection) | Actual archived CLE-LMD run and Round 1 qrels | Explicit-format recovery executed; original inputs preserved |
| [Native protocol alignment](#native-protocol-alignment) | The same actual CLE-LMD input | Separate declared protocol checked against pinned native `trec_eval`; default unknown-label control preserved |
| [Different retrieval candidate sets](#different-retrieval-candidate-sets) | Actual archived CLE-LMD and CLE-DFR runs | Diagnostic and separate two-system native follow-up checked; shared-pool reranking **not executed** |
| [Rank-derived scores](#rank-derived-scores) | Original synthetic scores, rank-only export and planted labels | Controlled consequences checked; historical framework-export recovery **not demonstrated in this case** |
| [Fitted-model score export](#fitted-model-score-export) | Actual public MovieLens ratings and two newly fitted NumPy models | Same observed-item pools checked; deliberate presentation rounding and retained-score recovery executed |

These are developer-run software checks. None establishes human adoption, measured human time saved or model quality. A warning disappearing is not sufficient acceptance: retain source hashes, report version, assumptions and the scope of any metric change.

## Missing query: synthetic control

The [first TREC report](../examples/trec/README.md) gives reordered a higher submitted average after it omits q2. The `query_coverage_mismatch` evidence identifies `q2` in `left_only`. That alone does not establish an export error: check the intended query universe first.

The [recovery step](../examples/trec/README.md#restore-the-omitted-query-and-recheck) uses an explicitly authored complete control, keeps the original inputs/report, and supplies a new comparison command under the unchanged protocol. Both runs now submit three queries, of which q1/q2 are metric-eligible. MRR@2 is 0.25 on each side, NDCG@2 is approximately 0.315464876786, and matched deltas are zero. The coverage mismatch disappears; q3's unknown label, absent q4 and unavailable Recall remain. The lower mean reflects restored coverage, not a measured ranking regression.

This is a developer-executed invented recovery control, not recovery of an actual model export or human adoption. With real data, obtain predictions from that run's own retained source. Do not borrow the baseline's scores, infer them from labels or fill gaps with zeros. If the original evidence is unavailable, record the limitation instead of manufacturing a repair.

## TREC format selection

**Finding.** The archived run has no recognized extension and the qrels file ends in `.txt`. Automatic format selection failed with exit 2 before producing a report.

**Action executed.** Keep both files unchanged and select `--input-format trec --qrels-format trec`. The [public-input recipe](trec-covid-case.md#audit-with-explicit-input-formats) contains the exact source URLs, byte lengths, SHA256 values and commands.

**Recheck.** The explicit-format command completed with exit 0. The retained inputs contain 2,601 submitted candidates across 30 queries; 781 candidate judgments are supplied and 1,820 remain unknown. There are zero assumed nonrelevant candidates. The alpha4 follow-up kept the original files and previous report unchanged. Warnings about judgment coverage remain meaningful; successful parsing does not remove them.

**Acceptance for your file.** Check the input hashes before and after, inspect the supplied/unknown/assumed counts, and open the new HTML and JSON reports. An input error uses exit 2; exit 1 can instead be a completed report that meets your configured findings threshold. See [error recovery](try-it.md) before treating every nonzero status as a parse failure.

## Native protocol alignment

**Finding.** The default unknown-label result and a benchmark's native result can use different judgment and tie rules. Matching their displayed numbers is not a valid reason to alter labels.

**Action executed.** For a separate CLE-LMD experiment, the [NIST convention](https://ir.nist.gov/trec-covid/data.html) supports explicitly assuming absent judgments nonrelevant for these measures. The [reference recipe](trec-covid-case.md#separate-native-reference-check) also aligns equal-score ordering using a new in-memory descending ASCII document-ID view. It preserves original IDs, scores and file bytes. The default report remains separate, with unknown labels unchanged. Qrels completeness is never declared.

**Recheck.** The [reference job for commit `13480c6`](https://github.com/C4LLM3LUC4S/rechorus-patt-reproduction/actions/runs/39425312578/job/118636277902) built pinned NIST source `ba38899cbd4de0fb699b47f39b64ef1c107e4a5c`, passed its upstream self-test and passed 186 CLE-LMD comparisons: 30 per-query values plus one macro, for MRR and linear NDCG at cutoffs 1, 5 and 10. Maximum absolute error was `0.000049639140017987415`, within the declared `0.00005000001` tolerance for native four-decimal output. The job's `trec-eval-reference` artifact includes `rankprobe-trec-covid-result.json` while retained; the source-checkout recipe can reproduce the check.

Under the explicit nonrelevant assumption, changing only tie ordering leaves MRR@10 at `0.3942989417989418` and changes NDCG@10 from `0.22869399948832908` to `0.2286144995215745`; one query changes. The latter rounds to the historical display `0.2286`. This is a protocol explanation, not a model gain or reproduction of the historical executable. MRR and NDCG remain `partial`, with NDCG referencing the known qrels pool; Recall stays unavailable. The default control still has 1,820 unknown and zero assumed nonrelevant candidates.

**Acceptance for another run.** Retain the reason for each protocol choice, the exact native source/build, query universe, cutoffs and numeric tolerance. Check coverage and per-query values as well as the macro. This fixed-input result does not establish universal evaluator parity or authorize missing-label assumptions for other datasets.

## Different retrieval candidate sets

**Finding.** The [two-run public case](trec-covid-case.md#compare-two-real-retrieval-runs) shares all 30 query IDs, but all 30 submitted candidate sets differ. The report returns `not_comparable`, zero matched queries and unavailable matched deltas. Under the default unknown policy, the displayed MRR@10 averages cover 17 queries for CLE-LMD and 29 for CLE-DFR. Subtracting those means would mix populations.

**Choose the experimental question.** First decide the experimental question. Different candidate sets are expected for many complete retrieval systems; this finding alone is not an error in either submission.

| Intended question | Next action | Evidence needed before accepting a result |
| --- | --- | --- |
| Did a reranker improve ordering on the same candidates? | Obtain score-bearing exports from the actual shared candidate stage | Preserve original exports; verify query IDs, per-query candidate sets and shared labels, then compare under the same protocol and metric-eligible query population |
| Which complete retrieval system performs better under this benchmark protocol? | Keep each original run and evaluate both under the separately justified native protocol | Verify both input fingerprints, the same 30 topics, qrels version, cutoffs, gain, missing-label and tie rules; retain per-query and macro results with coverage and assumptions |

Do not intersect the submitted results, invent absent scores or fill unknown labels with zeros to force a same-pool comparison. Such changes would answer a different question. RankProbe's matched-pool delta is not the end-to-end comparison requested in the second row.

**Recheck status.** Original-record parsing, Decimal score sorting and reciprocal-rank calculations independently confirmed the diagnostic and different eligible populations. The separate [two-system native follow-up](trec-covid-case.md#complete-retrieval-follow-up-on-both-original-runs) has now passed 372 comparisons on the original files. It preserves the default unknown-label controls and unavailable matched-pool delta. No shared-candidate reranking export has been executed; the numerical difference under the separate protocol does not establish statistical significance, model improvement or human benefit.

## Rank-derived scores

**Finding.** In the [synthetic score-provenance walkthrough](../examples/score-provenance/README.md), converting ranks into reciprocal-rank scores removes an original score tie. A valid six-column file does not establish where its scores came from, and a structural match does not verify their provenance.

**Action exercised in the control.** Compare the retained original scores with the rank proxy before adding any labels. Keep the separate planted-label experiment explicit and repeat it under both tie policies. The four main walkthrough commands use independently constructed files. A separate [fixed-source converter handoff control](../examples/score-provenance/README.md#check-conversion-completion-before-auditing-its-output) executes the upstream conversion script without installing the Pyserini package or running search.

**Recheck.** All four documented command paths were executed: the unlabeled comparison, the rank-only rejection and the two planted-label comparisons. The original has one tie group and the proxy has none. Both retain three unknown candidates and zero assumed nonrelevant candidates before the separate planted oracle is supplied; no metric delta is available then. Rank-only input is rejected with exit 2 before output. With the planted labels, MRR@1 and NDCG@1 deltas are zero under input-order ties and +1 under ascending-ID ties. These are controlled encoding effects, not evidence of a real model improvement or an upstream defect.

**Action for an actual export.** Locate retained score-bearing evaluation objects or an original scored export and follow the walkthrough's [source-selection guidance](../examples/score-provenance/README.md#choose-a-source-that-retains-score-evidence). Export original IDs, scores and ordering into a new file; keep its source provenance alongside it. Recheck query/candidate identities, score ties and judgment counts before interpreting metrics. Rank-only data cannot recover lost score ties, and rounded output cannot restore precision already discarded. If the original score evidence is unavailable, record that limit; changing the file extension or synthesizing new scores does not repair it.

**Conversion handoff recheck.** The pinned converter completed normally on the rank-only fixture. With a later invalid rank, it exited 1 after leaving a one-query prefix that RankProbe could still parse. A corrected source copy and fresh output retained both intended queries. Require upstream success and compare expected query-item records before auditing: RankProbe's exit-code rules apply to its own process, and parsing a prefix does not prove export completion. Both prefix and complete-copy audits preserved unknown labels and left metrics unavailable.

Recovery of a real framework export and any resulting human benefit remain unverified. These controlled cases establish what to inspect and why, rather than a completed real-world repair.

## Fitted-model score export

The separate [MovieLens score path](../examples/movielens-scores/README.md) uses 80,000 actual training ratings and the unchanged 20,000 held-out observed pairs. Two fitted models score the same 459 query pools. The experiment explicitly maps observed ratings to binary judgments; missing ratings are not filled, and full-catalog qrels completeness is not asserted.

**Finding and action.** An intentionally rounded presentation of actual factor scores increases tie groups from 6 to 3,505. NDCG@5 rises while MRR@5 falls despite unchanged fitted parameters and judgments. Inspect the score export, then use the retained exact capture to write a new faithful CSV instead of attributing that change to a model.

The [manual action path](../examples/movielens-scores/README.md#inspect-recover-and-recheck-without-refitting) separates that re-export from the automated experiment: verify the retained capture hash, use `--recover` to a fresh directory without fitting, stop on failure, then compare the new CSV against the exact export under the same protocol. Check file identity as well as matched metrics; the helper's format check cannot establish capture provenance.

**Recheck.** The recovered CSV is byte-identical to the exact original, all six matched deltas are zero, and source hashes stay unchanged. Independent per-query/macro/delta calculations passed 11,058 comparisons; a scores-only control keeps all 20,000 candidates unknown. This is an executed public-data software case with a deliberate loss control, not a historical user incident, a production retrieval stage, or a human benefit measurement. The fixed-commit CI records its platform scope separately.
