# CLI and Python usage

The CLI installs as `rankprobe`; `python -m rankprobe` uses the same entry point and is convenient when several Python environments are installed. Run `python -m rankprobe --help` for subcommands or add `--help` after `audit`, `compare`, or `demo`.

## Commands

```sh
python -m rankprobe audit predictions.csv --name baseline --out reports/baseline
python -m rankprobe compare --run baseline=baseline.csv --run treatment=treatment.jsonl --out reports/compare
python -m rankprobe demo --out reports/demo
```

`compare` requires at least two distinctly named runs. A run name describes a report entry; it does not change query or item identity. `demo` uses a built-in, invented example that deliberately contains problems.

| Option | Default | Meaning |
| --- | --- | --- |
| `--cutoffs 1,5,10` | 1,5,10 | Positive integer ranking cutoffs |
| `--tie-policy item_id` | item_id | Ascending string ID, or `input` for stable input order |
| `--gain linear` | linear | NDCG relevance gain, or `exp2` |
| `--relevance-threshold 0` | 0 | MRR / Recall consider label strictly above this threshold relevant; NDCG remains graded |
| `--qrels judgments.csv` | none | Independent CSV / JSONL judgments |
| `--qrels-complete` | false | Explicitly assert relevance-denominator completeness |
| `--unjudged unknown` | unknown | Preserve unknown labels, or explicitly choose `nonrelevant` |
| `--out DIR` | required | Destination for report.json and report.html |
| `--overwrite` | false | Replace existing report files, retaining unrelated files in the directory |
| `--fail-on error` | error | Findings trigger exit 1 at `error`, `warning`, or `never` |

Cutoffs are sorted and deduplicated. The declared protocol is saved in JSON. Absolute input paths and raw command lines are not stored as provenance; source filenames and hashes are recorded. Identifiers in the findings still require a privacy review before sharing.

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

Independent qrels use a nested dictionary of `{query_id: {item_id: relevance}}`, or the loader `rankprobe.io.read_qrels`. Pass the dictionary as `qrels=` to `audit_run` or `compare_runs`. Inputs are validated; contradictory labels raise `ValueError`. The API returns ordinary dictionaries and performs no file writes until you call `write_report`.

The library-generated report contains the audit data; the CLI additionally records input-file provenance. Pin the alpha version or commit if integrating this API. The report schema and public functions may change during early development.
