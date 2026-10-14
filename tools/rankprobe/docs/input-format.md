# Input contract

RankProbe reads UTF-8 CSV (including a UTF-8 BOM) and JSONL. Use a header in CSV and one JSON object per nonempty JSONL line. Fields have exact names; aliases such as `label`, `docid`, or `user` are not guessed.

## Prediction rows

| Field | Required | Meaning |
| --- | --- | --- |
| `query_id` | Yes | A nonempty identifier for one ranking event |
| `item_id` | Yes | A nonempty candidate identifier within that event |
| `score` | Yes | A finite numeric score; larger ranks first |
| `relevance` | No | A finite, nonnegative judgment; blank or null means unknown |

Identifiers must be strings. CSV fields are strings; JSONL identifiers must be quoted strings, not numbers. Keep their spelling consistent across files. IDs such as `01` and `1` are different; ascending string ordering puts `10` before `2`. Identifiers are not automatically normalized, so remove unintended whitespace before exporting.

```csv
query_id,item_id,score,relevance
request_001,item_a,1.2,2
request_001,item_b,0.8,0
request_002,item_b,-0.3,
```

```json
{"query_id":"request_001","item_id":"item_a","score":1.2,"relevance":2}
{"query_id":"request_001","item_id":"item_b","score":0.8,"relevance":0}
{"query_id":"request_002","item_id":"item_b","score":-0.3,"relevance":null}
```

Do not supply a rank in the score column. Convert a distance to a score only if its direction is known, for example `score = -distance`. Infinite padding scores, NaN, booleans, negative relevance, malformed records, and missing required fields are rejected rather than coerced into valid predictions.

One query may span nonadjacent rows. File order within a query matters only under the explicit `input` tie policy and in diagnostic comparisons. Duplicate `(query_id, item_id)` rows are an audit finding; they are not silently treated as independent documents.

For recommendation, a user can have several target events. Give each event a distinct query ID. Do not merge all predictions for that user into one query. For run comparison, query and item IDs must refer to the same events and candidates in every run.

## Independent qrels

A qrels file has `query_id,item_id,relevance`, with no score required. It may include judged items absent from the prediction file. Those items matter to the known-judgment ideal ranking and, if the qrels are declared complete, the Recall denominator.

```csv
query_id,item_id,relevance
request_001,item_a,2
request_001,item_b,0
request_001,not_retrieved,1
```

```sh
python -m rankprobe audit predictions.csv --qrels judgments.csv --out reports/audit
```

Keep judgments consistent between inline labels and qrels. Conflicts are rejected as invalid input rather than reconciled by an undocumented convention. Duplicate qrels pairs are also rejected. Missing relevance is not automatically zero.

`--qrels-complete` declares that the independent judgments cover all relevant items for the evaluated queries. This can justify a Recall denominator; it does not prove corpus completeness. Queries absent from the qrels still lack evidence and are not automatically assigned all-zero judgments. `--unjudged nonrelevant` is a separate explicit protocol choice; the report records it.

## Comparing runs

```sh
python -m rankprobe compare --run model_a=a.csv --run model_b=b.jsonl --out reports/comparison
```

Use a descriptive name before `=`. Do not compare remapped IDs from independently generated mappings without verifying alignment. Matching IDs, candidate sets, and labels establish only file-level agreement; they do not prove identical train/test splits, model selection, preprocessing, or tokenization.

Save the report alongside experiment configuration, data version, framework version, and the process that exported predictions. These records provide context the score file cannot contain.
