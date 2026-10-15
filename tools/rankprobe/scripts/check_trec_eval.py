"""Cross-check declared ranking protocols against an explicit trec_eval binary.

Only original synthetic inputs are created. This does not download or build the
reference, establish qrels completeness for user data, or certify model quality.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import random
import re
import subprocess
import tempfile

from rankprobe.metrics import evaluate_metrics
from rankprobe.model import Protocol, Row


ABSOLUTE_TOLERANCE = 0.00005000001
CUTOFFS = (1, 2, 5, 10)
GENERATOR_SEED = 20261015


class GateError(ValueError):
    """A named reference or protocol gate did not pass."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise GateError(message)


def parse_output(text: str) -> dict[tuple[str, str], float]:
    """Parse the three-column reference format without accepting ambiguous rows."""
    values = {}
    for line_number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        fields = line.split()
        require(len(fields) == 3, f"reference output: line {line_number} needs three fields")
        metric, query, raw_value = fields
        try:
            value = float(raw_value)
        except ValueError as exc:
            raise GateError(f"reference output: line {line_number} is not numeric") from exc
        require(math.isfinite(value), f"reference output: line {line_number} is not finite")
        key = metric, query
        require(key not in values, f"reference output: duplicate key at line {line_number}")
        values[key] = value
    require(bool(values), "reference output: no metric rows")
    return values


@dataclass
class Case:
    name: str
    rows: list[Row]
    qrels: dict[str, dict[str, int]]


def _fixed_cases() -> list[Case]:
    return [
        Case("binary", [Row("q1", "n", 9), Row("q1", "r", 7)],
             {"q1": {"n": 0, "r": 1, "unretrieved": 1}}),
        Case("graded", [Row("q1", "n", 9), Row("q1", "medium", 7),
                        Row("q1", "low", 5), Row("q1", "high", 3)],
             {"q1": {"n": 0, "low": 1, "medium": 2, "high": 3, "unretrieved": 1}}),
        Case("macro", [Row("q1", "r", 4), Row("q1", "n", 2), Row("q2", "n", 9)],
             {"q1": {"r": 1, "n": 0}, "q2": {"n": 0, "unretrieved": 2}}),
        Case("late-positive", [Row("q1", f"d{i}", 20 - i) for i in range(7)],
             {"q1": {**{f"d{i}": int(i == 6) for i in range(7)}, "unretrieved": 3}}),
    ]


def _seeded_cases() -> list[Case]:
    generator = random.Random(GENERATOR_SEED)
    cases = []
    for case_index in range(20):
        qrels = {}
        rows = []
        for query_index in range(generator.randint(1, 4)):
            query = f"q{query_index}"
            count = generator.randint(4, 18)
            judgments = {f"d{i:02d}": generator.randint(0, 3) for i in range(count)}
            # This original synthetic universe has explicit judgments for every
            # item and at least one positive, including possibly unreturned items.
            judgments["d00"] = generator.randint(1, 3)
            qrels[query] = judgments
            items = generator.sample(list(judgments), generator.randint(1, count))
            scores = generator.sample(range(-100, 101), len(items))
            rows.extend(Row(query, item, score) for item, score in zip(items, scores))
        generator.shuffle(rows)
        cases.append(Case(f"seeded-{case_index:02d}", rows, qrels))
    return cases


def _write_case(case: Case, root: Path) -> tuple[Path, Path]:
    directory = root / case.name
    directory.mkdir()
    qrels = directory / "judgments.qrels"
    run = directory / "predictions.run"
    qrels.write_text("".join(
        f"{query} 0 {item} {grade}\n"
        for query, judgments in sorted(case.qrels.items())
        for item, grade in sorted(judgments.items())
    ), encoding="utf-8", newline="\n")
    # Deliberately misleading ranks verify that scores, rather than the rank
    # field or input order, determine retrieval order in this shared protocol.
    run.write_text("".join(
        f"{row.query_id} Q0 {row.item_id} {len(case.rows) - index} {row.score} synthetic\n"
        for index, row in enumerate(case.rows)
    ), encoding="utf-8", newline="\n")
    return qrels, run


def _run(executable: Path, arguments: list[str], root: Path) -> subprocess.CompletedProcess:
    allowed = ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "TMPDIR",
               "LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH")
    environment = {name: os.environ[name] for name in allowed if name in os.environ}
    environment["LC_ALL"] = "C"
    try:
        return subprocess.run(
            [str(executable), *arguments], cwd=root, env=environment,
            shell=False, check=False, capture_output=True, encoding="utf-8",
            errors="replace", timeout=30,
        )
    except subprocess.TimeoutExpired as exc:
        raise GateError("reference: exceeded 30 seconds") from exc
    except OSError as exc:
        raise GateError("reference: could not start the subprocess") from exc


def _reference(
    executable: Path, paths: tuple[Path, Path], cutoff: int, root: Path, *, complete=False
) -> dict[tuple[str, str], float]:
    arguments = ["-q", "-M", str(cutoff), "-l", "1", "-m", "recip_rank",
                 "-m", f"ndcg_cut.{cutoff}", "-m", f"recall.{cutoff}"]
    if complete:
        arguments.append("-c")
    arguments.extend(str(path) for path in paths)
    result = _run(executable, arguments, root)
    require(result.returncode == 0, f"reference: subprocess exited {result.returncode}")
    return parse_output(result.stdout)


def _aliases(cutoff: int) -> dict[str, str]:
    return {"recip_rank": f"mrr@{cutoff}", f"ndcg_cut_{cutoff}": f"ndcg@{cutoff}",
            f"recall_{cutoff}": f"recall@{cutoff}"}


def _close(actual: float, expected: float, stage: str) -> float:
    error = abs(actual - expected)
    require(math.isclose(actual, expected, rel_tol=0, abs_tol=ABSOLUTE_TOLERANCE),
            f"{stage}: numerical mismatch ({actual:.17g} versus {expected:.17g})")
    return error


def _check_shared(case: Case, executable: Path, root: Path) -> tuple[int, float]:
    paths = _write_case(case, root)
    queries = sorted(case.qrels)
    require(set(queries) == {row.query_id for row in case.rows}, "shared: query sets differ")
    count, largest_error = 0, 0.0
    for cutoff in CUTOFFS:
        protocol = Protocol(cutoffs=(cutoff,), gain="linear", qrels_complete=True)
        reference = _reference(executable, paths, cutoff, root)
        aliases = _aliases(cutoff)
        expected_keys = {(metric, query) for metric in aliases for query in [*queries, "all"]}
        require(set(reference) == expected_keys, "shared: reference metric/query keys differ")
        evaluated = {"all": evaluate_metrics(case.rows, protocol, case.qrels)}
        for query in queries:
            evaluated[query] = evaluate_metrics(
                [row for row in case.rows if row.query_id == query],
                protocol, {query: case.qrels[query]},
            )
        for (metric, query), value in reference.items():
            observed = evaluated[query][aliases[metric]]
            require(observed["status"] == "ok" and observed["value"] is not None,
                    "shared: RankProbe metric is unavailable or partial")
            largest_error = max(largest_error, _close(
                observed["value"], value, f"shared {case.name} {query} {metric}",
            ))
            count += 1
    return count, largest_error


def _check_boundaries(executable: Path, root: Path) -> dict:
    one = Protocol(cutoffs=(1,), qrels_complete=True)
    tie = Case("boundary-ties", [Row("q1", "a", 1), Row("q1", "z", 1)],
               {"q1": {"a": 0, "z": 1}})
    tied_reference = _reference(executable, _write_case(tie, root), 1, root)
    tied_probe = evaluate_metrics(tie.rows, one, tie.qrels)
    _close(tied_reference["recip_rank", "all"], 1, "boundary ties reference")
    require(tied_probe["mrr@1"]["value"] == 0, "boundary ties: ascending policy differs")

    missing = Case("boundary-unknown", [Row("q1", "unknown", 2), Row("q1", "r", 1)],
                   {"q1": {"r": 1}})
    missing_paths = _write_case(missing, root)
    unknown = evaluate_metrics(missing.rows, Protocol(cutoffs=(1, 2)), missing.qrels)
    require(all(metric["value"] is None for metric in unknown.values()),
            "boundary unknown: missing judgment became a value")
    unknown_reference = {}
    for cutoff, expected in ((1, 0), (2, 0.5)):
        values = _reference(executable, missing_paths, cutoff, root)
        _close(values["recip_rank", "all"], expected, "boundary unknown reference")
        unknown_reference[f"mrr@{cutoff}"] = values["recip_rank", "all"]

    zero = Case("boundary-no-positive", [Row("q1", "r", 1), Row("q2", "n", 1)],
                {"q1": {"r": 1}, "q2": {"n": 0}})
    zero_reference = _reference(executable, _write_case(zero, root), 1, root)
    zero_probe = evaluate_metrics(zero.rows, one, zero.qrels)
    _close(zero_reference["recall_1", "q2"], 0, "boundary no-positive query")
    _close(zero_reference["recall_1", "all"], 0.5, "boundary no-positive macro")
    require(zero_probe["recall@1"]["value"] == 1
            and zero_probe["recall@1"]["evaluated_queries"] == 1
            and zero_probe["recall@1"]["excluded_query_ids"] == ["q2"],
            "boundary no-positive: Recall exclusion differs")

    absent = Case("boundary-qrels-only", [Row("q1", "r", 1)],
                  {"q1": {"r": 1}, "q2": {"r": 1}})
    absent_paths = _write_case(absent, root)
    default = _run(executable, ["-m", "recip_rank", *(str(p) for p in absent_paths)], root)
    # This is the observed control flow of the CI-pinned upstream commit,
    # despite its help text describing a default intersection of query sets.
    require(default.returncode == 4, "boundary qrels-only: pinned default exit code differs")
    absent_reference = _reference(executable, absent_paths, 1, root, complete=True)
    _close(absent_reference["recip_rank", "all"], 0.5, "boundary qrels-only reference")
    absent_probe = evaluate_metrics(absent.rows, one, absent.qrels)["mrr@1"]
    require(absent_probe["value"] == 1 and absent_probe["status"] == "partial"
            and absent_probe["qrels_only_queries"] == 1,
            "boundary qrels-only: submitted-query scope differs")
    return {
        "ties": {"rankprobe_mrr_at_1": 0, "reference_mrr_at_1": 1,
                 "reason": "RankProbe ascending item_id; reference descending docno"},
        "unknown_judgments": {"rankprobe_values": None, "reference": unknown_reference,
                              "reason": "RankProbe preserves unknown; reference treats as nonrelevant"},
        "no_positive_recall": {"rankprobe_macro": 1, "reference_macro": 0.5,
                               "reason": "RankProbe excludes zero-positive query; reference includes zero"},
        "qrels_only": {"reference_default_exit_code": default.returncode,
                       "rankprobe_mrr_macro": 1, "reference_complete_mrr_macro": 0.5,
                       "reason": "RankProbe submitted-query scope; reference -c includes missing query"},
    }


def check_reference(executable: str | Path) -> dict:
    """Exercise an actual supplied executable and return a path-free summary."""
    executable = Path(executable).resolve(strict=True)
    require(executable.is_file(), "reference: executable must be a file")
    binary_hash = hashlib.sha256(executable.read_bytes()).hexdigest()
    checkout = Path(__file__).resolve().parents[1]
    cases = [*_fixed_cases(), *_seeded_cases()]
    count, largest_error = 0, 0.0
    with tempfile.TemporaryDirectory(prefix="rankprobe reference ") as temporary:
        root = Path(temporary).resolve()
        require(not root.is_relative_to(checkout), "reference: temporary directory is inside checkout")
        version = _run(executable, ["-v"], root)
        require(version.returncode == 0, "reference: version subprocess failed")
        match = re.search(r"trec_eval version ([A-Za-z0-9.+_-]+)",
                          version.stdout + "\n" + version.stderr)
        require(match is not None, "reference: trec_eval version was not identified")
        for case in cases:
            comparisons, error = _check_shared(case, executable, root)
            count += comparisons
            largest_error = max(largest_error, error)
        boundaries = _check_boundaries(executable, root)
    require(hashlib.sha256(executable.read_bytes()).hexdigest() == binary_hash,
            "reference: executable changed during check")
    return {
        "status": "passed", "reference_version": match.group(1),
        "reference_binary_sha256": binary_hash,
        "shared_protocol": {"fixed_cases": 4, "seeded_cases": 20,
                            "generator_seed": GENERATOR_SEED, "cutoffs": list(CUTOFFS),
                            "comparisons": count, "maximum_absolute_error": largest_error,
                            "absolute_tolerance": ABSOLUTE_TOLERANCE,
                            "gain": "linear", "relevance_threshold": 0,
                            "qrels": "original fully judged synthetic universes"},
        "asserted_boundaries": boundaries,
        "scope": "Synthetic protocol cross-check; no claim of universal parity or user time saved",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trec-eval", required=True, type=Path, help="explicit reference executable")
    parser.add_argument("--summary", type=Path, help="write a new path-free JSON summary")
    arguments = parser.parse_args()
    if arguments.summary and (arguments.summary.exists() or arguments.summary.is_symlink()):
        parser.error("--summary must name a new file; existing paths are never replaced")
    try:
        result = check_reference(arguments.trec_eval)
    except (ValueError, OSError, KeyError, TypeError, RuntimeError) as exc:
        reason = str(exc) if isinstance(exc, GateError) else type(exc).__name__
        result = {"status": "failed", "reason": reason}
    if arguments.summary:
        try:
            arguments.summary.parent.mkdir(parents=True, exist_ok=True)
            with arguments.summary.open("x", encoding="utf-8", newline="\n") as handle:
                json.dump(result, handle, indent=2, ensure_ascii=True, allow_nan=False)
                handle.write("\n")
        except OSError:
            result = {"status": "failed", "reason": "summary: new file could not be written"}
    print(json.dumps(result, indent=2, ensure_ascii=True, allow_nan=False))
    return int(result["status"] != "passed")


if __name__ == "__main__":
    raise SystemExit(main())
