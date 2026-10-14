# CLI and Python usage

The CLI installs as `rankprobe`; `python -m rankprobe` uses the same entry point and is convenient when several Python environments are installed. Run `python -m rankprobe --help` for subcommands or add `--help` after `audit`, `compare`, or `demo`.

## Commands

```sh
python -m rankprobe audit predictions.csv --name baseline --out reports/baseline
python -m rankprobe compare --run baseline=baseline.csv --run treatment=treatment.jsonl --out reports/compare
python -m rankprobe demo --out reports/demo
python -m rankprobe compare --run baseline=examples/trec/baseline.run --run reordered=examples/trec/reordered.run --qrels examples/trec/judgments.qrels --cutoffs 1,2 --out reports/retrieval
```

`compare` requires at least two distinctly named runs. A run name describes a report entry; it does not change query or item identity. `demo` uses a built-in, invented example that deliberately contains problems.

| Option | Default | Meaning |
| --- | --- | --- |
| `--cutoffs 1,5,10` | 1,5,10 | Positive integer ranking cutoffs |
| `--tie-policy item_id` | item_id | Ascending string ID, or `input` for stable input order |
| `--gain linear` | linear | NDCG relevance gain, or `exp2` |
| `--relevance-threshold 0` | 0 | MRR / Recall consider label strictly above this threshold relevant; NDCG remains graded |
| `--input-format auto` | auto | Detect each prediction file by extension, or explicitly select `csv`, `jsonl`, or `trec` |
| `--qrels judgments.csv` | none | Independent CSV / JSONL / TREC judgments |
| `--qrels-format auto` | auto | Detect the judgment file by extension, or explicitly select `csv`, `jsonl`, or `trec` |
| `--qrels-complete` | false | Explicitly assert relevance-denominator completeness |
| `--unjudged unknown` | unknown | Preserve unknown labels, or explicitly choose `nonrelevant` |
| `--out DIR` | required | Destination for report.json and report.html |
| `--overwrite` | false | Replace existing report files, retaining unrelated files in the directory |
| `--fail-on error` | error | Findings trigger exit 1 at `error`, `warning`, or `never` |

Cutoffs are sorted and deduplicated. The declared protocol is saved in JSON. Absolute input paths and raw command lines are not stored as provenance; source filenames and hashes are recorded. Identifiers in the findings still require a privacy review before sharing.

The output report pair must not coincide with any prediction or judgment input, including an existing file alias. Such a destination is rejected even with `--overwrite`; choose a separate report directory.

In an audit summary, `judged_candidates` counts unique candidates with an actual known judgment after label resolution. `resolved_candidates` also includes unknowns assigned zero under `--unjudged nonrelevant`. Their difference reflects an assumption, not newly collected judgments.

Auto detection accepts `.csv`, `.jsonl`, prediction `.run` / `.trec`, and judgment `.qrels`. For `.txt` files, declare the format explicitly:

```sh
python -m rankprobe audit results.txt --input-format trec --qrels labels.txt --qrels-format trec --out reports/trec-text
```

TREC rank columns are validated but sorting uses scores and the selected tie rule. Explicit `-1` judgments remain unknown unless the protocol explicitly assumes unjudged items nonrelevant. Do not add `--qrels-complete` to a partially judged file. See [input-format.md](input-format.md) for the full contract and [try-it.md](try-it.md) for a five-minute walkthrough.

## Exit codes and automation

| Code | Meaning |
| --- | --- |
| 0 | The command finished and no finding met the selected failure threshold |
| 1 | A completed report contains findings at or above `--fail-on` |
| 2 | Invalid arguments, input, or output operation |

A warning does not fail the default invocation. To enforce a stricter local gate:

```sh
python -m rankprobe audit predictions.csv --fail-on warning --out reports/check
```

`--fail-on never` permits findings, not invalid inputs. Do not treat exit zero as certification of an experiment. Match your automation to structured finding codes and schema version `0.1`, rather than searching HTML text.

## Python API

```python
from rankprobe.audit import audit_run, compare_runs
from rankprobe.io import read_predictions
from rankprobe.model import Protocol, Row
from rankprobe.report import write_report

protocol = Protocol(cutoffs=(1, 5), tie_policy="item_id", gain="linear")
rows = [
    Row("q1", "b", 0.8, 1),
    Row("q1", "a", 0.8, 0),
]
report = audit_run(rows, protocol, run_name="example")
json_path, html_path = write_report(report, "reports/python-example")

runs = {
    "baseline": read_predictions("examples/clean.csv"),
    "changed": read_predictions("examples/mismatch.csv"),
}
comparison = compare_runs(runs, protocol)
```

Independent qrels use a nested dictionary of `{query_id: {item_id: relevance}}`, where `None` represents an explicit unknown, or the loader `rankprobe.io.read_qrels`. Both loaders accept a keyword-only `format=` argument with `auto`, `csv`, `jsonl`, or `trec`. For example, `read_predictions("retrieval.txt", format="trec")` reads six-column run text without relying on the extension. Pass the qrels dictionary as `qrels=` to `audit_run` or `compare_runs`. Inputs are validated; contradictory known labels raise `ValueError`. The API returns ordinary dictionaries and performs no file writes until you call `write_report`.

The library-generated report contains the audit data; the CLI additionally records input-file provenance. Pin the alpha version or commit if integrating this API. The report schema and public functions may change during early development.
