# Audit scores saved by an MTEB retrieval task

MTEB's ordinary result JSON contains metric summaries, not the query/document scores needed by RankProbe. Its optional prediction JSON can be transferred to the existing CSV interface with a small local script. Keep model evaluation in your existing MTEB environment and run conversion and auditing in the [core environment](try-it.md#1-install-locally).

The source inspected here is MTEB tag `2.26.1`, commit [`a689529bef70dae42c0747105154c10b00c63879`](https://github.com/embeddings-benchmark/mteb/tree/a689529bef70dae42c0747105154c10b00c63879). The instructions below are tied to that source. The initial recipe was checked by source inspection and an original synthetic file-shape example through RankProbe. A separate optional native gate below exercises the actual framework on original miniature inputs; its passing status must come from the exact CI commit.

## Obtain a separate prediction file

For an evaluation you already plan to run, enable [`prediction_folder`](https://github.com/embeddings-benchmark/mteb/blob/a689529bef70dae42c0747105154c10b00c63879/docs/get_started/usage/running_the_evaluation.md#L107-L128) in your existing MTEB environment. Use a new folder for each model, revision, and evaluation:

```python
from pathlib import Path
import mteb

folder = Path("reports/mteb-model-revision-evaluation")
folder.mkdir(parents=True, exist_ok=False)
results = mteb.evaluate(model, tasks=[task], cache=None,
                        prediction_folder=folder)
```

Here `model` and `task` are your already configured objects. **This performs a fresh evaluation, including model inference; it does not recover predictions from metric results.** Decide whether that run is appropriate for your resources. `cache=None` avoids both a cached early return and writes to your existing metric cache. A completed [cache hit](https://github.com/embeddings-benchmark/mteb/blob/a689529bef70dae42c0747105154c10b00c63879/mteb/evaluate.py#L744-L759) can otherwise skip task evaluation even when a prediction folder was requested. If you already have a permitted prediction file from the intended evaluation, use it without rerunning the model.

The [saver](https://github.com/embeddings-benchmark/mteb/blob/a689529bef70dae42c0747105154c10b00c63879/mteb/abstasks/abstask.py#L276-L325) writes `TASK_predictions.json`. It loads an existing file and replaces only the current subset/split, retaining its old metadata and other scopes. Reusing a folder across models can therefore mix new scores with old metadata or splits. A new folder prevents that use error; it does not certify provenance of an existing file.

For retrieval, the relevant shape is:

```json
{
  "mteb_model_meta": {"model_name": "your-model", "revision": "your-revision"},
  "default": {
    "test": {
      "query-1": {"document-1": 0.8, "document-2": 0.4}
    }
  }
}
```

This illustration is invented. The [retrieval output type](https://github.com/embeddings-benchmark/mteb/blob/a689529bef70dae42c0747105154c10b00c63879/mteb/types/_encoder_io.py#L278-L286) maps query IDs to document scores; the surrounding subset/split keys come from the saver. Model [name and revision can be null](https://github.com/embeddings-benchmark/mteb/blob/a689529bef70dae42c0747105154c10b00c63879/mteb/models/model_meta.py#L249-L253); metadata shape does not verify model identity. Select exactly one subset and split. The same query ID in another language, split, or task need not identify the same evaluation unit. Do not combine those scopes by bare ID. Ordinary [`TaskResult`](https://github.com/embeddings-benchmark/mteb/blob/a689529bef70dae42c0747105154c10b00c63879/mteb/results/task_result.py#L130-L176) metric summaries cannot supply this mapping.

## Convert one scope with the core interpreter

Save the following as a local file, for example `convert_mteb_scores.py`, and edit the four values at its start. It uses only the standard library and the installed RankProbe core. It writes scores without labels; CSV quoting preserves spaces and commas in IDs.

```python
import csv
import hashlib
import json
from pathlib import Path

from rankprobe.model import Row

source = Path("my-inputs/TASK_predictions.json")
destination = Path("my-inputs/selected-scores.csv")
subset = "default"
split = "test"


def unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key!r}")
        result[key] = value
    return result


def reject_constant(value):
    raise ValueError(f"Non-finite JSON number: {value}")


original = source.read_bytes()
payload = json.loads(original, object_pairs_hook=unique_keys,
                     parse_constant=reject_constant)
if not isinstance(payload, dict):
    raise ValueError("Expected an MTEB retrieval prediction object")
metadata = payload.get("mteb_model_meta")
if (not isinstance(metadata, dict)
        or "model_name" not in metadata
        or not isinstance(metadata["model_name"], (str, type(None)))
        or "revision" not in metadata
        or not isinstance(metadata["revision"], (str, type(None)))):
    raise ValueError("Missing prediction metadata; metric results are not scores")
if subset == "mteb_model_meta" or subset not in payload:
    raise ValueError(f"Prediction subset not found: {subset!r}")
subset_scores = payload[subset]
if not isinstance(subset_scores, dict) or split not in subset_scores:
    raise ValueError(f"Prediction split not found: {split!r}")
selected = subset_scores[split]
if not isinstance(selected, dict) or not selected:
    raise ValueError("Selected scope must contain query/document score mappings")

rows = []
for query_id, scores in selected.items():
    if not isinstance(scores, dict) or not scores:
        raise ValueError(f"Query {query_id!r} has no score mapping; not dropped")
    for document_id, score in scores.items():
        row = Row(query_id, document_id, score)
        rows.append(row)

if source.read_bytes() != original:
    raise RuntimeError("Source changed during conversion; no CSV written")
with destination.open("x", encoding="utf-8", newline="") as handle:
    writer = csv.writer(handle)
    writer.writerow(["query_id", "item_id", "score"])
    writer.writerows((row.query_id, row.item_id, row.score) for row in rows)
if source.read_bytes() != original:
    raise RuntimeError("Source changed during conversion; inspect both files")
print("Source SHA256:", hashlib.sha256(original).hexdigest())
print("Selected subset/split:", subset, split)
print("Exported rows:", len(rows))
```

The destination's parent must already exist, and the destination must be new. The script validates the whole selected scope before opening it with `x`; a bad late row cannot leave a partly validated CSV. It rejects duplicate JSON keys anywhere in the file, missing scopes, metric-only shapes and empty query mappings. An empty candidate list cannot be represented as a prediction row, so inspect that query separately rather than quietly dropping it. `Row` rejects empty IDs, booleans, nonnumeric and non-finite scores. Finite JSON floats retain their parsed values through Python's round-trip number representation. Accepted JSON integers are written as integer tokens, which the core CSV reader preserves exactly; adjacent integers such as `9007199254740992` and `9007199254740993` remain distinct. The script preserves selected record order without sorting, truncating, renaming IDs, filling labels, or modifying the source. It holds the JSON and selected rows in memory; this is a bounded local recipe, not a streaming exporter.

Windows PowerShell, from the package folder with the installed core environment:

```powershell
.\.venv\Scripts\python.exe convert_mteb_scores.py
if ($LASTEXITCODE -eq 0) {
    .\.venv\Scripts\python.exe -m rankprobe audit my-inputs/selected-scores.csv --out reports/mteb-audit
} else {
    throw "MTEB conversion failed; no audit started. Keep the diagnostic and use a new CSV destination."
}
```

macOS / Linux:

```sh
.venv/bin/python convert_mteb_scores.py &&
    .venv/bin/python -m rankprobe audit my-inputs/selected-scores.csv --out reports/mteb-audit
```

Require conversion exit `0` before starting the audit. Two independent shell commands can continue after a failed conversion and audit a previous CSV at the same path. The conditional blocks above stop that handoff; RankProbe's own completed-report exit `1` still has its [usual meaning](usage.md#exit-codes-and-automation).

If conversion fails, keep its diagnostic and the existing files. Fix invalid source data in a new source export, or choose a new `destination` in the script when the old destination exists. Update the audit's CSV path to that exact destination, choose a new report directory, and rerun the conditional block. Do not audit an existing CSV merely because it parses or overwrite it to clear the error. A filesystem error during writing can also leave a partial CSV even though input validation finished first; require a successful fresh-output conversion before proceeding. Without judgments, label-dependent metrics are unverified; structural findings such as ties remain useful.

An original synthetic PowerShell handoff control reproduced conversion exit `1` for an existing CSV followed by a completed audit of that stale CSV under the former independent commands. The conditional form stops before creating a report; a fresh-output retry audits only the new source's selected scope. This is a command-orchestration check of the local bridge, not a new MTEB framework execution, outside adoption or measured human time saved.

If you have permitted, independent judgments for **the same task, subset, split and ID namespace**, transfer their supplied grades to a separate [judgment file](input-format.md). Keep missing judgments unknown. Then add `--qrels my-inputs/judgments.csv` to the audit command. The score bridge deliberately does not infer relevance from scores or create judgments for absent pairs. Do not assert `--qrels-complete` or add `--unjudged nonrelevant` just to obtain a metric.

## Interpret the exported stage

The saved prediction is a **pre-scoring candidate pool**. In the inspected source, [saving](https://github.com/embeddings-benchmark/mteb/blob/a689529bef70dae42c0747105154c10b00c63879/mteb/abstasks/retrieval.py#L392-L428) precedes scoring with `ignore_identical_ids` and `skip_first_result`. When enabled, the former [removes equal query/document IDs](https://github.com/embeddings-benchmark/mteb/blob/a689529bef70dae42c0747105154c10b00c63879/mteb/_evaluators/retrieval_evaluator.py#L116-L138), while the latter [drops a first result in a scoring copy](https://github.com/embeddings-benchmark/mteb/blob/a689529bef70dae42c0747105154c10b00c63879/mteb/_evaluators/retrieval_metrics.py#L580-L602). Generic defaults are false; inspect your specific task. Equal IDs do not by themselves prove leakage.

Default retrieval depth is [`max(k_values)`, initially 1000](https://github.com/embeddings-benchmark/mteb/blob/a689529bef70dae42c0747105154c10b00c63879/mteb/abstasks/retrieval.py#L96-L107); reranking can [change the depth and candidate pool](https://github.com/embeddings-benchmark/mteb/blob/a689529bef70dae42c0747105154c10b00c63879/mteb/abstasks/retrieval.py#L735-L783). Saved scores do not reconstruct omitted candidates or a full-corpus score matrix. Queries with empty judgment dictionaries are [filtered before retrieval](https://github.com/embeddings-benchmark/mteb/blob/a689529bef70dae42c0747105154c10b00c63879/mteb/abstasks/retrieval.py#L63-L76); the export cannot reveal that earlier query loss. Despite the filter's name, its condition is dictionary emptiness, not a test for a positive grade.

Record the source checksum, selected scope, MTEB version, task and dataset revision, model revision, retrieval/reranking depth and scoring filters beside your report. The prediction metadata contains only model name and revision; the bridge does not verify those declarations or recover missing provenance. For comparisons, use independent files for each declared evaluation and keep task/scope/IDs consistent.

Current [MTEB MRR](https://github.com/embeddings-benchmark/mteb/blob/a689529bef70dae42c0747105154c10b00c63879/mteb/_evaluators/retrieval_metrics.py#L28-L54) breaks score ties by descending document ID and treats candidates outside its positive judgments as non-hits. RankProbe defaults to ascending item-ID ties and preserves absent labels as unknown. JSON insertion order is not a declared MTEB rank; `--tie-policy input` alone does not reproduce that native ordering. Read [metric scopes and eligibility](metrics.md) before interpreting a difference. This recipe establishes a score-file boundary, not native metric parity, benchmark correctness, automatic leakage exclusion, outside adoption, or measured human time saved.

## Optional synthetic native check

Converting an existing prediction file above requires only RankProbe's core. The following optional check installs and runs MTEB itself; use a separate environment so it does not change your research environment.

The tested installation target is **Ubuntu 24.04, x86_64, Python 3.12**. MTEB 2.26.1 [declares Python >=3.11,<3.15](https://github.com/embeddings-benchmark/mteb/blob/a689529bef70dae42c0747105154c10b00c63879/pyproject.toml); other Python, operating-system and architecture combinations are not established by this check. RankProbe's core still supports Python 3.10. The framework installation needs internet access and substantially more disk space and dependencies than the core; no paid service, pretrained weights or benchmark dataset are needed.

From this checkout's package folder, run the following in a POSIX shell with Python 3.12, `curl` and `sha256sum` available. The work folder must be new. It is under the already ignored `.tooling/` directory; if installation fails, retain the error and use a different new folder for a clean retry.

```sh
set -eu
work=.tooling/mteb-native
if [ -e "$work" ] || [ -L "$work" ]; then
    echo "Choose a new work folder; this one already exists."
    exit 1
fi
mkdir -p "$work"
python3.12 -m venv "$work/venv"
py="$work/venv/bin/python"
"$py" -m pip install "setuptools==80.9.0" "wheel==0.45.1"
"$py" -m pip install --no-build-isolation .
"$py" -m pip install "torch==2.8.0+cpu" --index-url https://download.pytorch.org/whl/cpu
"$py" -m pip install -r scripts/mteb-requirements.txt -c scripts/mteb-requirements.txt

archive="$work/mteb-source.tar.gz"
curl --fail --location --retry 2 \
    https://codeload.github.com/embeddings-benchmark/mteb/tar.gz/a689529bef70dae42c0747105154c10b00c63879 \
    --output "$archive"
printf '%s  %s\n' \
    b5e751e0f763a28e5bd2595b3bf392c981d5d6a884b0d535ae3a439d54ecaf4e \
    "$archive" | sha256sum --check
"$py" -m pip install --no-build-isolation --no-deps "$archive"
"$py" -m pip check
"$py" -m pip list --disable-pip-version-check --format=json > "$work/installed-packages.json"
"$py" scripts/check_mteb_workflow.py --out "$work/workflow"
```

The [19 shared dependency requests](../scripts/mteb-requirements.txt) are used by this recipe and CI. They cover selected direct and transitive packages, not the entire dependency graph. `pip check` verifies declared dependency compatibility in the current environment; it does not lock future resolutions or verify package artifact hashes. `installed-packages.json` records visible installed names and versions for diagnosis, not a portable lock. Keep it and the installation error when reporting a failure; do not share tokens, pip configuration or your environment variables.

On success, inspect `$work/workflow/summary.json`, `score-only/report.html` and `sparse-judgments/report.html` under that workflow folder. The checker requires a new output directory with an existing parent and refuses linked ancestors. Do not delete an older report to make the command pass: choose a new output name or a new work folder.

The separate CI job also creates a fresh virtual environment, uses the shared requests, verifies the source archive and eight installed source files, runs `pip check`, and invokes the checker through the CLI above. Its dependency installation is online; the actual exercise isolates caches and blocks runtime network access. A 20-minute job limit is a timeout, not an expected installation duration. These packages do not become core dependencies.

The check uses the official `MockRetrievalTask` class and untrained random encoder over original in-memory queries, documents and sparse judgments. It runs one `test` split through actual `mteb.evaluate`, saves predictions, executes the copied conversion code above and runs the real RankProbe CLI. Identical document text under different IDs supplies a deliberate tie control. Score-only and separate sparse-judgment reports must preserve unknowns and avoid assumptions; they do not establish native metric equality. No pretrained weights or benchmark dataset are needed for this bounded path.

The source archive SHA256 is `b5e751e0f763a28e5bd2595b3bf392c981d5d6a884b0d535ae3a439d54ecaf4e`. The `mteb-workflow-summary` CI artifact retains the aggregate summary and `rankprobe-mteb-environment.json`. The latter records visible distribution names/versions and Python implementation/version, OS and architecture before framework imports; it omits installation URLs, paths, pip configuration and environment variables. Duplicate distribution names remain separate entries. Neither snapshot captures a full artifact lock or certifies framework correctness. Inspect the current commit's run before treating installation or the exercise as passed. Actual framework execution on synthetic inputs remains separate from an outside user's real export, independent adoption or measured human time saved.
