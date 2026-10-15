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

Then, from the RankProbe source checkout in an environment with `.[adapters]` installed:

```sh
python scripts/export_rechorus.py sampled-scores.npz --out sampled-predictions.csv --positive-index 0
python -m rankprobe audit sampled-predictions.csv --cutoffs 1,10 --out sampled-report
```

`--positive-index 0` is an explicit assertion about this dataset protocol. It labels only that observed positive; other candidates remain unknown by default. The native framework evaluates under its own sampled-negative assumptions. Do not silently copy those assumptions into an audit of real relevance judgments.

The default local identity mode assigns each row a distinct `query_000001`, etc. Thus two interaction rows from the same source user remain separate prediction contexts. Item tokens are remapped consistently within this one export. Original IDs and their mapping are omitted from the CSV/metadata, and this is pseudonymization, not an anonymity guarantee. Cross-run comparison requires the same source row order and item mapping; shuffled independent exports are not aligned merely because they have the same generated names.

For cross-run comparisons, add your existing stable event/context IDs to the capture, in the exact scored row order:

```python
# stable_event_ids comes from your evaluation records, not generated user numbers.
# It must distinguish different time/history contexts belonging to the same user.
query_ids = np.asarray(stable_event_ids)
with Path("sampled-scores-with-events.npz").open("xb") as handle:
    np.savez(handle, scores=scores, item_id=candidate_ids, query_id=query_ids)
```

Then use `--identity source` with that NPZ. This mode requires unique string event IDs and preserves original item IDs. It can expose physical candidate-pool changes that local first-appearance pseudonyms conceal. It does not prove that independently supplied IDs refer to the same real event or shared item namespace, and it retains potentially identifying source tokens. See [adapter identity rules](adapters.md) before sharing or comparing exports.

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

```sh
python -m rankprobe audit full-sort-export/predictions.csv --cutoffs 1,10 --out full-sort-report
```

Inspect the exclusion sidecar alongside report coverage. Residual clicks include dev/test observations under the pinned upstream policy; they are not necessarily information available before each event. Unexpected NaN, positive infinity or unmasked negative infinity fails before output, rather than being silently discarded. This bridge consumes the complete matrix already returned by the upstream runner; it does not stream model inference. Begin with a small permitted subset and account for catalog-sized CSV and exclusion metadata. The adapter neither fills unknown labels with zero nor asserts complete judgments, native metric parity, or support for all upstream model families.

## Interpret expected tie differences

ReChorus's inspected [`evaluate_method`](https://github.com/THUwangcy/ReChorus/blob/c164ec4303cc20ddcfbd1b57de366a481811d1e5/src/helpers/BaseRunner.py#L52) ranks the observed positive by counting scores greater than **or equal to** its score. A negative with the same score therefore pushes the positive down. RankProbe defaults to ascending item-token order within exact ties. The same scores can produce different NDCG without either evaluator having an arithmetic defect.

For a completely judged synthetic row with one positive tied for first with one negative, a positive token sorting first yields NDCG@1 = 1 in RankProbe and 0 in the inspected native evaluator. That separate reference probe explicitly declares the synthetic negatives. The normal sparse export does not infer those zeros. Inspect tie bounds, eligibility and recorded protocol before comparing reported numbers.

## Reproduce the bounded integration

With the verified source checkout and CPU helper dependencies used by CI:

```sh
python scripts/check_rechorus_workflow.py --source path/to/ReChorus --out rechorus-workflow-example
```

The check uses normally imported official `BaseRunner` and `GeneralModel.Dataset` on original synthetic data. It exercises prepared dataset rows, collation, model scoring and the actual runner prediction loop, then captures NPZ and calls the existing RankProbe exporter and installed CLI. A separate native evaluator probe asserts the expected tie difference. The full-sort workflow adds actual `BaseReader` construction from tiny generated CSVs, raw NPZ rejection, mask-aware safe export and a separate installed-CLI report. It does not train a model, use the bundled benchmark data, or validate all upstream model families.

CI verifies source archive SHA256 `0e66340a9d496ca6277ded4f6f0b51f92bf739eba4f26a14d1e8a26cb0c75cd1`, extracts only the source subtree and checks the runner/model source bytes before execution. The upstream archive contains bundled dataset files, but those are not extracted, loaded or used by this job. The checker never imports `main.py` and does not execute its presentation exporter; the CSV limitation above is established from the fixed source.

The source helper/checker are shipped in the source distribution, not as installed CLI subcommands. Current-head CI and its synthetic artifact provide execution evidence. External adoption, human time saved and general metric parity remain unmeasured.
