"""Export a declared one-positive NPZ convention without importing a framework."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path


def export_npz(
    source: Path,
    destination: Path,
    *,
    positive_index: int,
    other_candidates: str = "unknown",
    limit_queries: int | None = None,
    overwrite: bool = False,
) -> dict:
    """Write remapped candidate rows and return non-identifying export metadata.

    Labels are assertions supplied by the caller, not recovered training facts.
    Query identifiers represent matrix rows, never user IDs.
    """
    try:
        import numpy as np
    except ImportError as exc:
        raise ValueError(
            'This optional exporter needs NumPy: pip install -e ".[adapters]"'
        ) from exc

    source, destination = Path(source), Path(destination)
    metadata_path = destination.with_suffix(destination.suffix + ".metadata.json")
    if source.resolve() in (destination.resolve(), metadata_path.resolve()):
        raise ValueError("Output must not replace the source NPZ.")
    if not overwrite and (destination.exists() or metadata_path.exists()):
        raise ValueError("Output already exists; choose a new path or pass --overwrite.")
    if other_candidates not in {"unknown", "nonrelevant"}:
        raise ValueError("other_candidates must be unknown or nonrelevant.")
    if limit_queries is not None and limit_queries < 1:
        raise ValueError("limit_queries must be positive.")

    with np.load(source, allow_pickle=False) as archive:
        if not {"scores", "item_id"}.issubset(archive.files):
            raise ValueError("NPZ must contain scores and item_id arrays.")
        scores = archive["scores"]
        items = archive["item_id"]
        if scores.ndim != 2 or items.shape != scores.shape or 0 in scores.shape:
            raise ValueError("scores and item_id must have the same nonempty 2-D shape.")
        if scores.dtype.kind not in "iuf" or not np.isfinite(scores).all():
            raise ValueError("scores must contain finite real numbers.")
        if items.dtype.kind not in "iuUS":
            raise ValueError("item_id must contain integer or string identifiers.")
        if not 0 <= positive_index < scores.shape[1]:
            raise ValueError("positive_index is outside the candidate columns.")
        if "user_id" in archive.files and len(archive["user_id"]) != len(scores):
            raise ValueError("user_id length does not match prediction rows.")

        row_count = min(len(scores), limit_queries) if limit_queries else len(scores)
        exported = []
        item_mapping: dict[str, str] = {}
        for query_number in range(row_count):
            row_items = [str(value).strip() for value in items[query_number].tolist()]
            if any(not item for item in row_items):
                raise ValueError("Item identifiers must not be empty.")
            positive_item = row_items[positive_index]
            if row_items.count(positive_item) != 1:
                raise ValueError("The declared positive item is repeated within a query.")
            for column, (item, score) in enumerate(zip(row_items, scores[query_number])):
                if item not in item_mapping:
                    item_mapping[item] = f"item_{len(item_mapping) + 1:06d}"
                relevance = (
                    "1"
                    if column == positive_index
                    else ("0" if other_candidates == "nonrelevant" else "")
                )
                exported.append(
                    (
                        f"query_{query_number + 1:06d}",
                        item_mapping[item],
                        format(float(score), ".17g"),
                        relevance,
                    )
                )

    digest = hashlib.sha256()
    with source.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    metadata = {
        "source_sha256": digest.hexdigest(),
        "source_queries": len(scores),
        "exported_queries": row_count,
        "candidates_per_query": scores.shape[1],
        "exported_rows": len(exported),
        "positive_index": positive_index,
        "other_candidates": other_candidates,
        "query_identity": "matrix row number; source rows must align across runs",
        "item_identity": "first-appearance mapping within this export only",
        "user_ids_exported": False,
        "qrels_complete": False,
        "privacy_note": "Pseudonymization does not establish anonymity or redistribution rights.",
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(("query_id", "item_id", "score", "relevance"))
        writer.writerows(exported)
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return metadata


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--positive-index", type=int, required=True)
    parser.add_argument("--other-candidates", choices=("unknown", "nonrelevant"), default="unknown")
    parser.add_argument("--limit-queries", type=int)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    try:
        metadata = export_npz(
            args.source,
            args.out,
            positive_index=args.positive_index,
            other_candidates=args.other_candidates,
            limit_queries=args.limit_queries,
            overwrite=args.overwrite,
        )
    except (ValueError, OSError, KeyError, TypeError) as exc:
        parser.exit(2, f"Export error: {exc}\n")
    print(json.dumps(metadata, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
