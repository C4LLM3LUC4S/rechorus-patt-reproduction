# Verification record

Recorded on 2026-10-15 for the initial `0.1.0a1` implementation. These observations describe checks actually run locally, not remote CI, outside adoption, or a complete benchmark study. Further changes require rerunning affected checks.

## Public examples

The documented audit, compare, and demo commands were exercised from the renamed `rankprobe` source checkout on Windows with Python 3.12.5. The source directory was set on `PYTHONPATH` for this check; independent built-wheel installation is a separate validation gate. Each completed example produced parseable JSON and an HTML file.

| Case | Observed result |
| --- | --- |
| Built-in demo | Reports deliberate duplicates, exact ties, constant scores, unknown labels, and limited judgment scope |
| Clean CSV | MRR@1 = 0.5; MRR@5 = 0.75; linear candidate-pool NDCG@5 ≈ 0.815464876786 |
| Tied CSV, item-ID ordering | MRR@5 = 1/3 |
| Tied CSV, input ordering | MRR@5 = 1 |
| Equivalent tied JSONL | Metric dictionaries equal the CSV result |
| Duplicate CSV | Reports repeated candidates, including distinct scores for a repeated item |
| Independent complete miniature qrels | Recall@5 = 0.75 |
| Unjudged predictions without qrels | Metric values remain unavailable rather than assuming zero labels |
| Different query and candidate pools | Reports query coverage and candidate-set mismatches |
| Changed cross-run judgment | Reports an error; default command exits 1 |

The clean metric values and complete-miniature Recall were checked against hand calculations with absolute tolerance `1e-12`. The complete-qrels declaration is justified for the invented miniature dataset, not inferred for real experiments.

## CLI behavior

Locally confirmed:

- `--version` reports `RankProbe 0.1.0a1`.
- Findings below the default error threshold allow exit 0.
- `--fail-on warning` causes the tied example to exit 1.
- `--fail-on never` allows a completed report containing the cross-run judgment error to exit 0.
- A nonexistent input still exits 2 under `--fail-on never`.

Local Markdown links were checked after the rename. The official context links were read for the initial documentation, and the unrelated RankAudit project's original name and URL were retained.

## Optional adapter

The adapter's focused tests passed locally, covering event identity despite repeated users, ID remapping, unknown default labels, explicit negative assumptions, row limits, malformed arrays, source protection, existing-output protection, and disabled pickle loading. Ruff passed for the adapter and its tests.

A read-only local integration check exported the first 100 events from a saved Grocery PAtt2 experiment. It retained 100 candidates per event: 10,000 rows and 9,950 unique query-item pairs, including 50 extra duplicate rows. The audit reported no errors, one duplicate warning, and one limited-reference informational finding. MRR@5 was approximately 0.242667 and candidate-pool NDCG@5 approximately 0.281926; Recall was not checked because no complete independent qrels were available.

Those are observations on one selected local sample. They do not establish full-run accuracy, equality to the framework's frozen primary protocol, distributional representativeness, or external user value. No private source archive, exported real predictions, original IDs, or real-data report is distributed in this repository.

## Independent checks and installation

The final local suite at this stage passed 88 tests. An independent reviewer
exhaustively checked within-tie permutations for 50 five-candidate cases and
found no discrepancy in the reported metric bounds. The review also exposed
the qrels-only-query coverage blind spot, which was fixed and regression-tested.

A separate seeded reference check made 2,400 MRR/NDCG assertions over 200
random, uniquely scored 20-candidate cases and both gain functions. NDCG was
compared with scikit-learn 1.9.0, with maximum absolute error
2.220446049250313e-16. This comparison does not establish parity under ties or
incomplete judgments. A single local 100,000-row/1,000-query audit took about
3.39 seconds; it is an observation, not a throughput or scaling guarantee.

Wheel and source distributions were built. The wheel was installed with no
runtime dependencies into a fresh virtual environment, and both isolated
`python -I -m rankprobe demo` and the installed `rankprobe --version` entry point
ran successfully. The offline report was visually inspected at desktop width
and 390px mobile width; no page-wide horizontal overflow was observed.

## Pending evidence

Configured cross-platform CI does not count as passed until remote jobs run. External users, repeat adoption, paid demand, and research findings have not yet been established. See [validation-plan.md](validation-plan.md) for the remaining decision gates.
