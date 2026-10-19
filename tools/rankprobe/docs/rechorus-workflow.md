# Capture ReChorus scores before the top-k presentation export

The public ReChorus [`save_rec_results`](https://github.com/THUwangcy/ReChorus/blob/c164ec4303cc20ddcfbd1b57de366a481811d1e5/src/main.py#L98) writes TopK results as `user_id,rec_items,rec_predictions`: list-valued CSV cells, sorted and truncated to 100 candidates by the default call. It does not write the `scores,item_id` NPZ convention accepted by RankProbe's existing optional exporter. Renaming that CSV does not recover the original positive position, event identity or omitted candidates.

For a sampled, one-observed-positive-per-row evaluation, capture the complete matrix from [`BaseRunner.predict`](https://github.com/THUwangcy/ReChorus/blob/c164ec4303cc20ddcfbd1b57de366a481811d1e5/src/helpers/BaseRunner.py) before that presentation export. The [`GeneralModel.Dataset`](https://github.com/THUwangcy/ReChorus/blob/c164ec4303cc20ddcfbd1b57de366a481811d1e5/src/models/BaseModel.py) supplies candidate IDs in the same row order, with the observed target at column zero for this bounded protocol.

This recipe is tied to official source `c164ec4303cc20ddcfbd1b57de366a481811d1e5`. Different model/dataset subclasses may change candidate construction. Verify the actual dataset and evaluation configuration before declaring a positive column.

## Capture in your existing evaluation environment

With your existing `runner` and prepared test dataset, from the exact sampled evaluation whose candidate order you want to inspect:

```python
from pathlib import Path
import numpy as np

test_data = data_dict["test"]
if test_data.model.test_all:
    raise ValueError("This recipe supports sampled evaluation only")
scores = runner.predict(test_data)
candidate_ids = np.stack([test_data[index]["item_id"] for index in range(len(test_data))])
if scores.ndim != 2 or scores.shape != candidate_ids.shape:
    raise ValueError("Scores and original candidate rows must align exactly")

# New file only; its parent must already exist. Keep the original source private.
with Path("sampled-scores.npz").open("xb") as handle:
    np.savez(handle, scores=scores, item_id=candidate_ids)
```

This does not sort or truncate the matrix. Use only a prepared evaluation dataset whose candidate construction is deterministic across these two reads. For a custom dataset that resamples candidates, capture IDs in the same inference batch instead; this snippet cannot prove alignment for such a subclass. NPZ is the bridge convention, not a native upstream export feature.

### Set the mode and records before preparing the dataset

The pinned base model defaults to `buffer=1`. Dataset `prepare()` caches evaluation feed rows, and later `__getitem__` returns those rows without rebuilding them. Changing `model.test_all` or reordering/replacing `dataset.data` afterward does not automatically refresh the cached candidate identities. The runner can then interpret old sampled candidates under a new full-sort mode. This is a mutable-workflow risk, not a demonstrated defect in the normal default path.

Fix the evaluation mode and source records before constructing/preparing the dataset. If you change them, create a fresh dataset and call `prepare()` for that configuration, then obtain new predictions and event IDs from those same rows. Do not reuse old scores with a newly prepared dataset. The full-sort exporter checks the native shape/columns and fails before output when the cached sampled layout does not match; those checks cannot detect every same-shaped semantic mismatch.

The captured NPZ is relative to your model process's working directory. Changing to the RankProbe checkout does not transfer that file. Export in the same model environment, using its existing NumPy and the source helper; no RankProbe installation is needed there. Replace the scripts placeholder with the actual absolute source-checkout path:

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path("/absolute/path/to/rankprobe/scripts").resolve()))
from export_rechorus import export_npz

metadata = export_npz(Path("sampled-scores.npz"), Path("sampled-predictions.csv"),
                      positive_index=0)
print(Path("sampled-predictions.csv").resolve())
```

Then return to the RankProbe package folder with the [separate core environment](try-it.md#1-install-locally). Substitute the printed absolute CSV path below; the core audit does not need NumPy. The output directory must be new.

Windows PowerShell:

```powershell
.\.venv\Scripts\python.exe -m rankprobe audit "D:/my evaluation/sampled-predictions.csv" --cutoffs 1,10 --out reports/sampled-report
```

macOS / Linux:

```sh
.venv/bin/python -m rankprobe audit "/absolute/path/to/sampled-predictions.csv" --cutoffs 1,10 --out reports/sampled-report
```

`positive_index=0` (CLI `--positive-index 0`) is an explicit assertion about this dataset protocol. It labels only that observed positive; other candidates remain unknown by default. The native framework evaluates under its own sampled-negative assumptions. Do not silently copy those assumptions into an audit of real relevance judgments.

Before comparing native `HR@k` with this report, read [Hit/HR and Recall](metrics.md#native-hithr-and-recall); RankProbe does not report a Hit/HR field.

The default local identity mode assigns each row a distinct `query_000001`, etc. Thus two interaction rows from the same source user remain separate prediction contexts. Item tokens are remapped consistently within this one export. Original IDs and their mapping are omitted from the CSV/metadata, and this is pseudonymization, not an anonymity guarantee. Cross-run comparison requires the same source row order and item mapping; shuffled independent exports are not aligned merely because they have the same generated names.

For cross-run comparisons, add your existing stable event/context IDs to the capture, in the exact scored row order:

```python
# stable_event_ids comes from your evaluation records, not generated user numbers.
# It must distinguish different time/history contexts belonging to the same user.
query_ids = np.asarray(stable_event_ids)
with Path("sampled-scores-with-events.npz").open("xb") as handle:
    np.savez(handle, scores=scores, item_id=candidate_ids, query_id=query_ids)
```

Change the `export_npz` source argument to `Path("sampled-scores-with-events.npz")` and add `identity="source"` (the equivalent CLI option is `--identity source`), using new output filenames. This mode requires unique string event IDs and preserves original item IDs. It can expose physical candidate-pool changes that local first-appearance pseudonyms conceal. It does not prove that independently supplied IDs refer to the same real event or shared item namespace, and it retains potentially identifying source tokens. See [adapter identity rules](adapters.md) before sharing or comparing exports.

The sampled NPZ recipe excludes `test_all=True`. That path needs the separate helper below because it has different catalog/click masking and repeats the observed target in its candidate universe. The RecBole mask helper uses different dataset contracts and cannot be applied to it by renaming objects.

### Why full-sort needs a separate contract

In this source's `GeneralModel.Dataset`, full-sort columns are `[observed_target, 1, ..., n_items-1]`. Column zero is the target, **not padding**. Its catalog copy appears again at the column equal to its item ID. `BaseRunner.predict` masks catalog columns listed in `train_clicked_set | residual_clicked_set`, leaving the special target column untouched. The inspected [`BaseReader`](https://github.com/THUwangcy/ReChorus/blob/c164ec4303cc20ddcfbd1b57de366a481811d1e5/src/helpers/BaseReader.py) constructs residual clicks from both dev and test interactions, without filtering by the individual event's time. The target's catalog duplicate and other held-out items can therefore be masked too.

These are source-specific evaluation choices; they do not establish a leakage defect or a causal history policy. A portable export needs separate reasons for training clicks, residual dev/test clicks and the target duplicate, and must preserve the finite target at column zero. The NPZ exporter rejects the raw nonfinite matrix. Do not apply a RecBole-style "remove padding column zero" rule: that would remove the observed positive while its catalog duplicate is already masked.

The integration checker includes a bounded rejection probe using an actual `BaseReader` over original tiny synthetic CSVs, then the actual dataset and runner. It verifies the masks and finite target before asserting that raw NPZ export fails without writing a CSV. This probe establishes the input obstacle; it does not certify the evaluation protocol.

### Export the checked base full-sort contract

`scripts/export_rechorus_full_sort.py` is a separate NumPy-only source helper for the standard `GeneralModel.Dataset` dev/test contract. It accepts the complete runner matrix and the same dataset, with caller-supplied unique event IDs in the exact scored row order:

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path("path/to/rankprobe/scripts").resolve()))
from export_rechorus_full_sort import export_full_sort

test_data = data_dict["test"]  # model.test_all must be 1 / True
scores = runner.predict(test_data)
metadata = export_full_sort(scores, test_data, stable_event_ids, Path("full-sort-export"))
```

`stable_event_ids` must identify the actual prediction contexts from your evaluation records. Multiple interactions from one user need different IDs; a user ID alone is insufficient. The helper validates uniqueness and shape but cannot establish that separately supplied IDs or score rows refer to the same real context.

The new destination's parent must exist; existing destinations and symbolic-link ancestors are refused. The helper verifies each individual dataset row has the base `user_id,item_id` fields and the exact `[target,1..n_items-1]` candidate order. Custom/sequence/context dataset rows with extra fields are rejected by this first bounded bridge. Scores must be float16/32/64, with `-inf` at precisely the native clicked catalog positions and finite values everywhere else. The target catalog duplicate must already be masked by the declared native union; the exporter does not create additional masks.

It writes `predictions.csv` and `exclusions.json`. The retained observed target has relevance 1 under this explicit one-positive convention; other eligible candidates remain unknown. Source item IDs become exact decimal strings, and supplied event IDs are retained. Metadata records overlapping `train_clicked`, `residual_clicked` and `own_target_catalog_duplicate` reasons. Their counts can overlap and must not be summed as distinct exclusions. Real exported identifiers can identify people, so review before sharing.

Record the absolute location of `full-sort-export` in the model process before changing directories. Return to the RankProbe package folder and use the separate core interpreter, substituting your actual exported path.

Windows PowerShell:

```powershell
.\.venv\Scripts\python.exe -m rankprobe audit "D:/my evaluation/full-sort-export/predictions.csv" --cutoffs 1,10 --out reports/full-sort-report
```

macOS / Linux:

```sh
.venv/bin/python -m rankprobe audit "/absolute/path/to/full-sort-export/predictions.csv" --cutoffs 1,10 --out reports/full-sort-report
```

Inspect the exclusion sidecar alongside report coverage. Residual clicks include dev/test observations under the pinned upstream policy; they are not necessarily information available before each event. Unexpected NaN, positive infinity or unmasked negative infinity fails before output, rather than being silently discarded. This bridge consumes the complete matrix already returned by the upstream runner; it does not stream model inference. Begin with a small permitted subset and account for catalog-sized CSV and exclusion metadata. The adapter neither fills unknown labels with zero nor asserts complete judgments, native metric parity, or support for all upstream model families.

## Interpret expected tie differences

ReChorus's inspected [`evaluate_method`](https://github.com/THUwangcy/ReChorus/blob/c164ec4303cc20ddcfbd1b57de366a481811d1e5/src/helpers/BaseRunner.py#L52) ranks the observed positive by counting scores greater than **or equal to** its score. A negative with the same score therefore pushes the positive down. RankProbe defaults to ascending item-token order within exact ties. The same scores can produce different NDCG without either evaluator having an arithmetic defect.

For a completely judged synthetic row with one positive tied for first with one negative, a positive token sorting first yields NDCG@1 = 1 in RankProbe and 0 in the inspected native evaluator. That separate reference probe explicitly declares the synthetic negatives. The normal sparse export does not infer those zeros. Inspect tie bounds, eligibility and recorded protocol before comparing reported numbers.

## Inspect repeated negative draws separately

Repeated candidates are another possible cause of disagreement, even without a tie involving the positive. In the pinned [Grocery preprocessing notebook](https://github.com/THUwangcy/ReChorus/blob/c164ec4303cc20ddcfbd1b57de366a481811d1e5/data/Grocery_and_Gourmet_Food/Amazon.ipynb), `generate_dev_test` draws negatives with `np.random.randint` and resamples clicked items, without excluding previously drawn negatives. This source permits repeated draws; it does not establish their frequency in any released split. Other preprocessors differ, so do not generalize this observation to every ReChorus dataset.

The prepared dataset and exporter retain repeated item IDs. The native evaluator counts score columns when finding the positive's rank, while RankProbe's main metrics use unique items with the declared maximum-score duplicate policy. Inspect the report's duplicate counts and raw-row sensitivity before interpreting a difference. Repeated sampling may be intentional; a diagnostic does not justify replacing a frozen benchmark protocol. The [existing duplicate example](../examples/duplicates.csv) and [metric semantics](metrics.md#ordering-relevance-and-duplicate-rows) explain that boundary.

The bounded check uses an original event with candidates `[P,H,H,L]` and scores `[0.5,0.9,0.9,0.1]`: the positive has column rank 3 and unique-item rank 2, with no positive-score tie. Its normal export labels only P and leaves H/L unknown, so NDCG remains unavailable. A separate explicitly fully judged synthetic control isolates multiplicity: native NDCG@2 and raw-row NDCG@2 are 0, while unique-item NDCG@2 is `1/log2(3)`. Those planted labels are never copied into the normal export. This is a protocol boundary, not a corrected benchmark score or general metric-parity claim.

## Reproduce the bounded integration

With the verified source checkout and CPU helper dependencies used by CI:

```sh
python scripts/check_rechorus_workflow.py --source path/to/ReChorus --out rechorus-workflow-example
```

The check uses normally imported official `BaseRunner` and `GeneralModel.Dataset` on original synthetic data. It exercises prepared dataset rows, collation, model scoring and the actual runner prediction loop, then captures NPZ and calls the existing RankProbe exporter and installed CLI. Separate native evaluator probes isolate the positive-tie and repeated-negative boundaries above. The full-sort workflow adds actual `BaseReader` construction from tiny generated CSVs, raw NPZ rejection, mask-aware safe export and a separate installed-CLI report. The default-buffer path verifies cached feeds remain unchanged, and a separate mode-switch probe checks rejection of stale sampled candidates. It does not execute the public preprocessing notebooks, train a model, use the bundled benchmark data, or validate all upstream model families.

CI verifies source archive SHA256 `0e66340a9d496ca6277ded4f6f0b51f92bf739eba4f26a14d1e8a26cb0c75cd1`, extracts only the source subtree and checks the runner/model source bytes before execution. The upstream archive contains bundled dataset files, but those are not extracted, loaded or used by this job. The checker never imports `main.py` and does not execute its presentation exporter; the CSV limitation above is established from the fixed source.

The source helper/checker are shipped in the source distribution, not as installed CLI subcommands. Current-head CI and its synthetic artifact provide execution evidence. External adoption, human time saved and general metric parity remain unmeasured.
