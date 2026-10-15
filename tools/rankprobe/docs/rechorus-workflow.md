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

This first recipe excludes `test_all=True`. That path has different catalog/history masking and can repeat the observed target in its candidate universe. The RecBole mask helper uses different dataset contracts and cannot be applied to it by renaming objects.

## Interpret expected tie differences

ReChorus's inspected [`evaluate_method`](https://github.com/THUwangcy/ReChorus/blob/c164ec4303cc20ddcfbd1b57de366a481811d1e5/src/helpers/BaseRunner.py#L52) ranks the observed positive by counting scores greater than **or equal to** its score. A negative with the same score therefore pushes the positive down. RankProbe defaults to ascending item-token order within exact ties. The same scores can produce different NDCG without either evaluator having an arithmetic defect.

For a completely judged synthetic row with one positive tied for first with one negative, a positive token sorting first yields NDCG@1 = 1 in RankProbe and 0 in the inspected native evaluator. That separate reference probe explicitly declares the synthetic negatives. The normal sparse export does not infer those zeros. Inspect tie bounds, eligibility and recorded protocol before comparing reported numbers.

## Reproduce the bounded integration

With the verified source checkout and CPU helper dependencies used by CI:

```sh
python scripts/check_rechorus_workflow.py --source path/to/ReChorus --out rechorus-workflow-example
```

The check uses normally imported official `BaseRunner` and `GeneralModel.Dataset` on original synthetic data. It exercises prepared dataset rows, collation, model scoring and the actual runner prediction loop, then captures NPZ and calls the existing RankProbe exporter and installed CLI. A separate native evaluator probe asserts the expected tie difference. It does not train a model, use the bundled benchmark data, or validate all upstream model families.

CI verifies source archive SHA256 `0e66340a9d496ca6277ded4f6f0b51f92bf739eba4f26a14d1e8a26cb0c75cd1`, extracts only the source subtree and checks the runner/model source bytes before execution. The upstream archive contains bundled dataset files, but those are not extracted, loaded or used by this job. The checker never imports `main.py` and does not execute its presentation exporter; the CSV limitation above is established from the fixed source.

The source helper/checker are shipped in the source distribution, not as installed CLI subcommands. Current-head CI and its synthetic artifact provide execution evidence. External adoption, human time saved and general metric parity remain unmeasured.
