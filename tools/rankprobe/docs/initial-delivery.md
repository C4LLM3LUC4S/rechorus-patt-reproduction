# Initial delivery / 首版交付

**Status as of 2026-10-22: initial engineering scope complete; maintenance phase.**

**截至 2026-10-22：工程首版完成，进入维护。** Version `0.1.0a4` remains an alpha. This milestone records a bounded implementation and reproducible delivery, while independent adoption, human time saved, income and research outcomes remain unestablished.

## Delivered scope

| Area | Included in this first version |
| --- | --- |
| Local core | CSV/JSONL and ordinary TREC prediction/qrels input, explicit protocol, audit/compare/demo CLI and Python API; no core runtime dependency or audit network calls |
| Evaluation semantics | Known-prefix MRR, declared NDCG gains and references, conditional metric coverage, unknown judgments, and explicit completeness/nonrelevance assumptions |
| Diagnostics | Ties and sensitivity, duplicate candidates, conflicts, missing queries, differing candidate pools, source fingerprints and input/output preservation |
| Reports | Offline HTML and JSON; English/Chinese comparison guidance, within-metric run comparisons, submitted/matched scope and retained full evidence |
| Integration | Bounded source-checkout paths for BEIR, MTEB, ReChorus and RecBole; optional dependencies and supported task/score shapes remain explicit |
| Reproducible cases | Original synthetic controls, fixed public TREC/reference checks and an optional public-data fitted-score recovery control |
| Delivery | Source and wheel builds, isolated installation/error recovery checks, preserved original inputs and cross-platform CI for the exact snapshot |

The [metric contract](metrics.md), [input contract](input-format.md), [adapter limits](adapters.md), [case actions](case-actions.md) and [verification record](verification.md) define the scope in detail. This milestone does not imply every possible framework, Python version or data source has been verified.

## Use it without an active experiment

Follow the [first-report walkthrough](try-it.md). The included demo and TREC examples work locally without a trained model or your own predictions. When a permitted score export becomes available, use the supported adapter or input contract; judgments are optional and missing ones remain unknown. The [MovieLens path](../examples/movielens-scores/README.md) is an optional source-checkout experiment with separate NumPy/data requirements, not an installation prerequisite.

The public examples establish bounded software behavior. Keep guided practice, independent understanding and a useful discovery in someone's real work as separate evidence. No one needs to create a new experiment to keep this release scope complete.

## Acceptance and source identity

Use the exact source commit and inspect its [GitHub Actions run](https://github.com/C4LLM3LUC4S/rechorus-patt-reproduction/actions). The matrix covers the full development checks on Windows/Ubuntu Python 3.10, 3.12 and 3.13; Python 3.15 has separate core build/install checks. Python 3.14 and full optional-framework coverage on 3.15 are not established. Framework/reference jobs remain limited to their fixed sources and protocols.

Freshly built distributions must pass [distribution and installation checks](installation-checks.md). For a local snapshot bundle, retain a manifest, hashes, source identity and the exact-commit CI receipt; verify the final extracted copy before use. Earlier candidate archives remain separate immutable snapshots. The alpha is distributed from the default branch and the [versioned GitHub release](https://github.com/C4LLM3LUC4S/rechorus-patt-reproduction/releases/tag/v0.1.0a4). The curated bundle contains source, distributions, examples and a manifest. No PyPI or stable-version release is claimed.

## Maintenance / 后续维护

Prioritise reproducible wrong results, input/output damage, failed installation/export, unclear report interpretation and compatibility regressions. Start from the actual failure and an observable acceptance condition. Follow the smallest changed commit through CI; use already accepted evidence for unchanged paths.

For a bug report, use the repository's [issue form](https://github.com/C4LLM3LUC4S/rechorus-patt-reproduction/issues/new?template=rankprobe_bug.yml) and prefix the title with `[RankProbe]`. Include the version/commit, OS/Python, command shape, expected/observed behavior and a minimal original synthetic input where possible. Keep private predictions, identifiers, credentials and licensed raw data out of the issue. Report warnings alone do not establish a model bug.

The [practical-value plan](validation-plan.md) and [roadmap](roadmap.md) retain future adoption and research questions. Add capabilities when those observations show a need. Missing labels stay unknown; matching structure does not certify provenance, leakage avoidance or model quality.
