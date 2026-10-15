# Optional NPZ exporter

`scripts/export_rechorus.py` independently exports a documented ReChorus-style convention. It imports NumPy, not a training framework. Install optional support with:

```sh
python -m pip install -e ".[adapters]"
```

## Required source assumptions

The NPZ must have equally shaped, nonempty 2-D `scores` and `item_id` arrays. Rows are ranking events; columns are candidates. Scores must be finite real numbers. Object arrays are not loaded (`allow_pickle=False`). An optional `user_id` array is checked for row count but never exported.

You must explicitly declare the positive column. The exporter does not infer it from a larger score or framework name. By default every other candidate remains unjudged:

```sh
python scripts/export_rechorus.py test_predictions.npz --out local_export.csv --positive-index 0 --limit-queries 100
```

For a verified one-positive sampled evaluation protocol, explicitly declare the remaining sampled candidates nonrelevant:

```sh
python scripts/export_rechorus.py test_predictions.npz --out local_export.csv --positive-index 0 --other-candidates nonrelevant --limit-queries 100
```

The labels record that assumption. They are not proof that those items are truly irrelevant in the whole corpus. Multiple-positive conventions, ragged candidate arrays, padding scores, and alternative archive fields need a different declared adapter. A repeated declared positive is rejected because this convention would assign contradictory labels to one item.

## Identity and privacy

Each matrix row receives `query_000001`, etc., including multiple events for the same user. Item IDs are mapped to `item_000001`, etc., in first-appearance order. The mapping is not exported. Source user IDs, file paths, and original item IDs are omitted from the CSV and metadata.

Mappings are local to each export. Cross-run comparison requires aligned source rows and an identical item mapping; independently shuffled exports do not satisfy that requirement merely because the remapped names look alike. For general comparisons, export stable, appropriately protected event and item IDs directly from the originating evaluation pipeline.

This is pseudonymization, not a guarantee of anonymity: scores and relationships can still identify an experiment or user activity. It also does not confer permission to redistribute a dataset or derivative prediction file.

## Output and reproducibility

The exporter writes CSV and `<output>.metadata.json`. Metadata records a source SHA-256, selected query count, positive column, negative assumption, and remapping caveats. Existing outputs are refused unless `--overwrite` is explicit; the source archive cannot be chosen as an output. No complete qrels are inferred.

Source archives are read only. To keep local experiments private, store exports and reports outside the repository or under an ignored directory. Public examples in this repository are synthetic. Real experiment validation should publish only reviewed aggregate observations with clear data-use permission.
## TREC run compatibility

An explicit [TREC normalization helper](trec-normalization.md) handles the trailing run fields allowed by trec_eval. It creates a validated new file, refuses overwrites, and prints source/output hashes. The documented NIST case records the actual import obstacle and the query-coverage difference that becomes inspectable after conversion. This helper requires an installed RankProbe and the source checkout; it is not a new installed CLI subcommand.
