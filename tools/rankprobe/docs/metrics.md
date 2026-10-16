# Metric semantics

RankProbe exposes its evaluation choices so that a change in protocol is visible. It does not promise numerical parity with every framework. Check the JSON protocol and metric scope before quoting a value.

## Ordering, relevance, and duplicate rows

Higher scores rank first. The default tie policy, `item_id`, sorts tied item IDs in ascending string order. The optional `input` policy preserves their order in the input file. Neither policy means the model distinguished tied items. Other evaluators can use different rules; `trec_eval` uses descending document IDs in the historical case linked in [known-cases.md](known-cases.md).

A relevance value greater than zero is relevant for MRR and Recall. NDCG uses graded relevance with the chosen gain function:

- `linear`: `gain(r) = r`.
- `exp2`: `gain(r) = 2**r - 1`.

TREC qrels `-1` and Python qrels `None` record an explicit absence of a source judgment. They do not override a known inline label or become zero by default. Known qrels remain authoritative; conflicting known inline labels fail validation. An explicit unknown anywhere in the qrels contradicts `qrels_complete=True`, even if that document was not retrieved. Only the separate `unjudged=nonrelevant` assumption can resolve an otherwise unknown candidate as zero; it does not make the qrels complete.

The summary's `judged_candidates` counts unique candidates with known supplied labels. `resolved_candidates` also includes values introduced by explicit assumptions or the complete-qrels closure. `unknown_candidates` counts candidates still unresolved after applying the protocol. Inspect the assumption counts before interpreting label coverage.

Duplicate `(query_id, item_id)` entries are diagnosed before unique-item evaluation. The declared policy keeps the maximum score for an item. Conflicting relevance is evidence of inconsistent judgments; a duplicate's score difference does not establish which row came from a valid pipeline. Raw-row versus unique-item comparisons are sensitivity diagnostics. Do not silently replace a benchmark's frozen primary procedure with deduplicated scores.

## MRR@k

For each query, reciprocal rank is `1 / rank` for the first relevant item within cutoff k and zero if none is found in that cutoff. MRR is the arithmetic mean across eligible queries; each query has equal weight.

Under `unjudged=unknown`, scan the declared top-k ordering until the first known relevant item. If all earlier labels are known, its reciprocal rank is determined and the query is eligible; unknown labels after it remain unknown and cannot change that first rank. If an unknown occurs first, exclude the query because it could conceal an earlier relevant item. A fully judged top-k list with no relevant item contributes zero. For example, `[1, unknown]` has RR@2 = 1, while `[unknown, 1]` is unresolved. Relevance must be strictly above the declared threshold.

This is the `known_first_relevant_prefix` rule introduced in `0.1.0a4`. Version `0.1.0a3` deliberately required every top-k label to be known, excluding even `[1, unknown]`. Keep earlier reports with their original version. MRR deltas now require the same explicit `eligibility_rule` on both sides; recompute older reports from the original inputs before comparing them. An expanded eligible subset can change a conditional average without any ranking change.

An MRR status of `ok` can coexist with unknown labels after the first relevant item: the stated MRR is determined for all submitted queries, not every candidate's judgment. NDCG, Recall and exact tie bounds retain their own requirements. Treating unknown candidates as nonrelevant remains a separate explicit protocol choice. Read the reported eligible-query counts before interpreting a partial mean; excluded queries are not zeros.

### Positive-only labels

When the only known judgments are relevant positives, default MRR@1 eligibility selects queries whose first item is a known positive. If that subset is nonempty, its MRR@1 is necessarily 1. Unknown-first queries are excluded, so this does not mean the whole run ranked perfectly. In the [four-row synthetic example](../examples/README.md), MRR@1 is 1.0 with `partial` status and only 1 of 2 queries eligible; NDCG@1 and Recall@1 are unavailable. Read the value together with its coverage. Do not turn excluded queries into zeros or call the eligible fraction HitRate. Standalone audit reports place a coverage reminder beside an exactly perfect metric when only a subset of submitted queries is eligible.

## NDCG@k

`DCG@k = sum(gain(relevance_at_rank) / log2(rank + 1))` for ranks starting at one. NDCG divides DCG by the ideal DCG under the report's judgment scope. Queries with unknown candidate labels are not scored under the default unknown policy.

The scope is part of the result:

- **Candidate pool:** the ideal ordering uses known labels among supplied candidates. This measures ordering inside that pool and can hide missing relevant items.
- **Known qrels pool:** independent judgments can include items not retrieved. The ideal ordering uses that declared judgment pool. Incomplete qrels still do not establish full-corpus relevance.

When ideal DCG is zero, the query contributes zero by this implementation's declared convention. No relevant judged item is different from an unjudged query. Inspect coverage and warnings before interpreting either.

Gain calculations use scaled ratios to avoid overflow and cancellation. For very small exponential gains, the stable `expm1(x) / x` ratio preserves distinct finite grades, including subnormal values. This is a numerical implementation of the declared gain function, not a change in relevance meaning or a benchmark claim.

## Recall@k

Recall uses the number of distinct relevant items retrieved in the top k divided by the number of relevant items in the independent qrels. It is reported only when `--qrels-complete` explicitly declares a complete denominator for the evaluated queries. That flag is not a measured fact.

Counting only positives present in a truncated prediction file can make Recall artificially equal to one. RankProbe does not rename that quantity full Recall. Queries missing from the independent judgments remain unresolved. Queries with a known zero relevant denominator are excluded from Recall; inspect the eligible-query count.

## Query coverage

Macro averages use query IDs actually present in the submitted predictions.
When qrels contain additional queries, the report lists their count and examples
and marks metrics as partial. Those queries are not silently scored as zero:
the judgment file might intentionally cover a larger dataset. Confirm the
intended query universe before quoting the aggregate. Two runs omitting the
same queries can match each other while both have incomplete qrels coverage.

## Ties and sensitivity bounds

The audit keeps strict score ordering fixed and examines the effect of permuting candidates within exact-score tie groups. It reports metric minima and maxima for the supported metrics under those constraints. Graded relevance is respected for NDCG.

These bounds describe order sensitivity of this input and protocol. They are not confidence intervals, significance tests, or possible training outcomes. They are per-metric envelopes: the order giving the best value for one metric does not imply a common optimal order for every reported metric. Unknown judgments and coverage rules still apply.

Exact ties mean equal parsed numeric values. Near-ties caused by score rounding, quantization, or serialization need separate analysis; this version does not infer a tolerance from the data.

## What a comparison establishes

Comparisons inspect query coverage, unique candidate sets, and known judgments. A metric difference over different query or candidate pools mixes multiple causes. Even when those files agree, experiment version, training history, tokenization, split construction, and tuning remain manual checks. Read [limitations.md](limitations.md) before using a report in a paper or release.
