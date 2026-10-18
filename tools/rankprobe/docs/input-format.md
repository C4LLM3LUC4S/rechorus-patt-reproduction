# Input contract

RankProbe reads UTF-8 CSV, JSONL, and TREC-style run/qrels text, including a UTF-8 BOM. Use a header in CSV and one JSON object per nonempty JSONL line. CSV / JSONL fields have exact names; aliases such as `label`, `docid`, or `user` are not guessed.

With the default `auto` format, `.csv` and `.jsonl` select those loaders; `.run` / `.trec` select TREC predictions and `.qrels` selects TREC judgments. Other extensions require an explicit `--input-format` or `--qrels-format` (`csv`, `jsonl`, or `trec`). File contents are not guessed. In `compare`, `auto` detects each run separately; an explicit input format applies to every run.

### CSV field-size errors

CSV parsing reads every column before RankProbe selects the evaluation fields. A long document body or metadata value can therefore exceed [Python's current CSV field-size limit](https://docs.python.org/3.12/library/csv.html#csv.field_size_limit), even in an unused column. RankProbe preserves that limit; it does not silently shorten values or change the process-wide parser setting.

If the error says `field larger than field limit`, export a **new copy** from your source with only `query_id,item_id,score` and any supplied `relevance` for predictions, or `query_id,item_id,relevance` for qrels. Keep identifiers, scores, judgments and row order unchanged; missing prediction judgments must stay unknown. Alternatively, export equivalent JSONL from your source. JSONL avoids the CSV parser's field-size limit but retains RankProbe's identifier and numeric validation. Preserve the original export for comparison.

## Prediction rows

| Field | Required | Meaning |
| --- | --- | --- |
| `query_id` | Yes | A nonempty identifier for one ranking event |
| `item_id` | Yes | A nonempty candidate identifier within that event |
| `score` | Yes | A finite numeric score; larger ranks first |
| `relevance` | No | A finite, nonnegative judgment; blank or null means unknown |

Identifiers must be strings. CSV fields are strings; JSONL identifiers must be quoted strings, not numbers. Keep their spelling consistent across files. IDs such as `01` and `1` are different; ascending string ordering puts `10` before `2`. Identifiers are not automatically normalized, so remove unintended whitespace before exporting.

Identifiers must be UTF-8 encodable text. Malformed Unicode, such as an unpaired surrogate in a JSON escape, is rejected during input validation with the affected field; file loaders also include the source and line. Normal Chinese text, emoji and valid JSON surrogate pairs are preserved without changing the identifier.

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

Keep judgments consistent between inline labels and qrels. Conflicts are rejected as invalid input rather than reconciled by an undocumented convention. Duplicate qrels pairs are also rejected. CSV / JSONL qrels require a known, finite nonnegative relevance value; blank, missing, null, and negative values are rejected. Inline prediction labels may still be unknown.

`--qrels-complete` declares that the independent judgments cover all relevant items for the evaluated queries. This can justify a Recall denominator; it does not prove corpus completeness. Queries absent from the qrels still lack evidence and are not automatically assigned all-zero judgments. `--unjudged nonrelevant` is a separate explicit protocol choice; the report records it.

Explicit unknown qrels judgments are supported through TREC `-1` or Python API `None`. They remain unknown when no known inline judgment is supplied; they do not erase a known inline label. A qrels-completeness assertion is rejected if the supplied judgments include any explicit unknowns, even when `--unjudged nonrelevant` is selected or an inline label is available. Fix or remove the completeness assertion; a convention cannot supply the missing evidence.

## TREC-style retrieval files

Prediction records have exactly six whitespace-separated fields and no header:

```text
q1 Q0 doc_b 1 0.8 baseline
q1 Q0 doc_a 2 0.8 baseline
```

The positions are `query_id iteration item_id rank score run_tag`. Query and item IDs are strings without whitespace. Rank must contain only ASCII digits representing an integer greater than or equal to zero; signs and fractions are rejected. It does not order the result: RankProbe sorts finite scores descending and resolves equal scores with the declared tie policy. Iteration and run tag are parsed but not used. To compare multiple systems, supply separate named files; tags do not split a file into runs.

Judgment records have exactly four whitespace-separated fields:

```text
q1 0 doc_a 0
q1 0 doc_b 1
q1 0 doc_unknown -1
```

The positions are `query_id iteration item_id relevance`; iteration is not used. Relevance `-1` means explicitly unjudged and becomes `None` in the Python API. It is never silently changed to zero. Other negative values and nonfinite values are rejected. RankProbe also accepts finite nonnegative fractional judgments as an extension; the [official trec_eval qrels contract](https://raw.githubusercontent.com/usnistgov/trec_eval/main/formats.c) specifies integer grades below 128, or -1. Fractional grades do not establish trec_eval compatibility.

Blank lines and lines whose first non-whitespace character is `#` are ignored in these text files. Inline comments, extra columns, embedded whitespace in IDs, NUL characters, and malformed records are rejected. This exact-column contract is stricter than trec_eval's acceptance of trailing run fields.

For a known run with expendable trailing fields, the source checkout includes an [explicit normalization helper](trec-normalization.md). It validates a new six-field copy and preserves the original; regular import remains strict.

```sh
python -m rankprobe audit baseline.run --qrels judgments.qrels --out reports/retrieval
python -m rankprobe audit results.txt --input-format trec --qrels labels.txt --qrels-format trec --out reports/text-input
```

The [NIST qrels explanation](https://trec.nist.gov/data/qrels_eng/) documents a historical evaluation convention that treats absent judgments as nonrelevant. RankProbe defaults to preserving uncertainty. Select `--unjudged nonrelevant` only when that is your intended evaluation assumption; inspect excluded queries either way. Reading a TREC file does not select trec_eval's tie or averaging conventions. See the [synthetic retrieval walkthrough](../examples/trec/README.md).

## Comparing runs

```sh
python -m rankprobe compare --run model_a=a.csv --run model_b=b.jsonl --out reports/comparison
```

Use a descriptive name before `=`. Do not compare remapped IDs from independently generated mappings without verifying alignment. Matching IDs, candidate sets, and labels establish only file-level agreement; they do not prove identical train/test splits, model selection, preprocessing, or tokenization.

Save the report alongside experiment configuration, data version, framework version, and the process that exported predictions. These records provide context the score file cannot contain.

## Python numeric values

Use finite Python `int` or `float` values for `Row` scores and known relevance, qrels grades, and `Protocol.relevance_threshold`. Booleans are rejected. Other numeric objects, such as `Fraction` and NumPy scalar types that are not Python `int`/`float` instances, are rejected before evaluation rather than failing when the report is serialized. NumPy is not a core dependency.

Convert array-library scalars explicitly at your API boundary: use `int(integer_scalar)` for an integer value, or `float(floating_scalar)` for a floating value. Do not convert integer scores or grades indiscriminately to float: large integers can lose precision. Converting an already rounded floating value cannot recover the original precision. See [numeric precision and metric semantics](metrics.md#ordering-relevance-and-duplicate-rows).
