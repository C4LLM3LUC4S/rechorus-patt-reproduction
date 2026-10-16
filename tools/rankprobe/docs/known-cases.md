# Public context and independent examples

Sources checked on 2026-10-15 and 2026-10-16. The examples in this repository are original miniature constructions, not benchmark data or copies of another project's reproduction code.

## A retrieval export can appear better after losing a query

The original [TREC-style example](../examples/trec/README.md) contains two runs with identical scores on their shared queries. One run drops a difficult query and reverses the file order of two equal-score documents. Under the default ascending-ID tie rule, its unrestricted MRR@2 rises from 0.25 to 0.5. On matching queries and candidate sets, both runs score 0.5; the apparent gain comes from coverage, not better scores.

The same files contain an explicitly unjudged document and a query present only in qrels. The walkthrough shows how those affect metric eligibility and why a complete-qrels assertion is invalid here. This is an invented diagnostic example, not a new upstream bug, a dataset reproduction, or evidence of model improvement. All files can be shared under this repository's license.

## A known MTEB tie-order regression

[MTEB issue #5092](https://github.com/embeddings-benchmark/mteb/issues/5092) documents a constant-score case in which metric paths used inconsistent tie handling. Maintainers confirmed the report, merged [PR #5136](https://github.com/embeddings-benchmark/mteb/pull/5136), and later discussed comparability of older results. The issue is closed. This is a known, addressed upstream problem, not a new vulnerability discovered by RankProbe.

Our `examples/ties.csv` illustrates the general order-dependence mechanism using invented IDs and scores. It does not reproduce the WebLINX benchmark or verify any current MTEB release. RankProbe's ascending-ID rule differs from `trec_eval`'s descending-ID rule; equal output is not promised.

For an existing MTEB retrieval prediction file, the [bounded export recipe](mteb-workflow.md) explains which scores can enter the audit and which context must be retained separately. It addresses file selection, cache and scope boundaries; its source inspection and original shape checks are distinct from running MTEB or reevaluating historical results.

## Recommendation protocols are configurable

The official [RecBole evaluation settings](https://recbole.io/docs/user_guide/config/evaluation_settings.html) describe full-item and sampled evaluation, including uniform and popularity-based negative sampling. Those are distinct declared protocols. RankProbe can compare the exported candidate pools; it cannot reconstruct an omitted corpus, infer the sampling distribution, or certify split construction from scores.

RecBole already includes evaluation infrastructure. RankProbe's intended contribution is an independent, inspectable audit of exported evidence, not a claim that recomputing standard metrics is novel.

## The local ReChorus motivation

The existing [PAtt/ReChorus reproduction](https://github.com/C4LLM3LUC4S/rechorus-patt-reproduction) records its own fixed evaluation assumptions. It motivated a reusable interface that no longer assumes exactly 100 candidates or treats an item column as positive without an explicit adapter option. Existing code was inspected for context; the adapter is independently implemented.

No private run matrices, original MovieLens data, or upstream implementation snippets are included here. ReChorus and PAtt remain separate projects under their own terms.

## Naming and existing tools

RankProbe is independent of the existing [RankAudit project](https://github.com/m-np/rankaudit). It does not claim that ranking diagnostics or metric recomputation are a new market. The distinct name avoids confusing the two tools.
