# Synthetic retrieval audit: an apparent gain from dropping a query

These files are original, invented examples, distributed under the repository's MIT license. They contain no benchmark data, private predictions, real user records, or reproduced model results. Their purpose is to make a small evaluation mistake easy to inspect by hand.

## The files

`baseline.run` submits three queries. `reordered.run` has the same candidate scores for shared queries, reverses the file order of the tied documents for q1, and omits q2. `judgments.qrels` supplies the labels:

| Query | Baseline candidates in file order | Reordered candidates in file order | Judgments |
| --- | --- | --- | --- |
| q1 | doc_b=1.0, doc_a=1.0 | doc_a=1.0, doc_b=1.0 | doc_b relevant, doc_a nonrelevant |
| q2 | doc_e=0.9, doc_f=0.8 | Missing | doc_e/doc_f nonrelevant; unreturned doc_d relevant |
| q3 | doc_x=0.8, doc_y=0.5 | Same | doc_x explicitly unjudged (-1), doc_y relevant |
| q4 | Missing | Missing | doc_z relevant |

The rank column is a valid nonnegative integer but does not order the results. Scores and the declared tie policy do. The run tag is only a text field and does not separate systems within a file.

## Run the comparison

From the package root, after installation:

```sh
python -m rankprobe compare --run baseline=examples/trec/baseline.run --run reordered=examples/trec/reordered.run --qrels examples/trec/judgments.qrels --cutoffs 1,2 --out reports/trec-default
```

Open `reports/trec-default/report.html`. The default is ascending item ID within exact score ties, linear NDCG gain, and unknown judgments preserved. Inspect query coverage before comparing the headline metrics:

| Check | Expected result |
| --- | --- |
| Submitted queries | baseline=3, reordered=2 |
| qrels-only queries | baseline has q4; reordered has q2 and q4 |
| Default MRR@2 | baseline=0.25, reordered=0.5 |
| Default NDCG@2 | baseline≈0.315464876786, reordered≈0.630929753571 |
| Eligible metric queries at k=2 | baseline: q1,q2; reordered: q1 |
| Matched-pool MRR@2 | both=0.5, delta=0 |
| Matched-pool NDCG@2 | both≈0.630929753571, delta=0 |

For q1, ascending IDs put the nonrelevant doc_a first, so reciprocal rank is 1/2 and NDCG@2 is `1/log2(3)`. Baseline's q2 retrieves no relevant document, so both values are zero. Averaging q1 and q2 halves those values. The reordered run's missing q2 is excluded, not imputed as zero. Its apparent gain therefore comes entirely from a different query population.

For q3, an unknown judgment occurs before the first known relevant item, excluding that query from MRR@2; the unknown candidate label also excludes it from NDCG. The absent q4 is reported but not inserted into either average. These are partial-coverage metrics, not full-query benchmark results. The matched-pool section includes q1/q3 structurally, but only q1 is metric-eligible under this protocol.

## Isolate the tie convention

```sh
python -m rankprobe compare --run baseline=examples/trec/baseline.run --run reordered=examples/trec/reordered.run --qrels examples/trec/judgments.qrels --tie-policy input --cutoffs 1,2 --out reports/trec-input-order
```

Now q1 puts doc_b first in baseline and second in reordered. The matched-pool MRR@2 is 1 versus 0.5; matched-pool NDCG@2 is 1 versus approximately 0.630929753571. Scores did not change. This deliberately chosen input-order convention makes row order affect the reported score. It is not evidence that one system learned more.

## Make the unknown-label assumption explicit

```sh
python -m rankprobe audit examples/trec/baseline.run --qrels examples/trec/judgments.qrels --unjudged nonrelevant --cutoffs 1,2 --out reports/trec-assume-nonrelevant
```

This changes q3's unknown doc_x into zero under an explicit assumption. All three submitted queries become eligible: MRR@2 is 1/3 and NDCG@2 is approximately 0.420619835714. The report records the assumption. It does not establish that doc_x was judged nonrelevant.

Do not pass `--qrels-complete` with these qrels. The explicit `-1` contradicts that assertion and is rejected, even if `--unjudged nonrelevant` is also selected. Recall therefore remains unverified in the normal walkthrough.

Use a new output directory for each command. To rerun into the same directory, add `--overwrite`; unrelated files are retained. The expected warnings do not fail the default `--fail-on error` invocation. See [the input contract](../../docs/input-format.md) for `.txt` files and [the first-use guide](../../docs/try-it.md) for trying your own export.
