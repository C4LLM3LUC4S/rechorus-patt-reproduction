# Verification record

## BEIR export/evaluation workflow (unchanged `0.1.0a3` core)

Read-only inspection of pinned BEIR source identified three concrete integration concerns: evaluation's default same-ID filter mutates the supplied results, run export defaults to 1000 candidates, and native qrels TSV has a different schema. The new [recipe](beir-workflow.md) uses the existing BEIR exporter and RankProbe TREC interface. Its optional checker imports the actual BEIR helper/evaluator, exports original synthetic results, transfers only existing judgments, invokes the installed RankProbe CLI, and checks report coverage and source hashes. It does not download a model/dataset or assert general BEIR numerical parity.

Five targeted tests passed locally on Windows / Python 3.12.5: existing-output preservation before optional imports, missing-dependency failure without output creation, missing-parent rejection, bounded CLI failure messages and an actual downstream CLI comparison with unknown labels and a changed candidate pool. Ruff and whitespace checks passed. BEIR is absent locally; these tests do not claim local BEIR execution. The separate optional CI job installs checksum-pinned BEIR source plus selected CPU export/evaluation dependencies, verifies the installed source bytes, then executes the actual workflow. Check the current-head run for its result.

## Executable trec_eval reference gate (unchanged `0.1.0a3` core)

Earlier NIST input checks did not execute the reference evaluator, so numerical agreement remained unverified. The new standard-library checker invokes an explicitly supplied executable on 4 fixed and 20 seeded original cases at cutoffs 1/2/5/10. It checks each query and the macro result for MRR, linear NDCG and Recall under a fully judged shared synthetic protocol. Four separate probes assert expected differences in ties, unknown labels, zero-positive Recall queries and qrels-only query handling. The [reproduction guide](trec-reference.md) states the exact protocol, reference source and four-decimal output tolerance.

The new 14 checker tests passed locally on Windows / Python 3.12.5, including malformed/duplicate/nonfinite reference output, original case preconditions, a constant-zero engine with valid output keys that must fail numerically, summary preservation and a path-free missing-executable error. Ruff and diff whitespace checks passed. The core evaluator and previous suites were not rerun locally because their code is unchanged. This machine has no usable C compiler/WSL environment. At head `30d766f`, [run 38681645099](https://github.com/C4LLM3LUC4S/rechorus-patt-reproduction/actions/runs/38681645099) passed all seven jobs. The Ubuntu reference job checksum-verified NIST source, built trec_eval 10.0-rc3 with GCC 13.3.0, passed official quicktest, completed 960 numerical comparisons and asserted all four protocol boundaries. Maximum absolute difference was 0.00005, within the four-decimal text tolerance. This result covers that head; later changes need their affected checks.

## Explicit trailing-field conversion (unchanged `0.1.0a3` core)

The previous real-input check stopped at a documented compatibility boundary: NIST's `test/results.trunc` has legal trailing run fields which the strict RankProbe loader rejects. The upstream format specification and quicktest confirmed that this is intended input. A new explicit source-checkout helper validates a separate six-field copy before creating the destination, refuses existing outputs/source aliases, and reports original/output hashes. It does not relax core parsing or add judgments. See [the case and commands](trec-normalization.md).

On Windows / Python 3.12.5, 53 targeted normalization and TREC-loader tests passed; Ruff passed for both new files. An independent read-only review found no blocking issue. The actual upstream case converted 584 records, removed trailing fields on five records, and agreed with an independently constructed first-six-fields reference on all rows and their order. Original bytes remained unchanged. One separate CLI conversion took 0.228 seconds including interpreter startup; no human time-saving baseline was measured. The full-versus-truncated report identified missing query 302 and a differing candidate pool for query 303, preserving unknown judgments. Source inputs and generated reports remain ignored local artifacts; only original code, synthetic tests and aggregate evidence are distributed. CI results must be checked for this exact commit.

## Built-wheel installation gate (unchanged `0.1.0a3` runtime)

Review of the previous workflow found a specific evidence gap: its demo ran after an editable development install, so it exercised the checkout rather than an independently installed wheel. The workflow now invokes the standard-library `scripts/check_wheel_install.py` after building and checking the distributions. Runtime code and metric definitions were not changed for this improvement.

On Windows / Python 3.12.5, the checker created an independent environment outside the checkout in a path containing spaces, installed the explicit local wheel without dependencies or an index, verified its module/distribution versions and local wheel hash, and ran the real Windows console launcher plus isolated module entry point. Demo and copied TREC comparison reports matched their known values, unknown-label exclusions and input hashes. Only RankProbe was added beyond the environment's bootstrap packages. Original wheel and fixture hashes remained unchanged.

Four focused integration probes then verified the gate itself: a wheel missing its console entry point failed at the launcher stage; a wheel declaring an unexpected core dependency failed before installation; an existing summary file was refused without changing its bytes; and a parent environment with synthetic source-path and index overrides still produced a correctly isolated installation. The malformed wheels stayed in ignored local artifacts. No old unit suite was rerun locally because its runtime code was unchanged. Ruff passed for the new checker. Cross-platform evidence must come from this commit's workflow, which now runs the same installation gate in each matrix job.

The first installation-gate CI run, [38671586033](https://github.com/C4LLM3LUC4S/rechorus-patt-reproduction/actions/runs/38671586033), passed the four Python 3.12/3.13 jobs but failed both Python 3.10 jobs at the recorded wheel hash check. Older bootstrap pip records the archive hash only when the input URL includes one. The installation target now includes the computed SHA256 fragment explicitly, preserving the required hash equality. The updated checker passed locally on Windows / Python 3.12.5; inspect the follow-up commit's workflow for cross-platform results.

## Comparison report alpha (`0.1.0a3`, 2026-10-15)

The local Windows / Python 3.12.5 suite passed **170 tests and 12 subtests**, with one symbolic-link-loop test skipped because Windows symlink privileges are unavailable. Ruff passed. The CLI integration check was updated to the new comparison headings.

An independent, read-only report review checked ten scenarios against the core JSON: both TREC tie policies, positive and negative deltas, changing metric eligibility, no matched pool, escaped long identifiers, and ID/pair/metric display limits. The report preserved the distinction between two structurally matched queries and one metric-eligible query in the synthetic retrieval case. Deltas unsupported by matching eligibility or reference scope remained unavailable. These agent checks are software verification, not evidence of independent human adoption.

The review first reproduced an HTML defect: delta tables omitted the actual delta column. The new Comparison results section places submitted and matched results side by side, displays the numerical delta, and retains each metric's coverage and reference. Coverage details now include exact excluded prediction-query IDs in JSON, bounded in HTML; qrels-only queries remain a separate population. Finding cards provide specific next steps and valid local navigation.

A separate numerical review reproduced exp2 NDCG@1 = 1 for a reversed ordering of the distinct grades `5e-324` and `1e-323`. Stable gain ratios correct this to 0.5, matching a 420-digit Decimal oracle; the corresponding matched-pool delta is 0.5 instead of zero. Regression checks also cover tiny normal grades, ordinary graded relevance, values near the scaling branch boundary, and a large dynamic range. No new runtime dependency was introduced.

The generated retrieval report was visually inspected at desktop and a 390px viewport. Page content did not overflow horizontally (desktop content width 1265px, mobile content width 375px with its scrollbar). Wide tables scroll inside their container; focusing the comparison table and pressing the right arrow moved its horizontal scroll position by 40px. The temporary viewport override was reset. Lint is now included in the cross-platform CI workflow; inspect the current PR commit's runs for remote results.

## Retrieval alpha (`0.1.0a2`, 2026-10-15)

The updated local suite passed **155 tests and 10 subtests** on Windows / Python 3.12.5; Ruff passed. One symbolic-link-loop test was skipped because this Windows session lacks symlink creation privileges. These include TREC format errors, preserved identifiers and file order, explicit format overrides, unknown-only qrels, inline-label resolution, rejected contradictory completeness assertions, cross-run coverage, source provenance, and input/output collisions.

An independent reviewer ran 67 relevant tests and 10 subtests, plus four end-to-end probes covering misleading file extensions, unknown-only and absent queries, completeness combined with an explicit zero assumption, and cross-run label disagreement. No reproducible functional error was found. The review corrected documentation that had implied CSV/JSONL unknown qrels were accepted and clarified the conservative MRR exclusion rule.

Seven documented retrieval flows were exercised. Hand calculations agreed within `1e-12`: default MRR@2 is 0.25 versus 0.5, but both matched-pool values are 0.5; default NDCG@2 is approximately 0.315464876786 versus 0.630929753571, with equal matched-pool values. Input-order ties and the explicit nonrelevant assumption matched their documented results. These are invented cases, not public benchmark findings. All 41 local links checked across 16 Markdown documents were valid at that check.

A fresh virtual environment installed the built `0.1.0a2` wheel with `--no-deps`. Isolated `python -I -m rankprobe compare` on the retrieval example produced both reports, and the installed console entry point reported the correct version. Distribution checks verified wheel CRCs, version, absence of core runtime dependencies, exact packaged Python source bytes, and source-package examples/documentation/tests. The first packaging check exposed missing `.run`/`.qrels` fixtures; the manifest was corrected and rebuilt. The check is now a CI step.

Further review reproduced an input-protection defect introduced by format overrides: a JSONL input named `report.json` could be replaced by `--out` pointing to the same directory with `--overwrite`. The CLI now rejects output paths coinciding with any prediction or judgment input, including existing file aliases. Four regression tests cover audit, compare, demo judgments, and a hard-link alias.

### Public upstream input check

Unmodified test inputs from [`usnistgov/trec_eval` at commit ba38899cbd4de0fb699b47f39b64ef1c107e4a5c](https://github.com/usnistgov/trec_eval/tree/ba38899cbd4de0fb699b47f39b64ef1c107e4a5c/test) were downloaded only for local validation. `results.test` (SHA256 `69019319f6cb9ce861b4ad08d90898170d3d2b27da580fb3cba59e557ff2fd20`) and `qrels.test` (SHA256 `6c44a070a10bfb14b123cadc597227fc63c1acec109bc6d1e5a6bc4763906698`) loaded successfully: 1,500 predictions, three submitted queries and 3,681 judgments. The audit found 762 retrieved candidates absent from the judgments and real score ties. It did not invent labels to make NDCG or Recall available under the default protocol. A separate single-query run and run comparison also completed; qrels-only queries remained visible.

The upstream `results.trunc` file contains extra trailing fields and was explicitly rejected by the documented exact-six-column contract. This is a known input-compatibility limit. The upstream expected output and Makefile were inspected, but the `trec_eval` executable was not run and numerical parity was not established. Upstream inputs and notices remain outside version control; no third-party fixture redistribution permission is inferred from the software license. This checks public test-file integration, not an external user's adoption or a benchmark study.

The previous `0.1.0a1` remote commit `07ce7e586f857da124e32b4f402514fbee3c41e0` passed the six Windows/Ubuntu and Python 3.10/3.12/3.13 jobs in [run 38605754159](https://github.com/C4LLM3LUC4S/rechorus-patt-reproduction/actions/runs/38605754159). That result does not cover these new changes; inspect the updated PR commit's runs for current remote validation.

## Initial implementation (`0.1.0a1`)

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

Cross-platform CI must be checked for each changed commit. External users, repeat adoption, paid demand, and research findings have not yet been established. See [validation-plan.md](validation-plan.md) for the remaining decision gates.
