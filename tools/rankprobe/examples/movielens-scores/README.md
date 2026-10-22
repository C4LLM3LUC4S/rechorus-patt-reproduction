# Fitted scores, shared candidates and retained-score recovery

This case fits two small models on **actual public MovieLens ratings**, scores the same held-out observed-item pools, deliberately rounds one model's presentation scores, and restores the exact export from retained score evidence. It supplements the archived TREC and original synthetic cases. The rounding is an intentional software control on newly fitted scores, not a previously discovered framework or user incident.

## Source and scope

Use the official [MovieLens 100K dataset](https://grouplens.org/datasets/movielens/100k/) and its [usage README](https://files.grouplens.org/datasets/movielens/ml-100k-README.txt). The README permits research use, requires acknowledgment, and requires separate permission for redistribution or commercial/revenue-bearing use. This repository distributes original code and aggregate observations; it does not bundle ratings, model captures, prediction rows, qrels or generated reports. Do not redistribute those local outputs or use the data commercially without the required permission. GroupLens does not endorse RankProbe.

The fixed ZIP has 4,924,029 bytes and SHA256 `50d2a982c66986937beb9ffb3aa76efe955bf3d5c6b761f4e3a7cd717c6a3229`. Its official MD5 record was also checked: `0e33842e24a9c977be4e0107933c0723`. The checker verifies the ZIP and the selected `README`, `u1.base` and `u1.test` member SHA256 values before fitting. It reads no demographic files and extracts no archive paths.

The predefined `u1.base` has 80,000 observed training ratings; `u1.test` has 20,000 observed held-out pairs across 459 source users. Both models score every original test pair. No candidate is selected by its rating or by a favorable result. The candidate pool is the held-out **observed-item** list for each user. It is not full-catalog retrieval or a demonstrated production retrieval stage. The original split is not a temporal or leakage-free certificate.

## Fixed experiment

The model and evaluation choices were fixed before fitting or inspecting metrics:

- Fit a regularized user/item bias model for 10 alternating iterations, regularization 10.
- Add 8-dimensional matrix factors trained on observed training-rating residuals for 8 epochs, batch size 512, learning rate 0.01, regularization 0.02 and seed 20261021. Bias terms remain fixed. Missing training ratings are not supplied as zero observations. Cold evaluation IDs use zero biases/factors; adding unrelated evaluation IDs cannot change the fit.
- Preserve every source test pair and its order. Export finite binary64 scores as round-trip decimal strings, without inline labels. Stable query tokens identify this split/user context, not a causal history.
- For this experiment only, a supplied held-out rating of 4 or 5 gives binary relevance 1; an actually observed rating of 1–3 gives 0. This choice is explicit and transfers no judgment to unobserved items. The core's binary threshold is `0`, since relevance means `label > threshold`.
- Compare at cutoffs 1/5/10, linear NDCG, lexical item-ID ties, `unjudged=unknown` and `qrels_complete=False`. Recall remains unavailable. A fully known zero-positive pool contributes zero NDCG under the documented convention.
- Inspect one-decimal presentation rounding, then re-export into a fresh CSV from the retained exact score capture. Do not refit, intersect candidates or alter judgments to recover a result.

The retained NPZ is this checker's record-indexed capture, containing the two model score vectors and original pair order. Its shape is different from the [one-positive matrix NPZ bridge](../../docs/adapters.md); do not feed it to that helper or treat the conventions as interchangeable.

## Reproduce locally

From the source checkout, install RankProbe and optional NumPy in the same environment:

```sh
python -m pip install -e ".[adapters]"
```

Create a new local parent directory outside the repository or under ignored `artifacts/`. The following command explicitly downloads the fixed official ZIP to a **new file** and creates a **new output directory**; it is an optional source-checkout helper, not an installed core command:

```sh
python scripts/check_movielens_scores.py --fetch artifacts/ml100k.zip --out artifacts/ml100k-case
```

For an existing fixed original ZIP, use `--archive artifacts/ml100k.zip` instead of `--fetch`, with a fresh output directory. Existing output is refused before downloading or reading inputs. A failed attempt may retain local files for inspection; keep them and choose a new destination. No original archive or output is overwritten. A fixed-source checksum mismatch stops the check; do not substitute an unverified archive to clear it.

Four actual core CLI paths create local HTML/JSON reports: the two fitted models, one scores-only audit, exact-versus-rounded scores, and exact-versus-recovered scores. `summary.json` contains aggregate evidence suitable for review. Other generated files retain dataset identifiers and source-derived rows; keep them local. Core audits themselves remain offline; only explicit `--fetch` downloads this dataset.

## Inspect, recover and recheck without refitting

The full checker performs recovery automatically. To exercise the action separately, keep its completed `ml100k-case` directory and use this source-checkout path. It needs NumPy in the same environment and does not download, refit or read judgments.

1. Open `artifacts/ml100k-case/rounding/report.html`. Compare **exact** and **rounded within each metric**, then inspect each run's score-tie findings. The same factor model now has many more ties; an NDCG increase alone does not establish a better model. The rounded input here is deliberate.
2. Check the capture's SHA256 against `local_file_sha256["retained-scores.npz"]` in the original `summary.json`. Use `Get-FileHash` in PowerShell or `sha256sum` in a POSIX shell. If they differ, preserve both files and locate the correct retained capture. A readable NPZ does not prove it belongs to the run.
3. Re-export the **factor** vector from that capture into a fresh directory:

```sh
python scripts/check_movielens_scores.py --recover artifacts/ml100k-case/retained-scores.npz --out artifacts/ml100k-manual-recovery
```

Stop if the command fails. Preserve the failure output and choose a new destination for a corrected attempt. The helper rejects existing destinations before reading inputs and validates pair IDs, unique pairs, array shapes and finite binary64 scores before writing. It preserves original row order and decimal score precision. It does not accept the one-positive matrix bridge's NPZ format or repair a damaged capture with rounded scores. `recovery.json` records capture/output hashes and row/query counts, but does not authenticate the capture's model identity.

4. Only after successful recovery, compare with the retained **exact** export using the original judgments and protocol:

```sh
python -m rankprobe compare --run exact=artifacts/ml100k-case/factors.csv --run recovered=artifacts/ml100k-manual-recovery/recovered.csv --qrels artifacts/ml100k-case/observed-judgments.csv --cutoffs 1,5,10 --tie-policy item_id --gain linear --relevance-threshold 0 --unjudged unknown --out artifacts/ml100k-manual-recheck
```

5. Open `artifacts/ml100k-manual-recheck/report.html`. Require all **459** query pools to match, zero matched deltas for all six MRR/NDCG measures, and **6** tie groups in each run. Compare the CSV's SHA256 with the original `summary.json` factor-CSV hash as well: equal aggregate metrics alone cannot prove faithful restoration. Recall stays unavailable. Original rounded/exact reports, capture and judgments remain unchanged.

This checks one export action on actual public-data scores. It neither repairs an unretained historical score nor shows that someone understood the report, changed a decision or saved time. Record those outcomes prospectively if you try this flow yourself; distinguish guided practice from independent use.

## Executed observation

The Windows/Python 3.12.5, NumPy 2.5.4 run passed **11,058** independent per-query, macro and paired-delta comparisons at absolute tolerance `1e-12`. A separate Python formula sorts scores/lexical IDs and computes binary reciprocal rank and DCG/IDCG; it checks every query through the public metric API and each actual CLI macro. The installed-core unknown-label control retains **20,000 unknown candidates**, zero assumed labels and no label-dependent values when qrels are absent.

| Score export | Tie groups | MRR@5 | NDCG@5 |
| --- | --- | --- | --- |
| Exact fitted factor scores | 6 | 0.8988743645606391 | 0.8087799383000502 |
| Same scores rounded to one decimal | 3,505 | 0.8980029048656499 | 0.8104025301467699 |
| Fresh recovery from exact capture | 6 | 0.8988743645606391 | 0.8087799383000502 |

The rounding alone creates an apparent NDCG@5 increase of approximately `0.00162259` while MRR@5 decreases. A user can inspect the added ties, retain the capture and choose faithful score export before attributing a change to a model. Recovery produces a byte-identical original CSV and zero matched deltas across all six measures. Archive, capture, qrels and prediction hashes remain unchanged.

The bias-versus-factor comparison is structurally valid over all 459 shared query pools, with mixed metric changes. At cutoff 10 the factor-minus-bias differences are MRR `-0.002540892900369962` and NDCG `-0.00017881461568425294`; no favorable tuning was performed. These are conditional observed-item results, not evidence of superior model quality, statistical significance, full-catalog recall, external adoption or human time saved. Machine fitting time is labeled separately.

The six existing Windows/Ubuntu Python 3.10/3.12/3.13 CI jobs now execute this case and retain **only** aggregate `summary.json` artifacts named `movielens-shared-scores-<OS>-<Python>`, for 14 days. Check the exact commit's run before claiming those executions passed. NumPy/model execution is not added to the separate Python 3.15 core-only jobs.

Already discarded historical scores cannot be recovered without retained evidence. This new case completes a score-bearing public-data software path; a real user's earlier export problem and measured benefit remain separate evidence.

Dataset acknowledgment: F. Maxwell Harper and Joseph A. Konstan, *The MovieLens Datasets: History and Context*, ACM TiiS 5(4), 2015, [DOI 10.1145/2827872](https://doi.org/10.1145/2827872).
