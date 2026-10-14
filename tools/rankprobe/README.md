# RankProbe

**Find out when a ranking score depends on ties, duplicated candidates, or a changed evaluation pool.**

RankProbe is a local, model-free audit tool for recommendation and retrieval experiments. Give it candidate scores and relevance judgments; it produces a readable HTML report and machine-readable JSON with examples, metric assumptions, and sensitivity results. No model inference, cloud account, or API key is needed. The core uses the Python standard library.

[中文说明](README.zh-CN.md) · [Input contract](docs/input-format.md) · [Metric semantics](docs/metrics.md) · [CLI / Python API](docs/usage.md) · [Five-minute trial](docs/try-it.md) · [Limitations](docs/limitations.md)

## Start in two minutes

Requires Python 3.10 or newer. Install from this checkout; no PyPI release is claimed.

The alpha is currently incubated in an isolated directory of the existing
reproduction repository. To obtain this checkout:

```sh
git clone --branch feature/rankprobe-alpha https://github.com/C4LLM3LUC4S/rechorus-patt-reproduction.git
cd rechorus-patt-reproduction/tools/rankprobe
```

```sh
python -m pip install -e .
python -m rankprobe demo --out reports/demo
```

Open the generated `report.html`. To use a supplied example:

```sh
python -m rankprobe audit examples/ties.csv --cutoffs 1,5 --out reports/ties
python -m rankprobe audit examples/ties.csv --tie-policy input --cutoffs 1,5 --out reports/ties-input
python -m rankprobe compare --run baseline=examples/clean.csv --run changed=examples/mismatch.csv --out reports/compare
```

Reports are written to the selected output directory; existing report files are refused unless `--overwrite` is explicit. `report.json` is intended for programmatic inspection; `report.html` is self-contained and can be opened offline. Reports include input identifiers and example rows, so review them before sharing.

## What it checks

| Question | Evidence in the report |
| --- | --- |
| Could tied scores change the result? | Exact-score tie groups, input-order versus deterministic ranking, and metric bounds across permutations within ties |
| Does a query list the same item repeatedly? | Duplicate pairs, score or relevance conflicts, and a declared deduplication policy |
| Are two runs being evaluated on the same cases? | Query coverage, per-query candidate sets, relevance differences, and evidence that requires manual follow-up |
| What assumptions produced these metrics? | Cutoffs, gain, tie policy, unjudged treatment, relevance source, and denominator scope |

A tie is often legitimate. Repeated candidates can come from a declared sampling protocol. RankProbe reports their effects; it does not label every occurrence a bug or silently claim one universal correct score.

## Bring your own predictions

One CSV row is a scored `(query_id, item_id)` pair. A query is one ranking event, which may be a search query, recommendation target, or reranking request. Multiple events for the same user need separate query IDs.

```csv
query_id,item_id,score,relevance
q1,doc_a,0.9,1
q1,doc_b,0.7,0
q2,doc_c,0.4,2
```

Scores must be finite numbers; larger scores rank first. Relevance is nonnegative, with `> 0` treated as relevant by MRR and Recall. Missing relevance is **unknown**, unless you explicitly choose `--unjudged nonrelevant`. JSONL uses the same field names.

```sh
python -m rankprobe audit predictions.jsonl --out reports/my-run
```

Independent judgments use a CSV or JSONL file with `query_id,item_id,relevance`. Provide complete qrels only when you can justify that assumption:

```sh
python -m rankprobe audit examples/unjudged.csv --qrels examples/qrels.csv --qrels-complete --out reports/qrels
```

TREC retrieval outputs can be read directly, without reformatting scores:

```sh
python -m rankprobe audit results.run --qrels judgments.qrels --out reports/retrieval
```

For `.txt` files, select `--input-format trec` and `--qrels-format trec` explicitly. The run's score determines ordering; its declared rank is ignored. A qrels relevance of `-1` remains unknown. Declaring complete qrels while an explicit unjudged entry remains is rejected. See the [synthetic retrieval walkthrough](examples/trec/README.md) for a case where dropping a difficult query doubles MRR without improving the common queries.

MRR and NDCG are reported with their evaluated-query counts and scope. Recall is available only with explicitly declared complete qrels. Candidate-pool metrics do not measure full-corpus retrieval quality. A completeness flag records your assertion; RankProbe cannot verify it from scores alone.

## Existing framework outputs

Export a small ReChorus-style NPZ locally with the optional NumPy adapter:

```sh
python -m pip install -e ".[adapters]"
python scripts/export_rechorus.py local_test_predictions.npz --out local_export.csv --positive-index 0 --other-candidates nonrelevant --limit-queries 100
python -m rankprobe audit local_export.csv --out reports/local-export
```

The adapter has an explicit one-positive-column assumption. It remaps item IDs, omits user IDs, and treats each matrix row as a distinct query. Read [adapter assumptions](docs/adapters.md) before comparing exports. Synthetic fixtures are included; private predictions, MovieLens data, and third-party code are not redistributed.

RankProbe is an independent evaluator, not a compatibility wrapper for MTEB, RecBole, or ReChorus. Tie rules and metric definitions can differ. For example, its default `item_id` tie rule is ascending string order, whereas `trec_eval` uses a different convention. See [known public context](docs/known-cases.md).

## Development

```sh
python -m pip install -e ".[dev,adapters]"
python -m pytest
python -m build
```

The CI configuration targets Python 3.10, 3.12, and 3.13 on Ubuntu and Windows. A configuration file alone is not evidence that those remote jobs passed; inspect the workflow runs for the checked commit.

This is an early `0.1.0a2` implementation. The [verification record](docs/verification.md) distinguishes executed checks from pending evidence. There are no claimed external adopters, revenue, benchmark certification, or published research results. [The validation plan](docs/validation-plan.md) and [roadmap](docs/roadmap.md) describe what would establish practical value. Contributions should add an independently checkable example and document changed semantics. Please report problems with a small synthetic input instead of uploading private data.

## License and citation

See [LICENSE](LICENSE). Original synthetic examples follow this repository's license; framework outputs and datasets retain their own terms. A [CITATION.cff](CITATION.cff) file describes this software without claiming a paper or DOI.
