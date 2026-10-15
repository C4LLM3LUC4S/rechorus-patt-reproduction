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

Use an interpreter with RankProbe installed. From the source checkout, save the following original code as a separate `fetch_trec_covid.py`, then run `python fetch_trec_covid.py`. It uses only Python's standard library and works without shell-specific activation or heredoc syntax. The destination must be fresh; choose a new directory name for another attempt and use that name in the audit command too.

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

If fetching fails or a fingerprint changes, inspect the source response and retain the failed attempt's context. Use a fresh destination for a retry. Do not update the expected fingerprint merely to make an unexplained response pass.

## Audit with explicit input formats

The prediction filename has no extension and the judgment file ends in `.txt`. Neither identifies its TREC format automatically. The observed automatic-format attempt exited with code 2 at the qrels file and produced no report. Both format declarations are needed:

```sh
python -m rankprobe audit artifacts/trec-covid-round1-local/ir_covid19_cle_lmd --input-format trec --qrels artifacts/trec-covid-round1-local/qrels-rnd1.txt --qrels-format trec --gain linear --tie-policy item_id --cutoffs 1,5,10 --unjudged unknown --out artifacts/trec-covid-round1-local/report
```

This retains the default unknown-label policy and leaves qrels completeness undeclared. It uses descending scores and ascending item IDs for ties; submitted rank fields do not determine ordering. The run has six fields per record, while qrels has four. Fractional iteration values such as `0.5` in qrels are bookkeeping and are ignored, not interpreted as relevance grades. The report destination is new and no overwrite flag is used.

## Observed coverage and interpretation

The explicit-format local audit exited with code 0, reporting two warnings and one informational finding. Its inputs remained byte-identical. These are the recorded results under the command's declared protocol:

| Observation | Result |
| --- | --- |
| Prediction records / queries | 2,601 / 30 |
| Qrels records / queries | 8,691 / 30 |
| Supplied known labels among retrieved candidates | 781 |
| Candidates still unknown | 1,820 |
| Assumed nonrelevant candidates | 0 |
| MRR@10 coverage | 6 of 30 queries eligible; 24 excluded; `partial` |
| NDCG@1, @5 and @10 | Unavailable; no eligible queries |
| Recall@1, @5 and @10 | Unavailable; complete qrels not declared |
| Reported score ties | 249 groups, 631 candidates, all 30 queries |
| Exact tie bounds | Unavailable; no query has all candidate judgments known |

MRR@10 excludes a query when any of its top-ten candidates is unjudged, even when an earlier candidate is known relevant. Its value is an average over the six eligible queries. Inspect the coverage details before interpreting it; excluded queries are not zero-valued observations.

NDCG requires known labels for every submitted candidate under this policy, so an unknown candidate below the cutoff can still exclude its query. All 30 queries have an unknown submitted candidate here. Recall additionally needs a justified completeness declaration; a pooled set of judgments does not supply that declaration automatically. Exact tie bounds are also unavailable because their scope requires every candidate judgment in a query to be known. Tie counts identify equal scores to inspect, not a defect or evidence that a metric changed.

The historical NIST report lists NDCG@10 = 0.2286. This guide does not treat that score as a parity target for the default audit: unknown-label treatment, tie ordering and eligible query sets must match before comparing numbers. No native trec_eval comparison was performed for this case. The separate [pinned-reference checks](trec-reference.md) have their own stated synthetic protocols.

For a follow-up investigation, first verify the Round 1 input fingerprints and inspect the locally reported unknown candidates and tie groups. Check judgment version, gain, relevance threshold, tie policy and query coverage against the intended evaluation. A separate audit with `--unjudged nonrelevant` needs an explicit justification for that assumption and must retain its reported assumption counts; it does not establish complete qrels. Keep any such result separately named and preserve the original files.
