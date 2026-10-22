# Optional NPZ exporter

`scripts/export_rechorus.py` independently exports a documented ReChorus-style convention. It imports NumPy, not a training framework. Install optional support with:

```sh
python -m pip install -e ".[adapters]"
```

## Required source assumptions

The NPZ must have equally shaped, nonempty 2-D `scores` and `item_id` arrays. Rows are ranking events; columns are candidates. Scores must be finite integers or real floating-point arrays with dtypes of at most 64 bits. Wider floating-point dtypes are rejected before CSV or metadata output instead of silently narrowed. Object arrays are not loaded (`allow_pickle=False`). An optional `user_id` array is checked for row count but never exported.

`numpy.save` writes a single NPY array; renaming it to `.npz` does not create the required named arrays. The helper identifies that content before output and explains how to make a new capture with `numpy.savez` or `numpy.savez_compressed`, using complete scores and aligned item IDs. Keep the original; a score matrix alone cannot supply missing item or event identities. The container is checked by its contents, so a genuine named NPZ archive is not refused solely because its filename has another suffix.

Integer score arrays are written as exact decimal integers, including signed and unsigned 64-bit values. Adjacent large integers must not become a tie through a float conversion. Float16/32/64 scores keep their values through the existing binary64 decimal representation. Neither representation can recover score precision already lost before the NPZ was saved; preserve the original archive when comparing an older export.

`longdouble` varies by platform; its name or storage size alone does not establish its precision. Actual Linux controls with 16-byte storage and 64 significant bits exposed two former export failures: distinct `1.0000000000000000001` and `1.0` became tied, while a larger source-finite value became an unreadable infinite score. The same fidelity regression now requires faithful parsed scores or rejection before any output. This does not establish every extended dtype's layout. Obtain supported source scores for a new archive, or review an explicitly declared narrowing conversion separately for finite values and changed ties. A later audit cannot recover the source precision or certify that conversion.

You must explicitly declare the positive column. The exporter does not infer it from a larger score or framework name. By default every other candidate remains unjudged:

```sh
python scripts/export_rechorus.py test_predictions.npz --out local_export.csv --positive-index 0 --limit-queries 100
```

With these positive-only judgments, MRR@1 can be 1 because only queries with a known positive first are eligible. Read its coverage before interpreting it. The [synthetic example and explanation](metrics.md#positive-only-labels) show 1 of 2 queries eligible; this is not evidence that the whole run ranked perfectly.

For an already verified one-positive sampled-negative evaluation protocol, keep the default unknown labels from the export above and apply the nonrelevance assumption when auditing that existing CSV. Confirm export success and [check CSV/metadata pairing](#check-csv-and-metadata-pairing) before auditing copied files:

```sh
python -m rankprobe audit local_export.csv --unjudged nonrelevant --out reports/sampled-assumed
```

The report records `unjudged=nonrelevant`, an explicit assumption finding, and `assumed_nonrelevant_candidates` separately from the supplied-label count `judged_candidates`. This option applies to every unresolved candidate in the audit, so the verified protocol must justify that treatment for all of them. It does not establish complete qrels.

The export-time alternative `--other-candidates nonrelevant` writes literal `0` values into the CSV and records that choice in `<output>.metadata.json`. The core audit does not automatically ingest this sidecar: those zeros count as supplied labels, and the report cannot recover their export-time assumption from the CSV alone. Retain the sidecar with the CSV so the original declaration remains available for review. Counting a value as a supplied label does not verify its origin.

Either route declares an evaluation assumption; it does not prove that those items are truly irrelevant in the whole corpus. Multiple-positive conventions, ragged candidate arrays, padding scores, and alternative archive fields need a different declared adapter. A repeated declared positive is rejected because this convention would assign contradictory labels to one item.

## Identity and privacy

Each matrix row receives `query_000001`, etc., including multiple events for the same user. Item IDs are mapped to `item_000001`, etc., in first-appearance order. The mapping is not exported. Source user IDs, file paths, and original item IDs are omitted from the CSV and metadata.

The default `--identity local` mappings are local to each export. Cross-run comparison requires aligned source rows and an identical item mapping; independently shuffled exports do not satisfy that requirement merely because the remapped names look alike. Two different physical pools `[A,B,C]` and `[A,D,E]` can both become `item_000001/2/3`. Comparing those local names would falsely declare a matched pool.

For cross-run work, opt into `--identity source` and include a `query_id` array in the NPZ: a one-dimensional string vector with one unique, nonempty event/context ID per source row. The exporter preserves these query tokens and original integer/string item tokens, so candidate changes and reordered event rows remain inspectable. It validates every source query ID even when exporting only a prefix. Integer item IDs become exact decimal strings; text is preserved, and bytes must decode as UTF-8. Duplicate nonpositive candidates remain available to the audit; the existing repeated-positive rejection still applies.

```sh
python scripts/export_rechorus.py predictions.npz --out comparison-input.csv --positive-index 0 --identity source
```

This mode retains source identities. The caller must supply IDs from the same namespace and identify the same prediction context across runs; a unique user ID alone may omit changing time/history. The exporter cannot certify that assertion. Missing/invalid/duplicate event IDs fail instead of falling back to generated row names. Review retained query/item tokens before sharing, and protect exports with the same care as source data. The `user_id` array is not exported directly, but caller-supplied `query_id` tokens may themselves identify people.

The same identity requirement applies when attaching independent qrels to a **single** exported run. Source-ID qrels do not follow the default local pseudonym mapping, which is not exported. A successful audit or known inline positive does not prove a qrels pair matched. Use source mode only with shared, correctly aligned original event/item IDs; keep both old files and recover into a new export. The [three-case qrels walkthrough](../examples/npz-qrels/README.md) distinguishes this remapping mistake from legitimate judged items outside the candidate pool and explains what to recheck. Neither case justifies automatic remapping, dropping judgments or filling unknowns.

This is pseudonymization, not a guarantee of anonymity: scores and relationships can still identify an experiment or user activity. It also does not confer permission to redistribute a dataset or derivative prediction file.

## Output and reproducibility

The exporter writes CSV and `<output>.metadata.json`. Metadata records `source_sha256` for the NPZ, `predictions_sha256` for the completed CSV bytes, selected query count, positive column, negative assumption, identity mode and alignment/privacy caveats. The returned Python metadata and CLI JSON contain the same record as the saved sidecar. Existing outputs are refused unless `--overwrite` is explicit; neither output may replace the source archive, including through a symbolic link or hard link. The CSV and metadata must also be distinct files. No complete qrels are inferred.

### Check CSV and metadata pairing

A source fingerprint alone cannot select the CSV: the same NPZ can produce different labels or identities under different settings, and an older exporter can serialize scores differently. A retained integer-score regression, for example, had two different CSVs with identical source-only sidecars. New exports record the CSV fingerprint after closing the output file. The core audit still fingerprints its actual input and does not automatically ingest this sidecar or its label assumptions.

Save this read-only standard-library check as a local `check_npz_pair.py`, set `csv_path` to your export, and run it with the Python interpreter used for the audit. It compares the sidecar's recorded output fingerprint with the current CSV bytes:

```python
import hashlib
import json
from pathlib import Path
import re

csv_path = Path("local_export.csv")
metadata_path = csv_path.with_suffix(csv_path.suffix + ".metadata.json")
metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
expected = metadata.get("predictions_sha256") if isinstance(metadata, dict) else None
if not isinstance(expected, str) or re.fullmatch(r"[0-9a-f]{64}", expected) is None:
    raise ValueError(
        "No valid CSV fingerprint in this sidecar. Keep both originals; "
        "re-export the intended complete NPZ with declared settings to a new destination."
    )
digest = hashlib.sha256()
with csv_path.open("rb") as handle:
    for block in iter(lambda: handle.read(1024 * 1024), b""):
        digest.update(block)
if digest.hexdigest() != expected:
    raise ValueError(
        "CSV/metadata fingerprint mismatch. Keep both files; locate the matching pair "
        "or re-export the intended complete NPZ to a new destination before auditing."
    )
print("CSV bytes match the fingerprint recorded in this sidecar.")
```

Stop before auditing if this check fails; a failed pre-audit check is not RankProbe's completed-findings exit `1`. Missing files or malformed JSON also require finding the intended pair. Legacy sidecars without `predictions_sha256` cannot establish this byte match. Keep them unchanged and, when the complete source and declared settings are available, use the current exporter with a fresh destination. Adding a fingerprint to an arbitrary old sidecar cannot recover the original association. Do not change labels to repair a mismatch.

A byte-identical copy matches; even newline-only changes do not. A match establishes consistency with this recorded digest, not authenticity of either file, the declared positive column or label origin, source alignment, anonymity, or model quality. Hashing adds one streaming read of the CSV; concurrent modification and coordinated edits to both files are outside this check.

An empty or truncated NPZ, or a ZIP checksum or DEFLATE decoding failure while reading an array, is an input error: the CLI returns `2` with a recovery message, and the Python helper raises `ValueError`. These failures occur before CSV or metadata output. Complete `numpy.savez` and `numpy.savez_compressed` captures follow the same score, identity and label contract. Keep the failed capture unchanged, recapture the complete scores and aligned IDs into a new NPZ, and retry with a new CSV destination. Confirm export success before auditing; an old CSV is not evidence that this capture succeeded. Re-exporting needs the original complete source arrays and does not reconstruct missing predictions from a damaged archive.

Source archives are read only. To keep local experiments private, store exports and reports outside the repository or under an ignored directory. Public examples in this repository are synthetic. Real experiment validation should publish only reviewed aggregate observations with clear data-use permission.

The official ReChorus TopK presentation CSV is a different, lossy format. The [sampled runner capture recipe](rechorus-workflow.md) shows where to create this NPZ bridge before sorting/truncation, and explains positive-column and tie assumptions. It does not recover missing target/event information from a previously saved top-k CSV.

For the standard base ReChorus full-sort dev/test contract, use the [separate masked-score helper](rechorus-workflow.md#export-the-checked-base-full-sort-contract). It retains the observed target at column zero, records overlapping train/residual/target-copy exclusions and requires stable event IDs. Raw full-sort NPZ remains outside the sampled NPZ exporter's contract. ReChorus and RecBole have different column-zero meanings; their helpers are not interchangeable.
## TREC run compatibility

An explicit [TREC normalization helper](trec-normalization.md) handles the trailing run fields allowed by trec_eval. It creates a validated new file, refuses overwrites, and prints source/output hashes. The documented NIST case records the actual import obstacle and the query-coverage difference that becomes inspectable after conversion. This helper requires an installed RankProbe and the source checkout; it is not a new installed CLI subcommand.

Normalizing fields cannot restore discarded scores. Pyserini's MS MARCO writer emits only query ID, document ID and rank; its converter uses `1 / rank` for the TREC score. Those proxy values preserve a submitted order without recovering original ties or score gaps. Prefer retained scores from the same evaluation when inspecting score diagnostics. See the [fixed-source explanation and original miniature case](../examples/score-provenance/README.md); the rank-only format is not a new supported loader.

The [TREC-COVID Round 1 walkthrough](trec-covid-case.md) uses actual archived predictions and matching judgments, with source hashes and explicit format flags. It exposes sparse judgment coverage and real tied scores without requiring model training or a corpus download. Upstream files are fetched locally rather than bundled.

## BEIR export and evaluation

BEIR already writes compatible TREC predictions. The [integration recipe](beir-workflow.md) explains how to preserve results before in-place same-ID filtering, choose export depth and transfer actual qrels entries to four-column text. Its optional integration check calls the real BEIR modules on original synthetic inputs. BEIR and PyTorch are not RankProbe runtime requirements; model retrieval is outside this check.

## RecBole nonsequential full-sort

The [safe export helper and recipe](recbole-workflow.md) convert a complete masked score matrix from the same evaluation object's user/item mappings and history. Only declared padding/history positions are excluded, with reasons saved separately. Eligible nonfinite values, sequential contexts, invalid or duplicate IDs and inconsistent shapes are rejected. The caller must supply the exact scored user order and dataset; a same-shaped mapping from another experiment cannot be detected automatically. Predictions contain no inferred relevance labels. The helper requires optional NumPy; actual RecBole/PyTorch execution belongs to a separate bounded CI integration environment.
