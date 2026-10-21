# RankProbe

**Find out when a ranking score depends on ties, duplicated candidates, or a changed evaluation pool.**

RankProbe is a local, model-free audit tool for recommendation and retrieval experiments. Give it candidate scores and relevance judgments; it produces a readable HTML report and machine-readable JSON with examples, metric assumptions, and sensitivity results. No model inference, cloud account, or API key is needed. The core uses the Python standard library.

For a trial, share the [RankProbe package page](https://github.com/C4LLM3LUC4S/rechorus-patt-reproduction/tree/feature/rankprobe-alpha/tools/rankprobe) and [first-report walkthrough](https://github.com/C4LLM3LUC4S/rechorus-patt-reproduction/blob/feature/rankprobe-alpha/tools/rankprobe/docs/try-it.md). Both links open the alpha's own directory inside the reproduction repository.

[中文说明](README.zh-CN.md) · [Input contract](docs/input-format.md) · [Metric semantics](docs/metrics.md) · [CLI / Python API](docs/usage.md) · [First local report](docs/try-it.md) · [Limitations](docs/limitations.md)

Using BEIR? The [export/evaluation recipe](docs/beir-workflow.md) preserves the retrieved snapshot, makes self-match filtering and export depth explicit, and transfers existing qrels without inventing labels.

Using RecBole nonsequential full-sort scores? The [safe export recipe](docs/recbole-workflow.md) records padding/history exclusions, preserves external tokens and rejects unexpected nonfinite scores without inventing judgments.

Using ReChorus? The [runner capture recipes](docs/rechorus-workflow.md) preserve sampled candidates before the native top-100 presentation export, or explicitly handle masks in the checked base full-sort contract. Stable source identities are available for cross-run comparisons.

Have saved MTEB retrieval predictions? The [score-file recipe](docs/mteb-workflow.md) selects one subset and split for the existing CSV interface, explains cache and output-folder choices, and distinguishes saved candidates from the later scoring stage. Metric-only result JSON is insufficient.

## Quick start

Requires Python 3.10 or newer. Install from this checkout; no PyPI release is claimed.

The alpha is currently incubated in an isolated directory of the existing
reproduction repository. Without Git, [download the source ZIP](https://codeload.github.com/C4LLM3LUC4S/rechorus-patt-reproduction/zip/refs/heads/feature/rankprobe-alpha), extract it, open a terminal in the extracted repository folder, and run `cd tools/rankprobe`.

On Windows, choose a short extraction path. If creating the environment fails with a long-path hint from pip/ensurepip, start again from a shorter folder.

Or obtain it with Git:

```sh
git clone --branch feature/rankprobe-alpha https://github.com/C4LLM3LUC4S/rechorus-patt-reproduction.git
cd rechorus-patt-reproduction/tools/rankprobe
```

From the package folder, use a separate environment without activating it.

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install .
.\.venv\Scripts\python.exe -m rankprobe demo --out reports/demo
```

macOS / Linux:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/python -m rankprobe demo --out reports/demo
```

Open `reports/demo/report.html` offline. See the [complete first-use walkthrough](docs/try-it.md) for a comparison with expected values and framework environment guidance. In the remaining examples, `python` means the same environment interpreter: use `.\.venv\Scripts\python.exe` on Windows or `.venv/bin/python` on macOS / Linux. To use a supplied example:

```sh
python -m rankprobe audit examples/ties.csv --cutoffs 1,5 --out reports/ties
python -m rankprobe audit examples/ties.csv --tie-policy input --cutoffs 1,5 --out reports/ties-input
python -m rankprobe compare --run baseline=examples/clean.csv --run changed=examples/mismatch.csv --out reports/compare
```

Reports are written to the selected output directory; existing report files are refused unless `--overwrite` is explicit. `report.json` is intended for programmatic inspection; `report.html` is self-contained and can be opened offline. Reports include input identifiers and example rows, so review them before sharing.

In a comparison, start with **Comparison results**: submitted-run values sit beside matched-pool values and the right-minus-left delta. Each value shows its coverage and reference scope. Expand coverage details to see which queries were excluded, then follow the relevant finding's suggested next step. A displayed delta is an arithmetic difference under the stated protocol, not a significance test.

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

From `0.1.0a4`, MRR can use a known first-relevant prefix even when later labels are unknown. Earlier reports used a stricter eligibility rule. Read the [metric semantics and migration note](docs/metrics.md#mrrk) before comparing conditional averages across versions.

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

For the next step after a finding, see [case actions and rechecks](docs/case-actions.md). It separates executed public-input checks from pending follow-up experiments and synthetic controls.

The optional [fitted-score MovieLens case](examples/movielens-scores/README.md) uses actual public ratings and two small NumPy models to check shared observed-item pools, presentation rounding and recovery from retained exact scores. It keeps dataset-derived rows local and does not change the model-free core.

## Existing framework outputs

Export a small ReChorus-style NPZ locally with the optional NumPy adapter:

```sh
python -m pip install -e ".[adapters]"
python scripts/export_rechorus.py local_test_predictions.npz --out local_export.csv --positive-index 0 --limit-queries 100
python -m rankprobe audit local_export.csv --out reports/local-export
```

The adapter has an explicit one-positive-column assumption; all other labels remain unknown in this recipe. Only add `--other-candidates nonrelevant` when your verified evaluation protocol justifies that assertion. It remaps item IDs, omits the `user_id` array, and treats each matrix row as a distinct query. Read [adapter assumptions](docs/adapters.md) before comparing exports. Run model-dependent capture in your existing framework interpreter; audit the resulting file with the core environment above. Synthetic fixtures are included; private predictions, MovieLens data, and third-party code are not redistributed.

RankProbe is an independent evaluator, not a compatibility wrapper for MTEB, RecBole, or ReChorus. Tie rules and metric definitions can differ. For example, its default `item_id` tie rule is ascending string order, whereas `trec_eval` uses a different convention. See [known public context](docs/known-cases.md) and the [reproducible trec_eval cross-check](docs/trec-reference.md) to distinguish shared-protocol agreement from expected differences.

## Development

```sh
python -m pip install -e ".[dev,adapters]"
python -m pytest
python -m ruff check .
python -m build
python scripts/check_distribution.py
python scripts/check_wheel_install.py --wheel dist/rankprobe-0.1.0a4-py3-none-any.whl
```

The full-test CI matrix targets Python 3.10, 3.12, and 3.13 on Ubuntu and Windows, including fresh built-wheel installation and both command-line entry points. Separate Python 3.15 jobs on both systems check core source installation, distribution builds and the isolated wheel; they do not establish full-suite, NumPy-adapter or native-framework coverage on 3.15. Python 3.14 is not in this matrix. See [installation checks](docs/installation-checks.md) and inspect the exact commit's workflow runs for results.

This is an early `0.1.0a4` implementation. The [verification record](docs/verification.md) distinguishes executed checks from pending evidence. There are no claimed external adopters, revenue, benchmark certification, or published research results. [The validation plan](docs/validation-plan.md) and [roadmap](docs/roadmap.md) describe what would establish practical value. Contributions should add an independently checkable example and document changed semantics. Please report problems with a small synthetic input instead of uploading private data.

## License and citation

See [LICENSE](LICENSE). Original synthetic examples follow this repository's license; framework outputs and datasets retain their own terms. A [CITATION.cff](CITATION.cff) file describes this software without claiming a paper or DOI.
