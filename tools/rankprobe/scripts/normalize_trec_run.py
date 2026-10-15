"""Explicitly copy the first six TREC run fields to a new, validated file."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import tempfile

from rankprobe.io import InputError, read_predictions


def normalize_run(source: Path, destination: Path) -> dict:
    source, destination = Path(source), Path(destination)
    if source.resolve() == destination.resolve():
        raise ValueError("Output must not replace the source run.")
    if destination.exists():
        raise ValueError("Output already exists; choose a new path.")
    original = source.read_bytes()
    lines = []
    stripped_rows = 0
    for number, line in enumerate(original.decode("utf-8-sig").split("\n"), 1):
        if "\x00" in line:
            raise ValueError(f"{source}:{number}: TREC input cannot contain NUL characters")
        if not line.strip() or line.lstrip().startswith("#"):
            lines.append(line)
            continue
        fields = line.split()
        if len(fields) < 6:
            raise ValueError(f"{source}:{number}: expected at least 6 TREC run fields")
        stripped_rows += len(fields) > 6
        lines.append(" ".join(fields[:6]))
    normalized = ("\n".join(lines) + "\n").encode("utf-8")
    with tempfile.TemporaryDirectory(prefix="rankprobe normalize ") as directory:
        candidate = Path(directory) / "candidate.run"
        candidate.write_bytes(normalized)
        try:
            rows = read_predictions(candidate)
        except InputError as exc:
            raise ValueError(str(exc).replace(str(candidate), str(source), 1)) from exc
    if source.read_bytes() != original:
        raise ValueError("Source changed during normalization; no output written.")
    with destination.open("xb") as handle:
        handle.write(normalized)
    return {
        "status": "converted",
        "rows": len(rows),
        "rows_with_trailing_fields_removed": stripped_rows,
        "source_sha256": hashlib.sha256(original).hexdigest(),
        "output_sha256": hashlib.sha256(normalized).hexdigest(),
        "operation": "first_six_run_fields; original_order_preserved; no_labels_added",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    arguments = parser.parse_args(argv)
    try:
        result = normalize_run(arguments.source, arguments.destination)
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"Normalization failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
