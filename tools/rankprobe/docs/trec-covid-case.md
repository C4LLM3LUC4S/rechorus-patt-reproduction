# Auditing a real TREC-COVID Round 1 submission

This case reads an existing public retrieval submission and its matching judgments. It needs no document corpus, model download, inference or training. It demonstrates file import, judgment coverage and tie diagnostics on real archived inputs. It does not establish external adoption of RankProbe or human time saved.

## Sources and local storage

The [official Round 1 archive](https://ir.nist.gov/trec-covid/archive/archive-round1.html) links the `ir_covid19_cle_lmd` submission and its [description and historical score report](https://ir.nist.gov/trec-covid/archive/round1/ir_covid19_cle_lmd.pdf). The submitted system used Lucene with LM-Dirichlet scoring. Use the Round 1 judgments linked below: NIST's [data page](https://ir.nist.gov/trec-covid/data.html) explains why later cumulative or chronological judgments do not correspond to the original submitted runs.

These files are publicly accessible. This guide does not establish a downstream redistribution license for the participant-submitted run. The recipe places inputs and reports under an ignored directory. This published case contains source links, original reproduction code and aggregate observations; the raw run, qrels and record-level reports are not included in public examples or distribution packages. The corpus has separate licensing terms and is not needed here.

The local check on 2026-10-16 recorded these exact bytes:

| Input | Official URL | Bytes | SHA256 |
| --- | --- | ---: | --- |
| Prediction run | [ir_covid19_cle_lmd](https://ir.nist.gov/trec-covid/archive/round1/ir_covid19_cle_lmd) | 120592 | `e8980fb2b6d9ca081454f68d6b1c7896fa251f844e92d83f3a651630c24b9465` |
| Round 1 qrels | [qrels-rnd1.txt](https://ir.nist.gov/trec-covid/data/qrels-rnd1.txt) | 150110 | `1f2ee6258744581b466c744a1e5956b9a10b0e10f84f44cb6336bef053644b51` |

## Fetch the two bounded files

Start in this checkout's package folder with the core `.venv` from the [first-report installation](try-it.md#1-install-locally). Keep using its explicit interpreter path; activating the environment is unnecessary. A bare `python` may select a different environment where RankProbe is not installed.

Save the following original code as a separate `fetch_trec_covid.py`. It uses only Python's standard library and works without shell-specific activation or heredoc syntax. The destination must be fresh; choose a new directory name for another attempt and use that name in the audit command too.

The initial default `urllib` GET for the run returned HTTP 403 before saving bytes. Explicit `Request` objects with `User-Agent: RankProbe-local-validation/0.1` and `Accept: text/plain` returned HTTP 200 for both files. The recipe uses those headers, a 2 MiB limit per response, exact length and SHA256 checks, and exclusive `xb` file creation after verification. A changed file is rejected rather than accepted under the recorded fingerprint.

```python
import hashlib
import json
from pathlib import Path
from urllib.request import Request, urlopen

LIMIT = 2 * 1024 * 1024
DESTINATION = Path("artifacts/trec-covid-round1-local")
FILES = (
    (
        "ir_covid19_cle_lmd",
        "https://ir.nist.gov/trec-covid/archive/round1/ir_covid19_cle_lmd",
        120592,
        "e8980fb2b6d9ca081454f68d6b1c7896fa251f844e92d83f3a651630c24b9465",
    ),
    (
        "qrels-rnd1.txt",
        "https://ir.nist.gov/trec-covid/data/qrels-rnd1.txt",
        150110,
        "1f2ee6258744581b466c744a1e5956b9a10b0e10f84f44cb6336bef053644b51",
    ),
)

DESTINATION.mkdir(parents=True, exist_ok=False)
manifest = []
for name, url, expected_bytes, expected_hash in FILES:
    request = Request(
        url, headers={"User-Agent": "RankProbe-local-validation/0.1", "Accept": "text/plain"}
    )
    with urlopen(request, timeout=30) as response:
        if response.status != 200:
            raise ValueError(f"{name}: unexpected HTTP status {response.status}")
        content = response.read(LIMIT + 1)
    if len(content) > LIMIT:
        raise ValueError(f"{name}: response exceeds the 2 MiB limit")
    digest = hashlib.sha256(content).hexdigest()
    if len(content) != expected_bytes or digest != expected_hash:
        raise ValueError(f"{name}: byte length or SHA256 differs from the recorded input")
    with (DESTINATION / name).open("xb") as handle:
        handle.write(content)
    manifest.append({"filename": name, "url": url, "bytes": len(content), "sha256": digest})
print(json.dumps(manifest, indent=2))
```

Run it with the same interpreter you will use for the audit.

Windows PowerShell:

```powershell
.\.venv\Scripts\python.exe fetch_trec_covid.py
```

macOS / Linux:

```sh
.venv/bin/python fetch_trec_covid.py
```

If fetching fails or a fingerprint changes, inspect the source response and retain the failed attempt's context. Use a fresh destination for a retry. Do not update the expected fingerprint merely to make an unexplained response pass.

## Audit with explicit input formats

The prediction filename has no extension and the judgment file ends in `.txt`. Neither identifies its TREC format automatically. The observed automatic-format attempt exited with code 2 at the qrels file and produced no report. The error names `--qrels-format trec`; after declaring that format, the extensionless prediction needs `--input-format trec` too. Both format declarations are needed:

Windows PowerShell:

```powershell
.\.venv\Scripts\python.exe -m rankprobe audit artifacts/trec-covid-round1-local/ir_covid19_cle_lmd --input-format trec --qrels artifacts/trec-covid-round1-local/qrels-rnd1.txt --qrels-format trec --gain linear --tie-policy item_id --cutoffs 1,5,10 --unjudged unknown --out artifacts/trec-covid-round1-local/report
```

macOS / Linux:

```sh
.venv/bin/python -m rankprobe audit artifacts/trec-covid-round1-local/ir_covid19_cle_lmd --input-format trec --qrels artifacts/trec-covid-round1-local/qrels-rnd1.txt --qrels-format trec --gain linear --tie-policy item_id --cutoffs 1,5,10 --unjudged unknown --out artifacts/trec-covid-round1-local/report
```

This retains the default unknown-label policy and leaves qrels completeness undeclared. It uses descending scores and ascending item IDs for ties; submitted rank fields do not determine ordering. The run has six fields per record, while qrels has four. Fractional iteration values such as `0.5` in qrels are bookkeeping and are ignored, not interpreted as relevance grades. The report destination is new and no overwrite flag is used.

## Observed coverage and version migration

The explicit-format local audits in `0.1.0a3` and `0.1.0a4` each exited with code 0, reporting two warnings and one informational finding. Their inputs remained byte-identical. The following table records the current `0.1.0a4` default-unknown audit under the command's declared protocol:

| Observation | Result |
| --- | --- |
| Prediction records / queries | 2,601 / 30 |
| Qrels records / queries | 8,691 / 30 |
| Supplied known labels among retrieved candidates | 781 |
| Candidates still unknown | 1,820 |
| Assumed nonrelevant candidates | 0 |
| MRR@1 / @5 / @10 eligible queries | 27 / 19 / 17 out of 30 |
| MRR@10 | 0.6029411764705882; 17 eligible, 13 excluded; `partial` |
| NDCG@1, @5 and @10 | Unavailable; no eligible queries |
| Recall@1, @5 and @10 | Unavailable; complete qrels not declared |
| Reported score ties | 249 groups, 631 candidates, all 30 queries |
| Exact tie bounds | Unavailable; no query has all candidate judgments known |

MRR can include a query when all labels through its first relevant item are known; later unknowns cannot change that first rank and remain unknown. An unknown before it still excludes the query. The reported value is a conditional mean over 17 eligible queries, with `eligibility_rule=known_first_relevant_prefix` visible in JSON and HTML coverage details. Excluded queries are not zero-valued observations.

The retained `0.1.0a3` report used the deliberately conservative all-top-k-known rule: its MRR eligible counts were 27/15/6 at cutoffs 1/5/10, and MRR@10 was 0.4583333333333333 over six queries. The separate `0.1.0a4` audit includes 11 additional queries at cutoff 10 without assigning any missing label or changing the 1,820 unknown / zero assumed counts. NDCG, Recall, protocol settings and source hashes match the retained report. The larger conditional mean reflects a changed eligible population, not better rankings. Do not subtract the old and new values; recompute both runs under the same declared rule when comparing them.

NDCG requires known labels for every submitted candidate under this policy, so an unknown candidate below the cutoff can still exclude its query. All 30 queries have an unknown submitted candidate here. Recall additionally needs a justified completeness declaration; a pooled set of judgments does not supply that declaration automatically. Exact tie bounds are also unavailable because their scope requires every candidate judgment in a query to be known. Tie counts identify equal scores to inspect, not a defect or evidence that a metric changed.

The historical NIST report lists NDCG@10 = 0.2286. This guide does not treat that score as a parity target for the default audit: unknown-label treatment, tie ordering and eligible query sets must match before comparing numbers. The observations above were recorded without a native trec_eval comparison. The separate [pinned-reference checks](trec-reference.md) have their own stated synthetic protocols.

For a follow-up investigation, first verify the Round 1 input fingerprints and inspect the locally reported unknown candidates and tie groups. Check judgment version, gain, relevance threshold, tie policy and query coverage against the intended evaluation. A separate audit with `--unjudged nonrelevant` needs an explicit justification for that assumption and must retain its reported assumption counts; it does not establish complete qrels. Keep any such result separately named and preserve the original files.

## Compare two real retrieval runs

The same [official Round 1 archive](https://ir.nist.gov/trec-covid/archive/archive-round1.html) also provides `ir_covid19_cle_dfr`. Its [submission description](https://ir.nist.gov/trec-covid/archive/round1/ir_covid19_cle_dfr.pdf) describes Lucene abstract-field retrieval with Divergence from Randomness scoring. It provides a real second run for the existing comparison command, without training a model or downloading the corpus.

For a fresh reproduction, use the verified downloader above with `DESTINATION = Path("artifacts/trec-covid-round1-pair-local")` and add this third tuple to `FILES` before executing it:

```python
    (
        "ir_covid19_cle_dfr",
        "https://ir.nist.gov/trec-covid/archive/round1/ir_covid19_cle_dfr",
        118231,
        "c919e38726909203d69cff6092f34421d03b6c52ebcfc800f0119a287b827692",
    ),
```

The LMD and Round 1 qrels fingerprints remain those listed above. The three files and generated reports stay local under the ignored destination; the run files and record-level reports are not redistributed here. Previously retained exact inputs can be reused after verifying their fingerprints, with the command paths adjusted accordingly.

Windows PowerShell:

```powershell
.\.venv\Scripts\python.exe -m rankprobe compare --run cle_lmd=artifacts/trec-covid-round1-pair-local/ir_covid19_cle_lmd --run cle_dfr=artifacts/trec-covid-round1-pair-local/ir_covid19_cle_dfr --input-format trec --qrels artifacts/trec-covid-round1-pair-local/qrels-rnd1.txt --qrels-format trec --gain linear --tie-policy item_id --cutoffs 1,5,10 --unjudged unknown --out artifacts/trec-covid-round1-pair-local/compare
```

macOS / Linux:

```sh
.venv/bin/python -m rankprobe compare --run cle_lmd=artifacts/trec-covid-round1-pair-local/ir_covid19_cle_lmd --run cle_dfr=artifacts/trec-covid-round1-pair-local/ir_covid19_cle_dfr --input-format trec --qrels artifacts/trec-covid-round1-pair-local/qrels-rnd1.txt --qrels-format trec --gain linear --tie-policy item_id --cutoffs 1,5,10 --unjudged unknown --out artifacts/trec-covid-round1-pair-local/compare
```

The local 0.1.0a4 comparison on 2026-10-18 exited successfully. Input hashes were unchanged, no nonrelevance assumptions were introduced, and qrels completeness remained undeclared. Independent parsing of the original records, Decimal score sorting and reciprocal-rank calculations checked these aggregate observations:

| Observation | CLE-LMD | CLE-DFR |
| --- | ---: | ---: |
| Submitted records / queries | 2,601 / 30 | 2,564 / 30 |
| Supplied known candidate labels | 781 | 825 |
| Candidate labels still unknown | 1,820 | 1,739 |
| MRR@10 | 0.6029411764705882 | 0.6795977011494252 |
| MRR@10 eligible queries | 17 / 30 | 29 / 30 |
| NDCG@1, @5 and @10 | Unavailable | Unavailable |
| Recall@1, @5 and @10 | Unavailable | Unavailable |

All 30 queries occur in both runs, but all 30 have different submitted candidate sets. Shared query-item labels have no conflicts. The pair therefore reports `status=not_comparable`, zero structurally matched queries and unavailable matched deltas. This is the tool's same-pool comparison scope, not a finding that the original retrieval systems cannot be evaluated against each other.

Two end-to-end retrievers can legitimately return different documents. Follow the `candidate_set_mismatch` action by inspecting whether candidate selection changed as intended. For a question about reranking alone, obtain a shared candidate export. For a question about the complete retrieval systems, preserve both original runs and establish the intended evaluation protocol separately. Do not intersect their results or invent absent scores or zero labels to force structural matching.

The diagnostic has been independently checked. The [complete-retrieval follow-up](#complete-retrieval-follow-up-on-both-original-runs) now checks both original runs under a separately declared native protocol. No shared-candidate reranking export has been executed. See the [action and recheck table](case-actions.md#different-retrieval-candidate-sets) for the distinction.

The two displayed MRR@10 values also average different eligible query populations. Their subtraction would not be a matched improvement estimate. NDCG remains unavailable because each query has an unknown submitted candidate; Recall additionally lacks a justified completeness declaration. These results demonstrate report interpretation on public real inputs, not independent human use, time saved or a quality judgment about either submission. See [what a comparison establishes](metrics.md#what-a-comparison-establishes) for the distinction between structural matching and metric eligibility.

## Separate native-reference check

`scripts/check_trec_covid.py` compares this fixed public input with an explicitly supplied native `trec_eval`. The [NIST data page](https://ir.nist.gov/trec-covid/data.html) states that most measures assume documents absent from qrels are not relevant. That supports a separately declared missing-as-nonrelevant experiment for MRR and linear NDCG; it does not turn absent judgments into supplied labels or establish complete qrels. This checker always keeps `qrels_complete=False`, leaves Recall unavailable, and preserves the default unknown-policy controls above.

These optional reference commands use the macOS / Linux core interpreter path and require a native executable you supply; `/path/to/trec_eval` is a placeholder. They do not build or install that executable. With the source checkout, use the already fetched files:

```sh
.venv/bin/python scripts/check_trec_covid.py --trec-eval /path/to/trec_eval --inputs-dir artifacts/trec-covid-round1-local --summary artifacts/trec-covid-reference-result.json
```

Both `--trec-eval` and `--inputs-dir` are required. The input directory must contain the exact `ir_covid19_cle_lmd` and `qrels-rnd1.txt` files with the lengths and SHA256 values recorded above. Alternatively, add `--fetch` with a fresh input directory to download only those two bounded files:

```sh
.venv/bin/python scripts/check_trec_covid.py --trec-eval /path/to/trec_eval --inputs-dir artifacts/trec-covid-round1-reference --fetch --summary artifacts/trec-covid-reference-result.json
```

These are alternative recipes. `--fetch` refuses an existing input directory; it verifies the fixed fingerprints and creates files exclusively. `--summary` is optional and refuses an existing output file. Choose a fresh summary path for another attempt. The summary contains aggregate results and provenance, without local paths, participant records or per-query native output. The checker does not rewrite the original run, qrels or default report. It checks input hashes before and after native execution and verifies that the original in-memory rows and qrels remain unchanged.

The comparison uses linear gain, relevance greater than zero, cutoffs 1, 5 and 10, and the same 30 queries. Its explicit nonrelevant view retains 781 supplied candidate labels and records 1,820 assumed nonrelevant candidates. MRR and NDCG remain `partial`; NDCG uses the known qrels pool as its ideal-ranking reference. Added zero gains do not require a completeness declaration, while Recall still does.

Exact score ties need a separate adapter. RankProbe's ordinary `item_id` policy orders tied IDs ascending; the pinned native source orders them descending. The checker creates only an in-memory copy ordered by descending ASCII document ID, then selects `tie_policy="input"`, whose stable descending-score sort retains that order for ties. Original document IDs, scores, run bytes and qrels stay unchanged. This adapter is explicit reference ordering, not a change to the default tie policy.

The following values are recorded RankProbe API observations, **not evidence of a passed native check**:

| Explicit nonrelevant view, all 30 queries | Ascending document-ID ties | Native-aligned descending document-ID ties |
| --- | ---: | ---: |
| MRR@10 | 0.3942989417989418 | 0.3942989417989418 |
| NDCG@10 | 0.22869399948832908 | 0.2286144995215745 |
| Recall@1, @5 and @10 | Unavailable | Unavailable |

Only one query's NDCG@10 changes with this tie ordering. The two macro values round to 0.2287 and 0.2286, respectively. The latter matches the historical report's displayed precision; that is a rounding observation, not identification or reproduction of the 2020 executable or scoring command.

The checker invokes NDCG on the original paths once, without truncating the run:

```sh
trec_eval -q -l 1 -m ndcg_cut.1,5,10 ORIGINAL_QRELS ORIGINAL_RUN
```

It invokes `recip_rank` separately with `-M 1`, `-M 5` and `-M 10`, because that measure has no cutoff parameter. It does not use `-J`, which would remove unjudged candidates and change their positions. The expected result is exactly 186 comparisons: 30 per-query values plus one macro value, for each of three cutoffs and two metrics. Each comparison uses absolute tolerance `0.00005000001` and relative tolerance zero, reflecting native four-decimal output. A pass establishes numerical agreement only under this declared protocol and output precision. The checker also requires the `0.1.0a4` default controls: no assumed nonrelevant candidates, 27/19/17 eligible MRR queries under the declared prefix rule, and unavailable NDCG and Recall. The fully resolved nonrelevant reference view is unaffected by the MRR eligibility migration.

CI uses the modern NIST source pin [`ba38899cbd4de0fb699b47f39b64ef1c107e4a5c`](https://github.com/usnistgov/trec_eval/tree/ba38899cbd4de0fb699b47f39b64ef1c107e4a5c), whose version is `10.0-rc3`. The verified source archive SHA256 is `d603cd657950aebea3a5ed08cee5ea0e5e836012ed5eb63303d3a7d66e49ba6a`; the reference job builds the unmodified source and runs its upstream `quicktest` before the checker. Check the CI run for the exact RankProbe commit before claiming this gate passed. The summary records the supplied executable's hash and version, but a version string alone does not prove build provenance. This modern reference cannot be described as the original 2020 binary, whose build and complete command remain unverified.


## Complete-retrieval follow-up on both original runs

The [native job for commit `f005dd5`](https://github.com/C4LLM3LUC4S/rechorus-patt-reproduction/actions/runs/39462577354/job/118765566512) built and self-tested the same fixed modern NIST source above and passed **372 comparisons**, 186 per run, at the declared native text tolerance. This is actual native execution on the original CLE-LMD, CLE-DFR and Round 1 cumulative qrels paths. It does not reproduce a historical executable or train either retriever.

The separately declared experiment uses linear gain, relevance greater than zero, cutoffs 1/5/10, absent judgments assumed nonrelevant and descending ASCII document-ID ties, with the same 30 queries. It never declares complete qrels. The default controls retain 1,820 unknown candidates for CLE-LMD and 1,739 for CLE-DFR, with zero assumed nonrelevant candidates. In the separate native views, those same counts are explicitly recorded as assumptions; supplied labels remain 781 and 825.

| Common-protocol result, all 30 queries | CLE-LMD | CLE-DFR | DFR minus LMD |
| --- | ---: | ---: | ---: |
| RankProbe MRR@10, native-aligned view | 0.3942989417989418 | 0.6606481481481481 | 0.2663492063492063 |
| Native MRR@10 as printed | 0.3943 | 0.6606 | 0.2663 |
| RankProbe linear NDCG@10, native-aligned view | 0.2286144995215745 | 0.35999083087476774 | 0.13137633135319324 |
| Native NDCG@10 as printed | 0.2286 | 0.3600 | 0.1314 |

Native differences subtract rounded values; their absolute error bound is twice the per-run tolerance, `0.00010000002`. MRR and NDCG remain `partial`, with NDCG referencing the known qrels pool. Recall remains unavailable. These are numerical differences between fixed archived runs under explicit assumptions, not a matched-pool delta, significance test, model-quality certificate or measured human benefit. The default unknown-policy diagnostic still reports 30 different candidate sets, zero matched queries and unavailable matched deltas.

From the package source checkout, supply a native executable as above and a fresh directory:

```sh
.venv/bin/python scripts/check_trec_covid.py --pair --trec-eval /path/to/trec_eval --inputs-dir artifacts/trec-covid-pair-reference --fetch --summary artifacts/trec-covid-pair-reference-result.json
```

Alternatively omit `--fetch` and point `--inputs-dir` at the existing verified three-file pair directory. Existing summary files are refused. Without `--pair`, the two-file CLE-LMD recipe remains available. The pair checker verifies all three fingerprints before execution and again afterward; it does not rewrite original files or default reports. It requires complete native metric/topic coverage and an identical reference binary before forming the separate comparison. CI retains its aggregate summary as `rankprobe-trec-covid-pair-result.json` in `trec-eval-reference`; `runs` holds the two checks, `end_to_end_comparison` the separate arithmetic differences, and `same_pool_control` the still-unavailable matched comparison.
