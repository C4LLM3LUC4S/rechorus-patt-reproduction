"""Export a declared one-positive NPZ convention without importing a framework."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import csv
import hashlib
import json
from pathlib import Path
from zipfile import BadZipFile
import zlib


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


@contextmanager
def _read_npz(source: Path, np):
    try:
        loaded = np.load(source, allow_pickle=False)
        if isinstance(loaded, np.ndarray):
            raise ValueError(
                "Expected an NPZ archive with named scores and item_id arrays; found a single "
                "NPY array. Keep the original unchanged; capture complete aligned arrays with "
                "numpy.savez or numpy.savez_compressed into a new file."
            )
        with loaded as archive:
            yield archive
    except (BadZipFile, EOFError, zlib.error) as exc:
        raise ValueError(
            "NPZ archive is incomplete or damaged. Keep the original unchanged and create "
            "a new NPZ from the complete source arrays; use a new CSV destination."
        ) from exc


def _source_identifier(value: object, field: str, *, integer: bool = False) -> str:
    """Preserve text exactly, decode bytes strictly, and never round integer IDs."""
    if isinstance(value, bytes):
        try:
            value = value.decode("utf-8", errors="strict")
        except UnicodeError as exc:
            raise ValueError(f"{field} must contain valid UTF-8 identifiers.") from exc
    elif integer and isinstance(value, int) and not isinstance(value, bool):
        value = str(value)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must contain nonempty string identifiers.")
    if len(value) > 4096:
        raise ValueError(f"{field} exceeds the 4096-character input limit.")
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise ValueError(f"{field} must contain valid UTF-8 identifiers.") from exc
    return value


def export_npz(
    source: Path,
    destination: Path,
    *,
    positive_index: int,
    other_candidates: str = "unknown",
    limit_queries: int | None = None,
    identity: str = "local",
    overwrite: bool = False,
) -> dict:
    """Write candidate rows using export-local or explicitly preserved identities.

    Labels are assertions supplied by the caller, not recovered training facts.
    Local mode pseudonymizes rows/items independently within each export. Source
    mode requires caller-supplied stable event IDs in ``query_id`` and preserves
    original item IDs for comparisons. The caller must establish that the IDs
    refer to the same events/items across runs; the exporter cannot verify this.
    """
    try:
        import numpy as np
    except ImportError as exc:
        raise ValueError(
            'This optional exporter needs NumPy: pip install -e ".[adapters]"'
        ) from exc

    source, destination = Path(source), Path(destination)
    metadata_path = destination.with_suffix(destination.suffix + ".metadata.json")
    outputs = (destination, metadata_path)
    if (source.resolve() in (path.resolve() for path in outputs)
            or any(path.exists() and source.samefile(path) for path in outputs)):
        raise ValueError("Output must not replace the source NPZ.")
    if (destination.resolve() == metadata_path.resolve()
            or (destination.exists() and metadata_path.exists()
                and destination.samefile(metadata_path))):
        raise ValueError("Prediction CSV and metadata must not refer to the same file.")
    if not overwrite and (destination.exists() or metadata_path.exists()):
        raise ValueError("Output already exists; choose a new path or pass --overwrite.")
    if other_candidates not in {"unknown", "nonrelevant"}:
        raise ValueError("other_candidates must be unknown or nonrelevant.")
    if identity not in {"local", "source"}:
        raise ValueError("identity must be local or source.")
    if limit_queries is not None and limit_queries < 1:
        raise ValueError("limit_queries must be positive.")

    with _read_npz(source, np) as archive:
        if not {"scores", "item_id"}.issubset(archive.files):
            raise ValueError("NPZ must contain scores and item_id arrays.")
        scores = archive["scores"]
        items = archive["item_id"]
        if scores.ndim != 2 or items.shape != scores.shape or 0 in scores.shape:
            raise ValueError("scores and item_id must have the same nonempty 2-D shape.")
        if scores.dtype.kind not in "iuf" or not np.isfinite(scores).all():
            raise ValueError("scores must contain finite real numbers.")
        if scores.dtype.kind == "f" and scores.dtype.itemsize > 8:
            raise ValueError(
                "Floating-point score dtypes wider than 64 bits are unsupported by this core. "
                "Keep the original NPZ; an explicit source conversion needs separate checks "
                "for finite values and changed ties before a new export."
            )
        if items.dtype.kind not in "iuUS":
            raise ValueError("item_id must contain integer or string identifiers.")
        if not 0 <= positive_index < scores.shape[1]:
            raise ValueError("positive_index is outside the candidate columns.")
        if "user_id" in archive.files and len(archive["user_id"]) != len(scores):
            raise ValueError("user_id length does not match prediction rows.")
        query_ids = None
        if identity == "source":
            if "query_id" not in archive.files:
                raise ValueError("Source identity requires a query_id array of stable event IDs.")
            queries = archive["query_id"]
            if queries.ndim != 1 or len(queries) != len(scores) or queries.dtype.kind not in "US":
                raise ValueError("query_id must be a 1-D string array matching every score row.")
            # Validate the entire event universe before selecting a prefix.
            query_ids = [_source_identifier(value, "query_id") for value in queries.tolist()]
            if len(set(query_ids)) != len(query_ids):
                raise ValueError("query_id must contain unique stable event IDs, not repeated user IDs.")

        row_count = min(len(scores), limit_queries) if limit_queries else len(scores)
        exported = []
        item_mapping: dict[str, str] = {}
        for query_number in range(row_count):
            row_items = (
                [_source_identifier(value, "item_id", integer=True)
                 for value in items[query_number].tolist()]
                if identity == "source"
                else [str(value).strip() for value in items[query_number].tolist()]
            )
            if any(not item for item in row_items):
                raise ValueError("Item identifiers must not be empty.")
            positive_item = row_items[positive_index]
            if row_items.count(positive_item) != 1:
                raise ValueError("The declared positive item is repeated within a query.")
            for column, (item, score) in enumerate(zip(row_items, scores[query_number])):
                if identity == "local" and item not in item_mapping:
                    item_mapping[item] = f"item_{len(item_mapping) + 1:06d}"
                relevance = (
                    "1"
                    if column == positive_index
                    else ("0" if other_candidates == "nonrelevant" else "")
                )
                exported.append(
                    (
                        query_ids[query_number] if query_ids is not None
                        else f"query_{query_number + 1:06d}",
                        item if identity == "source" else item_mapping[item],
                        str(int(score)) if scores.dtype.kind in "iu" else format(float(score), ".17g"),
                        relevance,
                    )
                )

    metadata = {
        "source_sha256": _sha256(source),
        "source_queries": len(scores),
        "exported_queries": row_count,
        "candidates_per_query": scores.shape[1],
        "exported_rows": len(exported),
        "positive_index": positive_index,
        "other_candidates": other_candidates,
        "identity_mode": identity,
        "retained_source_ids": identity == "source",
        "query_identity": (
            "caller-supplied stable event IDs from query_id; user_id array is not used"
            if identity == "source"
            else "matrix row number; source rows must align across runs"
        ),
        "item_identity": (
            "original item_id identifiers; integer IDs are exact decimal strings"
            if identity == "source"
            else "first-appearance mapping within this export only"
        ),
        "caller_alignment": (
            "caller must establish shared event/item meanings across exports; preserved IDs are not proof"
            if identity == "source"
            else "independent local pseudonyms cannot establish shared physical pools or event alignment"
        ),
        "user_ids_exported": None if identity == "source" else False,
        "user_id_array_exported": False,
        "qrels_complete": False,
        "privacy_note": (
            "Source query/item IDs are retained and may identify people; anonymity and redistribution rights are not established."
            if identity == "source"
            else "Pseudonymization does not establish anonymity or redistribution rights."
        ),
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(("query_id", "item_id", "score", "relevance"))
        writer.writerows(exported)
    metadata["predictions_sha256"] = _sha256(destination)
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return metadata


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--positive-index", type=int, required=True)
    parser.add_argument("--other-candidates", choices=("unknown", "nonrelevant"), default="unknown")
    parser.add_argument("--limit-queries", type=int)
    parser.add_argument(
        "--identity", choices=("local", "source"), default="local",
        help="source preserves item IDs and requires caller-supplied stable query_id event IDs",
    )
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    try:
        metadata = export_npz(
            args.source,
            args.out,
            positive_index=args.positive_index,
            other_candidates=args.other_candidates,
            limit_queries=args.limit_queries,
            identity=args.identity,
            overwrite=args.overwrite,
        )
    except (ValueError, OSError, KeyError, TypeError) as exc:
        parser.exit(2, f"Export error: {exc}\n")
    print(json.dumps(metadata, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
