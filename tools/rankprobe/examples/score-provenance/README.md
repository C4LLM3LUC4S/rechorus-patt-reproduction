# A rank-derived score loses the original tie

All records here are original synthetic controls. They contain one query and three candidates, with an intentional score tie. They were first checked as a developer control and are included here for a complete source-checkout example. No model, Pyserini installation or benchmark data is needed.

| File | What it contains |
| --- | --- |
| `original.run` | Scores `0.5, 0.5, 0.1`, in candidate order `22, 11, 33`; no relevance labels |
| `rank-only.tsv` | The same supplied order as three columns: query ID, candidate ID and one-based rank; no scores |
| `rank-proxy.run` | A new six-column file whose scores are `1 / rank`: `1, 0.5, 1/3`; no relevance labels |
| `planted.qrels` | A separate, explicitly planted synthetic oracle: candidate `22` has grade 1, and `11` and `33` have grade 0 |

The reciprocal-rank values preserve this supplied order but remove its original score equality. A six-column file can be valid TREC text without containing the model's original scores. RankProbe can inspect the scores supplied to it; it cannot reconstruct their history from the file shape.

## First inspect the unlabeled scores

Start in the RankProbe package root with the core `.venv` from [the first-report setup](../../docs/try-it.md#1-install-locally). The commands use new report directories; choose another name if one already exists.

Windows PowerShell:

```powershell
.\.venv\Scripts\python.exe -m rankprobe compare --run original_scores=examples/score-provenance/original.run --run rank_proxy=examples/score-provenance/rank-proxy.run --cutoffs 1,3 --unjudged unknown --out reports/score-provenance-unknown
```

macOS / Linux:

```sh
.venv/bin/python -m rankprobe compare --run original_scores=examples/score-provenance/original.run --run rank_proxy=examples/score-provenance/rank-proxy.run --cutoffs 1,3 --unjudged unknown --out reports/score-provenance-unknown
```

Open `reports/score-provenance-unknown/report.html`. The original scores have one tie group; the rank proxy has none. Each run retains three unknown candidates and zero assumed nonrelevant candidates. MRR, NDCG and Recall are unavailable. The query and candidate IDs match structurally, but no metric delta is available without judgments. That structural match does not verify score provenance.

The three-column file is outside the TREC input contract. To see the clear rejection, run the following separately; exit code 2 is expected and no report is created.

Windows PowerShell:

```powershell
.\.venv\Scripts\python.exe -m rankprobe audit examples/score-provenance/rank-only.tsv --input-format trec --out reports/score-provenance-rank-only
```

macOS / Linux:

```sh
.venv/bin/python -m rankprobe audit examples/score-provenance/rank-only.tsv --input-format trec --out reports/score-provenance-rank-only
```

## Keep the planted-label control separate

The following commands explicitly add the invented labels in `planted.qrels`. They answer how tie policy affects this control; they do not supply missing benchmark judgments. Neither command declares complete qrels, and Recall remains unavailable.

Windows PowerShell:

```powershell
.\.venv\Scripts\python.exe -m rankprobe compare --run original_scores=examples/score-provenance/original.run --run rank_proxy=examples/score-provenance/rank-proxy.run --qrels examples/score-provenance/planted.qrels --cutoffs 1,3 --tie-policy input --unjudged unknown --out reports/score-provenance-planted-input
.\.venv\Scripts\python.exe -m rankprobe compare --run original_scores=examples/score-provenance/original.run --run rank_proxy=examples/score-provenance/rank-proxy.run --qrels examples/score-provenance/planted.qrels --cutoffs 1,3 --tie-policy item_id --unjudged unknown --out reports/score-provenance-planted-item-id
```

macOS / Linux:

```sh
.venv/bin/python -m rankprobe compare --run original_scores=examples/score-provenance/original.run --run rank_proxy=examples/score-provenance/rank-proxy.run --qrels examples/score-provenance/planted.qrels --cutoffs 1,3 --tie-policy input --unjudged unknown --out reports/score-provenance-planted-input
.venv/bin/python -m rankprobe compare --run original_scores=examples/score-provenance/original.run --run rank_proxy=examples/score-provenance/rank-proxy.run --qrels examples/score-provenance/planted.qrels --cutoffs 1,3 --tie-policy item_id --unjudged unknown --out reports/score-provenance-planted-item-id
```

| Planted-label control | Original MRR@1 / NDCG@1 | Rank proxy MRR@1 / NDCG@1 | Matched right-minus-left delta for each |
| --- | --- | --- | --- |
| `input` ties | 1 / 1 | 1 / 1 | 0 |
| `item_id` ties | 0 / 0 | 1 / 1 | +1 |

Under `input`, both order candidates `22, 11, 33`. Under `item_id`, the original score tie orders `11` before `22`, while the rank proxy's distinct scores still put `22` first. RankProbe sorts by scores and the declared tie policy; the input rank column does not override them. At cutoff 3 with `item_id`, original MRR is `0.5` and NDCG is `1 / log2(3)`; the proxy gives 1 for both. These differences come from encoding a tie order into new scores, with the same candidates and planted labels. They are not a model improvement.

## Choose a source that retains score evidence

At Pyserini commit [`ef7c2edf71e0402bca8d8826d3c7b55d42d6fabb`](https://github.com/castorini/pyserini/tree/ef7c2edf71e0402bca8d8826d3c7b55d42d6fabb), the [MS MARCO writer](https://github.com/castorini/pyserini/blob/ef7c2edf71e0402bca8d8826d3c7b55d42d6fabb/pyserini/output_writer.py#L88-L91) writes three rank-only columns. Its [TREC writer](https://github.com/castorini/pyserini/blob/ef7c2edf71e0402bca8d8826d3c7b55d42d6fabb/pyserini/output_writer.py#L82-L85) writes the hit score to six decimal places. The official [MS MARCO-to-TREC converter](https://github.com/castorini/pyserini/blob/ef7c2edf71e0402bca8d8826d3c7b55d42d6fabb/pyserini/eval/convert_msmarco_run_to_trec_run.py#L26-L30) creates scores from reciprocal ranks. This example independently constructs those documented shapes and arithmetic; it does not execute Pyserini or its converter.

When planning an evaluation, preserve score-bearing output before it is reduced to ranks. The [official passage guide](https://github.com/castorini/pyserini/blob/ef7c2edf71e0402bca8d8826d3c7b55d42d6fabb/docs/experiments-msmarco-passage.md#L142-L156) gives a TREC-output retrieval path. If your existing evaluation objects still hold the scores, export them to the [CSV/JSONL contract](../../docs/input-format.md) with their original IDs and ordering. A new retrieval may be costly; decide whether it is needed rather than rerunning it merely to create a report. A rank-only file cannot recover lost scores, and six-decimal TREC output cannot recover precision already rounded away.

This developer example verifies a file boundary and its consequences under stated tie policies. It does not establish native Pyserini parity, a benchmark defect, independent adoption or measured human time saved.
