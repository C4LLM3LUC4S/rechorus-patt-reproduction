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


def _input_format(path: Path, format: str, *, qrels: bool = False) -> str:
    if format not in {"auto", "csv", "jsonl", "trec"}:
        raise InputError(f"{path}: format must be auto, csv, jsonl, or trec")
    if format != "auto":
        return format
    extension = path.suffix.lower()
    if extension in {".csv", ".jsonl"}:
        return extension[1:]
    trec_extensions = {".qrels"} if qrels else {".run", ".trec"}
    if extension in trec_extensions:
        return "trec"
    supported = ".csv, .jsonl, and .qrels" if qrels else ".csv, .jsonl, .run, and .trec"
    cli_option = "--qrels-format" if qrels else "--input-format"
    raise InputError(
        f"{path}: supported extensions are {supported}; for TREC text use "
        f"{cli_option} trec (CLI) or format='trec' (Python)"
    )


def _records(path: Path, required: set[str], format: str) -> Iterator[tuple[int, dict]]:
    csv_line_number = 0

    def csv_lines(handle):
        nonlocal csv_line_number
        for line in handle:
            csv_line_number += 1
            yield line

    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            if format == "csv":
                reader = csv.DictReader(csv_lines(handle), strict=True)
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
            elif format == "jsonl":
                for line_number, line in enumerate(handle, 1):
                    if not line.strip():
                        continue
                    try:
                        record = json.loads(
                            line, object_pairs_hook=_unique_keys, parse_constant=_reject_constant
                        )
                    except RecursionError as exc:
                        fields = (
                            "query_id,item_id,score and relevance when supplied"
                            if "score" in required else "query_id,item_id,relevance"
                        )
                        raise InputError(
                            f"{path}:{line_number}: JSON nesting is too deep. "
                            f"Export a new flat JSONL from the source with {fields}. "
                            "Preserve identifiers, numeric values, label availability and row order; "
                            "keep the original unchanged."
                        ) from exc
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
    except csv.Error as exc:
        message = f"{path}: cannot read input: {exc}"
        if csv_line_number:
            message += (
                f" (CSV parser stopped at physical line {csv_line_number}; "
                "the record may start earlier)"
            )
        if str(exc).startswith("field larger than field limit"):
            fields = (
                "query_id,item_id,score and relevance when supplied"
                if "score" in required else "query_id,item_id,relevance"
            )
            message += (
                ". The CSV field limit also applies to unused text columns. "
                f"Export a new minimal CSV with {fields}, or equivalent JSONL. "
                "Preserve identifiers, numeric values and all supplied labels; "
                "keep the original unchanged."
            )
        else:
            message += (
                ". Check CSV quoting and delimiters in a new source export; "
                "keep the original unchanged."
            )
        raise InputError(message) from exc
    except (OSError, UnicodeError) as exc:
        raise InputError(f"{path}: cannot read input: {exc}") from exc


def _trec_records(path: Path, columns: int) -> Iterator[tuple[int, list[str]]]:
    try:
        with path.open("r", encoding="utf-8-sig") as handle:
            for line_number, line in enumerate(handle, 1):
                if "\x00" in line:
                    raise InputError(f"{path}:{line_number}: TREC input cannot contain NUL characters")
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                fields = stripped.split()
                if len(fields) != columns:
                    raise InputError(
                        f"{path}:{line_number}: expected exactly {columns} whitespace-separated TREC fields"
                    )
                yield line_number, fields
    except (OSError, UnicodeError) as exc:
        raise InputError(f"{path}: cannot read input: {exc}") from exc


def _float(value: object, field: str, *, optional: bool = False) -> int | float | None:
    if optional and (value is None or value == ""):
        return None
    if isinstance(value, bool) or value is None or isinstance(value, (list, dict)):
        raise ValueError(f"{field} must be a finite number")
    try:
        if isinstance(value, int):
            result = value
        elif isinstance(value, str):
            token = value.strip()
            digits = token[1:] if token[:1] in {"+", "-"} else token
            if digits.isascii() and digits.isdigit():
                # Strip redundant zeroes before int's digit limit, retaining
                # the existing float sign for a textual negative zero.
                significant = digits.lstrip("0") or "0"
                if token.startswith("-") and significant == "0":
                    result = -0.0
                else:
                    result = int(significant)
                    if token.startswith("-"):
                        result = -result
            else:
                # Decimal/exponent syntax keeps the binary64 contract.
                result = float(value)
        else:
            result = float(value)
        finite = math.isfinite(result)
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError(f"{field} must be a finite number") from exc
    if not finite:
        raise ValueError(f"{field} must be a finite number")
    return result


def read_predictions(path: str | Path, *, format: str = "auto") -> list[Row]:
    """Read CSV/JSONL or six-column TREC input without changing file order.

    TREC iteration, declared rank, and tag are not ranking inputs. Rank must
    still be a non-negative integer; score and the audit's tie policy govern
    evaluation. Ambiguous extensions require an explicit format.
    """
    source = Path(path)
    selected = _input_format(source, format)
    rows = []
    if selected == "trec":
        for line_number, fields in _trec_records(source, 6):
            query, _iteration, item, rank, score, _tag = fields
            try:
                if not rank.isascii() or not rank.isdigit():
                    raise ValueError("rank must be a non-negative integer (ignored for ordering)")
                rows.append(Row(query, item, _float(score, "score")))
            except ValueError as exc:
                raise InputError(f"{source}:{line_number}: {exc}") from exc
        if not rows:
            raise InputError(f"{source}: no prediction rows")
        return rows
    for line_number, record in _records(source, {"query_id", "item_id", "score"}, selected):
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


def read_qrels(path: str | Path, *, format: str = "auto") -> dict[str, dict[str, float | None]]:
    """Read judgments, preserving TREC -1 as an explicit unknown pair.

    Non-negative graded floats extend TREC's integer judgment convention.
    CSV/JSONL keep their existing contract requiring known non-negative labels.
    """
    source = Path(path)
    selected = _input_format(source, format, qrels=True)
    result: dict[str, dict[str, float | None]] = {}
    if selected == "trec":
        for line_number, fields in _trec_records(source, 4):
            query, _iteration, item, grade = fields
            try:
                _identifier(query, "query_id")
                _identifier(item, "item_id")
                relevance = _float(grade, "relevance")
                if relevance < 0 and relevance != -1:
                    raise ValueError(
                        "TREC relevance must be non-negative or -1 (unjudged). "
                        "Other negative values may be source-specific annotations; keep the "
                        "original and check its grade definition and evaluator. "
                        "--unjudged does not reinterpret them. See "
                        "https://github.com/C4LLM3LUC4S/rechorus-patt-reproduction/"
                        "blob/main/tools/rankprobe/docs/input-format.md"
                        "#source-specific-negative-judgments"
                    )
                labels = result.setdefault(query, {})
                if item in labels:
                    raise ValueError(
                        f"duplicate qrels entry for query {query!r}, item {item!r}; "
                        "expected one ordinary query-item judgment. Field 2 is ignored; "
                        "if it represents subtopics/intents, use a scope-appropriate ordinary "
                        "export or the native evaluator. See "
                        "https://github.com/C4LLM3LUC4S/rechorus-patt-reproduction/"
                        "blob/main/tools/rankprobe/docs/input-format.md"
                        "#subtopic-and-diversity-judgments"
                    )
                labels[item] = None if relevance == -1 else relevance
            except ValueError as exc:
                raise InputError(f"{source}:{line_number}: {exc}") from exc
        if not result:
            raise InputError(f"{source}: no qrels rows")
        return result
    for line_number, record in _records(source, {"query_id", "item_id", "relevance"}, selected):
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
