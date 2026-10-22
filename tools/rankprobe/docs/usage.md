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

Start at **Comparison results** in the HTML report. It places submitted-run metrics beside results on the structurally matched queries and shows the matched right-minus-left delta. Metric cells retain their status, eligible-query count and reference. Structural matching does not guarantee that every matched query is metric-eligible. When eligibility or reference scope differs, the delta remains unavailable.

Expand metric-coverage details for eligible query IDs, exclusion reasons and the corresponding JSON location. Lists shown in HTML are bounded; the JSON contains the full data stored by the engine. Findings include suggested next steps and local links to the relevant report section. These suggestions guide inspection; they do not change the protocol or automatically repair input data.

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

CLI reports also record `provenance.core_source_identity`. Unreleased builds can share a package version while containing different fixes, so the version alone does not identify their implementation. An available identity contains the SHA256 of each of the nine core Python source files and an aggregate SHA256. For scheme `rankprobe-core-python-v1`, hash the ASCII JSON of that filename-to-hash mapping with sorted keys and compact separators (`,`, `:`). Filenames are package-relative; no local paths or source text are stored. The HTML includes this under **Reproducibility metadata**.

This identifies the source bytes available when the report is created, including line endings; it does not prove which bytecode was loaded or describe Python, the operating system, installed dependencies, export helpers or model code. A changed hash is a reason to inspect the source difference, not proof that metric semantics changed. Keep the source archive or exact commit and environment details as well. If a core source file cannot be read, the identity is explicitly `unavailable` and the audit can still finish. Earlier reports without this field have an unknown implementation identity; do not infer it from their date or package version.

The output report pair must not coincide with any prediction or judgment input, including an existing file alias. Such a destination is rejected even with `--overwrite`; choose a separate report directory.

Give concurrent jobs separate `--out` directories. Without `--overwrite`, a second writer to the same report pair is refused even when both jobs began before either report existed. After an interrupted write, inspect both files before retrying; use a fresh directory to retain what remains, or use `--overwrite` only when you intend to replace that pair.

The HTML rounds most floating-point values for readability, but retains additional digits when rounding would make a non-whole result appear exactly whole (for example, an NDCG just below 1). Inspect `report.json` for the computed numeric value and the metric's coverage and reference scope before interpreting a near-perfect result.

In an audit summary, `judged_candidates` counts unique candidates with an actual known judgment after label resolution. `resolved_candidates` also includes unknowns assigned zero under `--unjudged nonrelevant`. Their difference reflects an assumption, not newly collected judgments.

Auto detection accepts `.csv`, `.jsonl`, prediction `.run` / `.trec`, and judgment `.qrels`. For `.txt` files, declare the format explicitly:

```sh
python -m rankprobe audit results.txt --input-format trec --qrels labels.txt --qrels-format trec --out reports/trec-text
```

TREC rank columns are validated but sorting uses scores and the selected tie rule. Explicit `-1` judgments remain unknown unless the protocol explicitly assumes unjudged items nonrelevant. Do not add `--qrels-complete` to a partially judged file. See [input-format.md](input-format.md) for the full contract and [try-it.md](try-it.md) for a complete first-use walkthrough.

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

For a complete cross-platform runner that keeps completed reports before returning a findings failure, see the [local CI recipe](local-ci.md).

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

The library-generated report contains the audit data; the CLI additionally records input-file provenance and core-source identity. Retain the exact source commit or build artifact if integrating an unreleased version of this API. The report schema and public functions may change during early development.
