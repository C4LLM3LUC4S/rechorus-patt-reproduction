# Audit a BEIR export without changing its protocol

BEIR already provides a TREC run exporter. RankProbe can read its output directly; another prediction format or model dependency is unnecessary. The main integration risks are *when* results are exported, which candidates are retained, and how judgments are transferred.

The source inspected here is BEIR [`ef83d29307061c65d04b035b4f4e7c18bd8374af`](https://github.com/beir-cellar/beir/tree/ef83d29307061c65d04b035b4f4e7c18bd8374af), whose package metadata identifies version 2.2.0. These observations are tied to this source, not every BEIR version.

## Check ordinary qrels rows before loading

The pinned [`GenericDataLoader._load_qrels`](https://github.com/beir-cellar/beir/blob/ef83d29307061c65d04b035b4f4e7c18bd8374af/beir/datasets/data_loader.py#L120-L134) assigns each row into a query/document dictionary. A later repeated pair overwrites the earlier grade, so exporting that dictionary cannot recover conflicting source rows. Before loading an ordinary split, run this read-only check on its original TSV with the core interpreter; BEIR is unnecessary here:

```python
import csv
from pathlib import Path

source = Path("/absolute/path/to/permitted-dataset/qrels/test.tsv")
seen = set()
with source.open("r", encoding="utf-8-sig", newline="") as handle:
    rows = csv.reader(handle, delimiter="\t", strict=True)
    if next(rows, None) != ["query-id", "corpus-id", "score"]:
        raise ValueError(f"{source}: expected query-id, corpus-id, score TSV header")
    for row in rows:
        if len(row) != 3 or not row[0].strip() or not row[1].strip():
            raise ValueError(f"{source}:{rows.line_num}: expected three fields and nonblank IDs")
        pair = (row[0], row[1])
        if pair in seen:
            raise ValueError(f"{source}:{rows.line_num}: repeated query-document pair {pair!r}")
        seen.add(pair)
```

An optional UTF-8 BOM before the exact header is accepted without modifying the source. This rejects equal-grade repeats too; it does not deduplicate or select a grade. It writes nothing and does not cast or reinterpret supplied `1`, `0` or `-1`. It retains one key per unique pair in memory. It checks only the header, row width, nonblank IDs and pair uniqueness, not grade semantics, split provenance or completeness. Preserve the source and resolve repeats against its intended judgment unit. Intentional multiple judgments need an explicitly documented source policy and an evaluator or export that preserves their judgment unit; do not silently merge them or invent zeros to pass this check. Continue with fresh split loading below only after reviewing the source.

## Keep split loading independent

The pinned [`GenericDataLoader.load`](https://github.com/beir-cellar/beir/blob/ef83d29307061c65d04b035b4f4e7c18bd8374af/beir/datasets/data_loader.py#L69-L91) keeps mutable queries and qrels on the loader. Reusing one instance across splits can accumulate judgments, reuse an already filtered query map, or change a previously returned qrels reference. Disjoint query sets can instead raise `KeyError`. Upstream [draft PR #225](https://github.com/beir-cellar/beir/pull/225) reports the reuse problem; that report does not establish that your installed version contains a fix.

Create a fresh loader for each declared split. When preparing the intended evaluation, choose one permitted split; retrieve against the returned corpus and queries, keeping qrels from that same call:

```python
from pathlib import Path
from beir.datasets.data_loader import GenericDataLoader

dataset_folder = Path("/absolute/path/to/permitted-dataset")
split = "test"
corpus, queries, qrels = GenericDataLoader(data_folder=str(dataset_folder)).load(split=split)
```

This rereads corpus and query files; account for I/O and memory costs. Do not rerun retrieval just to audit existing permitted exports. Export the paired `results` and `qrels` using the next section before advancing to another split, with a new destination each time. Repeat the load with a new instance rather than resetting private caches or modifying source judgments.

Record the dataset/query/qrels revision or original file hashes, declared split and actual query IDs beside each run. Matching IDs or shapes do not prove common provenance. RankProbe cannot automatically detect consistently stale or mixed-split inputs, certify leakage absence or model quality, or justify treating missing judgments as zero.

## Preserve the retrieved result before evaluation

[`EvaluateRetrieval.evaluate`](https://github.com/beir-cellar/beir/blob/ef83d29307061c65d04b035b4f4e7c18bd8374af/beir/retrieval/evaluation.py#L62-L78) defaults to `ignore_identical_ids=True` and removes documents with the same ID as their query **from the supplied results dictionary**. The [official dense example](https://github.com/beir-cellar/beir/blob/ef83d29307061c65d04b035b4f4e7c18bd8374af/examples/retrieval/evaluation/dense/evaluate_sbert.py) evaluates before exporting. A later export therefore represents the filtered candidate pool. This can be an intended benchmark choice; identical IDs alone do not establish leakage or a defect.

Immediately after retrieval, preserve a snapshot and export both stages if the filtering matters to your comparison. In your existing BEIR environment, with `results` and `qrels` already available:

```python
from copy import deepcopy
from pathlib import Path
from beir import util
from beir.retrieval.evaluation import EvaluateRetrieval

folder = Path("reports/beir-inputs")
folder.mkdir(parents=True, exist_ok=False)
raw = deepcopy(results)
evaluated = deepcopy(raw)
depth = max(len(items) for items in raw.values())
util.save_runfile(str(folder / "raw.run"), raw, top_k=depth)
EvaluateRetrieval.evaluate(qrels, evaluated, [1, 10], ignore_identical_ids=True)
util.save_runfile(str(folder / "filtered.run"), evaluated, top_k=depth)

with (folder / "judgments.qrels").open("x", encoding="utf-8") as handle:
    for query_id, judgments in qrels.items():
        for document_id, grade in judgments.items():
            handle.write(f"{query_id} 0 {document_id} {grade}\n")
```

This copies result dictionaries, so account for their memory size. It writes only integer qrels entries actually present, including `-1` if explicitly supplied as an unknown grade; it does not fill missing pairs with zero. Python `None` is not a valid grade to serialize with this snippet: TREC uses `-1` for that state. The snippet expects ordinary nonempty BEIR result mappings and whitespace-free IDs. Use a new destination; output files are never a reason to modify the original dataset.

[`save_runfile`](https://github.com/beir-cellar/beir/blob/ef83d29307061c65d04b035b4f4e7c18bd8374af/beir/util.py) defaults to `top_k=1000`. Set the retained depth deliberately and record it; the snippet preserves the stored candidate depth. Its zero rank column is valid for RankProbe, which sorts by scores. The inspected helper writes the score's ordinary string representation, with no fixed-decimal quantization. BEIR's native `write_to_tsv` qrels header (`query-id`, `corpus-id`, `score`) is a different contract: do not rename that TSV to `.qrels` and expect it to become TREC.

## Compare the exported stages

The snippet writes files relative to the BEIR process's working directory. Record the absolute location of `reports/beir-inputs` before changing directories. Return to the RankProbe package folder with the [separate core environment](try-it.md#1-install-locally); substitute your actual absolute input paths below. BEIR need not be installed in the core environment.

Windows PowerShell:

```powershell
.\.venv\Scripts\python.exe -m rankprobe compare --run "raw=D:/my evaluation/reports/beir-inputs/raw.run" --run "filtered=D:/my evaluation/reports/beir-inputs/filtered.run" --qrels "D:/my evaluation/reports/beir-inputs/judgments.qrels" --cutoffs 1,10 --out reports/beir-comparison
```

macOS / Linux:

```sh
.venv/bin/python -m rankprobe compare --run "raw=/absolute/path/to/beir-inputs/raw.run" --run "filtered=/absolute/path/to/beir-inputs/filtered.run" --qrels "/absolute/path/to/beir-inputs/judgments.qrels" --cutoffs 1,10 --out reports/beir-comparison
```

Start at Comparison results and inspect candidate-set findings. If filtering changes the pool, a higher submitted MRR need not reflect new model scores. Matched-pool values answer a narrower question and can cover fewer queries. When a query loses every candidate, it disappears from a prediction file; inspect qrels-only coverage as well.

The pinned [BEIR saver and loader](https://github.com/beir-cellar/beir/blob/ef83d29307061c65d04b035b4f4e7c18bd8374af/beir/util.py#L134-L155) write and reconstruct queries through document rows, so an empty query mapping cannot survive the run-file round trip. Preserve the intended evaluation query IDs separately before retrieval/export and compare them with both run and qrels IDs. A qrels-only ID may indicate lost predictions or judgments from another split; a query absent from both files cannot be detected from these files alone. Restore accidental omissions or state the narrower scope; do not add dummy candidates or automatically score missing queries as zero. The [existing walkthrough](../examples/trec/README.md) explains the resulting coverage differences.

Sparse qrels often leave retrieved documents unjudged. RankProbe preserves that uncertainty and can leave metrics unavailable. BEIR's native metric conventions may differ; do not add `--unjudged nonrelevant` or `--qrels-complete` merely to obtain a number. If nonrelevance is an intentional evaluation assumption, declare and record it explicitly. See [reference protocol differences](trec-reference.md).

## Reproduce the integration check

In an environment with the BEIR export/evaluation dependencies and an installed RankProbe, run from this source checkout:

```sh
python scripts/check_beir_workflow.py --out beir-workflow-example
```

The output directory must be new and its parent must exist. The check uses the actual imported BEIR helpers and evaluator on original synthetic dictionaries, plus tiny generated corpus/query JSONL and split-qrels TSV files through the real `GenericDataLoader`. It saves both run files, transferred qrels, the native TSV counterexample, generated loader fixtures, an HTML/JSON comparison and a summary. It also checks the default 1000-candidate truncation against an explicit 1002-candidate export. These bounded export, evaluation and loader checks do not download a public benchmark or model, run retrieval, or verify BEIR retrieval implementations.

The loader cases compare reuse and fresh instances for shared and disjoint dev/test query IDs. The summary records accumulated judgments, mutation of a previously returned qrels reference, the disjoint-query error and fresh per-split scopes, alongside hashes of the unchanged generated input files. These cases target the pinned loader; they do not establish split provenance for an arbitrary existing export.

Separate source-row cases use fresh loaders with two conflicting TSV rows in each order. They retain the original TSV, the one-row mapping export and a row-preserving TREC copy made only from the verified invented tokens. The existing core accepts the surviving mapped judgment but rejects the repeated original pair. This isolates loss before export, not a new aggregation rule or a general TSV converter; the read-only preflight above checks the original rows instead.

A separate BOM-header fixture checks that native integer grades `1` and `-1` are preserved and the mapped TREC `-1` is explicitly unknown in RankProbe, with the original source bytes unchanged.

The synthetic same-ID example deliberately changes submitted MRR@1 from 0.5 to 1 by filtering an irrelevant first candidate. The unchanged structurally matched query has MRR@1 = 1 in both runs, so its delta is zero. An unjudged candidate remains unjudged throughout. This demonstrates an intended preprocessing effect, not a newly discovered upstream model bug.

CI installs the checksum-verified BEIR source in a separate Ubuntu job, imports the full modules without fake dependencies, and verifies the installed export, evaluation and dataset-loader source bytes. It uses CPU PyTorch 2.8.0, pytrec-eval-terrier 0.5.10, requests 2.32.5, tqdm 4.67.1 and NumPy 2.2.6 for this bounded path; unused model/dataset packages are not installed. None become RankProbe core dependencies. The BEIR source archive SHA256 is `93be775e8bb6c857883e77e3a3a01f4748e6498a341fc436416b547e35d5a75b`. Check the exact CI commit before claiming this integration passed. Original synthetic outputs are retained as a CI artifact for 14 days; no upstream dataset or source is redistributed in RankProbe.

No outside user's adoption or human time saved has been measured by this integration check.
