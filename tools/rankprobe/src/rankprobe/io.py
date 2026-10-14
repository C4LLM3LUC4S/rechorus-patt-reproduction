"""Strict, read-only loaders with file and line context for invalid records."""

import csv
import json
import math
from pathlib import Path
from typing import Iterator

from .model import Row, _identifier


class InputError(ValueError):
    """An input file does not satisfy the published data contract."""


def _unique_keys(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number: {value}")


def _records(path: Path, required: set[str]) -> Iterator[tuple[int, dict]]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            if path.suffix.lower() == ".csv":
                reader = csv.DictReader(handle, strict=True)
                fields = reader.fieldnames
                if not fields:
                    raise InputError(f"{path}: missing CSV header")
                if len(fields) != len(set(fields)):
                    raise InputError(f"{path}: duplicate CSV column names")
                missing = required - set(fields)
                if missing:
                    raise InputError(f"{path}: missing columns: {', '.join(sorted(missing))}")
                for record in reader:
                    if None in record:
                        raise InputError(f"{path}:{reader.line_num}: extra cells beyond CSV header")
                    if any(value is None for value in record.values()):
                        raise InputError(f"{path}:{reader.line_num}: missing cells")
                    yield reader.line_num, record
            elif path.suffix.lower() == ".jsonl":
                for line_number, line in enumerate(handle, 1):
                    if not line.strip():
                        continue
                    try:
                        record = json.loads(
                            line, object_pairs_hook=_unique_keys, parse_constant=_reject_constant
                        )
                    except ValueError as exc:
                        raise InputError(f"{path}:{line_number}: {exc}") from exc
                    if not isinstance(record, dict):
                        raise InputError(f"{path}:{line_number}: expected one JSON object per line")
                    missing = required - record.keys()
                    if missing:
                        raise InputError(
                            f"{path}:{line_number}: missing fields: {', '.join(sorted(missing))}"
                        )
                    yield line_number, record
            else:
                raise InputError(f"{path}: supported extensions are .csv and .jsonl")
    except (OSError, UnicodeError, csv.Error) as exc:
        raise InputError(f"{path}: cannot read input: {exc}") from exc


def _float(value: object, field: str, *, optional: bool = False) -> float | None:
    if optional and (value is None or value == ""):
        return None
    if isinstance(value, bool) or value is None or isinstance(value, (list, dict)):
        raise ValueError(f"{field} must be a finite number")
    try:
        result = float(value)
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError(f"{field} must be a finite number") from exc
    if not math.isfinite(result):
        raise ValueError(f"{field} must be a finite number")
    return result


def read_predictions(path: str | Path) -> list[Row]:
    source = Path(path)
    rows = []
    for line_number, record in _records(source, {"query_id", "item_id", "score"}):
        try:
            rows.append(
                Row(
                    record["query_id"],
                    record["item_id"],
                    _float(record["score"], "score"),
                    _float(record.get("relevance"), "relevance", optional=True),
                )
            )
        except ValueError as exc:
            raise InputError(f"{source}:{line_number}: {exc}") from exc
    if not rows:
        raise InputError(f"{source}: no prediction rows")
    return rows


def read_qrels(path: str | Path) -> dict[str, dict[str, float]]:
    source = Path(path)
    result: dict[str, dict[str, float]] = {}
    for line_number, record in _records(source, {"query_id", "item_id", "relevance"}):
        try:
            query, item = record["query_id"], record["item_id"]
            _identifier(query, "query_id")
            _identifier(item, "item_id")
            relevance = _float(record["relevance"], "relevance")
            if relevance < 0:
                raise ValueError("relevance must be non-negative")
            labels = result.setdefault(query, {})
            if item in labels:
                raise ValueError(f"duplicate qrels entry for query {query!r}, item {item!r}")
            labels[item] = relevance
        except ValueError as exc:
            raise InputError(f"{source}:{line_number}: {exc}") from exc
    if not result:
        raise InputError(f"{source}: no qrels rows")
    return result
