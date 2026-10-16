# Importing a TREC run with trailing fields

The [official trec_eval format](https://github.com/usnistgov/trec_eval/blob/ba38899cbd4de0fb699b47f39b64ef1c107e4a5c/formats.c#L228-L245) allows ignored text after the six run fields. RankProbe deliberately requires exactly six. A legitimate upstream test file, `test/results.trunc`, exposed this integration boundary: direct import failed before a comparison report could be produced.

## Explicit conversion

From a source checkout with RankProbe installed, run:

```sh
python scripts/normalize_trec_run.py results.trunc normalized.run
python -m rankprobe compare --run full=full.run --run truncated=normalized.run --qrels judgments.qrels --out reports/coverage
```

The helper copies the first six fields into a **new file** and validates every retained record with RankProbe's strict loader before creating the output. It prints row counts, the number of rows whose trailing fields were removed, and SHA256 hashes of both files. Save this JSON summary with your experiment so the original export remains traceable; the later report hashes the normalized input. Existing outputs and source aliases are refused. The helper does not download inputs or change the source, scores, identifier spelling, row order, duplicates, or judgments. Blank/comment lines are retained; whitespace and the UTF-8 BOM may be normalized.

This is an explicitly lossy conversion. Use it only after deciding that the trailing text is expendable. It is discarded, not interpreted as labels or metadata. This helper is for prediction runs, not qrels; use a `.run` output name for automatic format detection. Too few fields, invalid ranks, nonfinite scores, NUL characters and empty runs still fail. The normal `audit`/`compare` commands continue to reject extra fields; this conversion does not silently change their contract.

## Observed public integration case

Local validation used unmodified NIST inputs at commit `ba38899cbd4de0fb699b47f39b64ef1c107e4a5c`. The upstream [quicktest](https://github.com/usnistgov/trec_eval/blob/ba38899cbd4de0fb699b47f39b64ef1c107e4a5c/Makefile#L65-L66) actually exercises `results.trunc`; it is an intended compatibility fixture. The inputs remain in ignored local artifacts and are not redistributed with RankProbe.

| Observation | Actual result |
| --- | --- |
| Direct strict import | Rejected at line 1 for extra fields |
| Explicit normalization | 584 records; five records had trailing text removed |
| Independent first-six-fields comparison | Query IDs, document IDs, score values and ordering agreed for all 584 records |
| Source preservation | SHA256 remained `4a85d6b7b21b69b59728fa0aa7452199640f70d96529b86d0cca8f9c9292e438` |
| Full versus truncated report | Full run has queries 301/302/303; truncated run has 301/303, so query 302 is missing; candidate sets also differ |
| Judgment handling | Missing labels remained unknown; this case does not justify complete-qrels or nonrelevant assumptions |

One local CLI normalization took approximately 0.228 seconds on Windows / Python 3.12.5, including interpreter startup. This is a single observation, not a performance benchmark. It removes a demonstrated manual file-cleanup step and enables a report that identifies an actual coverage difference. It does not establish an erroneous model claim: the upstream truncation is intentional. No human completion-time baseline, repeat-use evidence, or time-saving percentage has been measured. Machine execution time is a local observation, not human time saved. Numerical parity with the trec_eval executable has not been established.
