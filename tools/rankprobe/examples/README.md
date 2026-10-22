# Small cases with inspectable answers

All files here were created for RankProbe. They contain no user activity, downloaded benchmark records, or private model predictions. The same repository license applies.

Run commands from the repository root. The examples deliberately contain audit findings; a reported risk does not mean the command failed to run.

| File | Expected observation |
| --- | --- |
| `clean.csv` | Two queries, six rows, no repeated candidates or exact-score ties. MRR@1 = 0.5; MRR@5 = 0.75; linear-gain candidate-pool NDCG@5 = `(1 + 1/log2(3))/2`, approximately 0.815465. |
| `ties.csv`, `ties.jsonl` | Every score within a query is tied. Input order places the positive first; ascending item-ID order puts it third. MRR@5 can be any tie-order value between 1/3 and 1. The envelope is sensitivity, not a confidence interval. |
| `duplicates.csv` | `q1/a` is repeated with equal score; `q2/e` is repeated with different scores. Deduplicating q1 moves its positive from raw-row rank 3 to unique-item rank 2. Neither duplicate justifies changing a published primary protocol silently. |
| `mismatch.csv` | Compared with `clean.csv`, q2 disappears, q3 is added, and q1 loses candidate c. A full-run metric difference would mix model and pool changes. |
| `label-conflict.csv` | Same candidates as `clean.csv`, but q2/d changes relevance. A run comparison should report a judgment mismatch. |
| `unjudged.csv` | Scores without labels. Metrics requiring relevance must not be invented. |
| `positive-only.csv` | Four rows, two queries, only observed positives labeled. MRR@1 = 1.0 with `partial` status and 1 of 2 queries eligible; the unknown-first query is excluded. NDCG@1 and Recall@1 are unavailable. |
| `qrels.csv` | Independent judgments add an unretrieved positive for q1. Declaring these complete permits Recall; Recall@5 is `(1/2 + 1)/2 = 0.75`, rather than 1.0 from counting only positives in the retrieved pool. |
| [score-provenance/](score-provenance/README.md) | A rank-only conversion can hide retained score ties. Separate unknown-label and planted-label controls distinguish score provenance, tie policy and metric changes. |

```sh
python -m rankprobe audit examples/clean.csv --out reports/clean
python -m rankprobe audit examples/ties.jsonl --cutoffs 1,5 --out reports/ties
python -m rankprobe audit examples/duplicates.csv --out reports/duplicates
python -m rankprobe audit examples/positive-only.csv --cutoffs 1 --out reports/positive-only
python -m rankprobe audit examples/unjudged.csv --qrels examples/qrels.csv --qrels-complete --out reports/qrels
python -m rankprobe compare --run clean=examples/clean.csv --run changed=examples/mismatch.csv --out reports/mismatch
python -m rankprobe compare --run clean=examples/clean.csv --run changed=examples/label-conflict.csv --out reports/labels
```

`qrels-complete` is a justified assertion for this invented miniature example. In a real corpus, availability of a qrels file by itself does not establish complete relevance judgments.

In `positive-only.csv`, `alpha_positive_first` has a known relevant item first, while `beta_unknown_first` has an unjudged item first. Excluding the latter leaves MRR@1 = 1.0 over only 1 of 2 queries. This is conditional coverage, not whole-run perfection or HitRate; an excluded query's unknown first item could still be relevant. See [positive-only MRR semantics](../docs/metrics.md#positive-only-labels).
