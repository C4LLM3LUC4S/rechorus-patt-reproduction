# Audit a BEIR export without changing its protocol

BEIR already provides a TREC run exporter. RankProbe can read its output directly; another prediction format or model dependency is unnecessary. The main integration risks are *when* results are exported, which candidates are retained, and how judgments are transferred.

The source inspected here is BEIR [`ef83d29307061c65d04b035b4f4e7c18bd8374af`](https://github.com/beir-cellar/beir/tree/ef83d29307061c65d04b035b4f4e7c18bd8374af), whose package metadata identifies version 2.2.0. These observations are tied to this source, not every BEIR version.

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

With RankProbe installed:

```sh
python -m rankprobe compare --run raw=reports/beir-inputs/raw.run --run filtered=reports/beir-inputs/filtered.run --qrels reports/beir-inputs/judgments.qrels --cutoffs 1,10 --out reports/beir-comparison
```

Start at Comparison results and inspect candidate-set findings. If filtering changes the pool, a higher submitted MRR need not reflect new model scores. Matched-pool values answer a narrower question and can cover fewer queries. When a query loses every candidate, it disappears from a prediction file; inspect qrels-only coverage as well.

Sparse qrels often leave retrieved documents unjudged. RankProbe preserves that uncertainty and can leave metrics unavailable. BEIR's native metric conventions may differ; do not add `--unjudged nonrelevant` or `--qrels-complete` merely to obtain a number. If nonrelevance is an intentional evaluation assumption, declare and record it explicitly. See [reference protocol differences](trec-reference.md).

## Reproduce the integration check

In an environment with the BEIR export/evaluation dependencies and an installed RankProbe, run from this source checkout:

```sh
python scripts/check_beir_workflow.py --out beir-workflow-example
```

The output directory must be new and its parent must exist. The check uses the actual imported BEIR helpers and evaluator on original synthetic dictionaries. It saves both run files, transferred qrels, the native TSV counterexample, an HTML/JSON comparison and a summary. It also checks the default 1000-candidate truncation against an explicit 1002-candidate export. This exercises export and evaluation only: it does not download a model or dataset, or verify BEIR retrieval implementations.

The synthetic same-ID example deliberately changes submitted MRR@1 from 0.5 to 1 by filtering an irrelevant first candidate. The unchanged structurally matched query has MRR@1 = 1 in both runs, so its delta is zero. An unjudged candidate remains unjudged throughout. This demonstrates an intended preprocessing effect, not a newly discovered upstream model bug.

CI installs the checksum-verified BEIR source in a separate Ubuntu job, imports the full modules without fake dependencies, and verifies the installed export/evaluation source bytes. It uses CPU PyTorch 2.8.0, pytrec-eval-terrier 0.5.10, requests 2.32.5, tqdm 4.67.1 and NumPy 2.2.6 for this bounded path; unused model/dataset packages are not installed. None become RankProbe core dependencies. The BEIR source archive SHA256 is `93be775e8bb6c857883e77e3a3a01f4748e6498a341fc436416b547e35d5a75b`. Check the exact CI commit before claiming this integration passed. Original synthetic outputs are retained as a CI artifact for 14 days; no upstream dataset or source is redistributed in RankProbe.

No outside user's adoption or human time saved has been measured by this integration check.
