# Independent judgments and export identities

These original synthetic files isolate one integration mistake: attaching source-ID qrels to an export that replaced its item IDs with local pseudonyms. They also include a valid outside-pool control. Successful parsing or a perfect MRR value cannot establish that independent judgments matched the intended candidates.

The source capture has one event `query_000001`, items `positive,other`, scores `0.75,0.25`, and a declared positive in column zero. The optional NPZ exporter produces `local.csv` in its default mode and `source.csv` with `--identity source`. The event token deliberately matches the generated local event name, so only item identity differs. The first inline positive is retained in both files; the other inline label stays unknown. The files are fixed text fixtures, not authenticated provenance records or a real model export.

Run these commands from the package root after installing RankProbe. They use existing files and separate report destinations; NumPy is not required to inspect the fixtures.

```sh
python -m rankprobe audit examples/npz-qrels/local.csv --qrels examples/npz-qrels/judgments.csv --cutoffs 1,2 --out reports/qrels-local
python -m rankprobe audit examples/npz-qrels/source.csv --qrels examples/npz-qrels/judgments.csv --cutoffs 1,2 --out reports/qrels-source
python -m rankprobe audit examples/npz-qrels/source.csv --qrels examples/npz-qrels/outside-pool-qrels.csv --cutoffs 1,2 --out reports/qrels-outside
```

| Case | Supplied candidate labels | Unknown candidates | MRR@1 | NDCG@2 |
| --- | --- | --- | --- | --- |
| Local pseudonyms with source-ID qrels | 1 inline; no qrels pair matches | 1 | 1 | Unavailable |
| Preserved source IDs with matching qrels | 2; both qrels pairs match | 0 | 1 | 1 |
| Preserved IDs with legitimate outside-pool qrels | 1 inline; no qrels pair matches | 1 | 1 | Unavailable |

All three keep zero assumed nonrelevant candidates, incomplete qrels and one submitted query. MRR@1 is already determined by the known first inline positive; it is not evidence that the qrels matched. The first and third cases have the same metric/coverage behavior for different reasons. None is automatically rejected as an ID mismatch. The current summary's `judged_candidates` combines known inline labels and matching known qrels, so it is not a count of matches supplied by the qrels alone.

## Check and recover the intended association

1. Compare exact query **and item** tokens with the original evaluation export. A shared query ID or two arrays of the same shape is insufficient. Check the declared event meaning and item namespace; preserve intentional whitespace and distinct tokens.
2. Inspect unknown-candidate examples and the `qrels_queries_without_predictions` finding when present. A missing-query warning addresses a different boundary from this same-query item mismatch. Judged items outside the retrieved pool can be valid evidence for the ideal ranking; zero overlap alone does not prove a bad join.
3. If local remapping caused the problem and the complete original capture has stable event IDs, make a **new** export with [`--identity source`](../../docs/adapters.md#identity-and-privacy), keep the original judgments unchanged, and confirm export success before auditing it. Review the newly retained identifiers for privacy. Source mode cannot reconstruct missing event IDs or certify the caller's alignment assertion.
4. Recheck the actual pair keys, scores, supplied/unknown/assumed counts and metric coverage. Keep the old export and report for comparison. Do not rename items by row position, attach an invented mapping, discard outside-pool qrels, add zeros, or declare qrels complete to obtain a number.

For a full software reproduction of the export stage, create a new named NPZ using the source arrays stated above and follow the [NPZ capture and export contract](../../docs/adapters.md). For another evaluator, preserve its actual event and item identities rather than copying these fixture tokens. This example establishes a recoverable software association, not real-user adoption or time saved.
