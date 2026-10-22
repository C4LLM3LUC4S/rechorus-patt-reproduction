"""Compare a fixed public TREC-COVID run with an explicit native reference.

Existing inputs are read-only by default. --fetch explicitly downloads the fixed
files into a fresh directory: two for CLE-LMD, three with --pair. Nonrelevance is
a separate reference assumption; qrels completeness is never declared.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import tempfile
from urllib.request import Request, urlopen

from rankprobe.audit import compare_runs
from rankprobe.io import InputError, read_predictions, read_qrels
from rankprobe.metrics import evaluate_metrics, resolve_rows
from rankprobe.model import Protocol, Row


LIMIT = 2 * 1024 * 1024
CUTOFFS = (1, 5, 10)
ABSOLUTE_TOLERANCE = 0.00005000001
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
DFR_FILE = (
    "ir_covid19_cle_dfr",
    "https://ir.nist.gov/trec-covid/archive/round1/ir_covid19_cle_dfr",
    118231,
    "c919e38726909203d69cff6092f34421d03b6c52ebcfc800f0119a287b827692",
)
CASES = {
    "cle_lmd": (FILES[0], 2601, 781, 1820, (27, 19, 17)),
    "cle_dfr": (DFR_FILE, 2564, 825, 1739, (30, 30, 29)),
}
Qrels = dict[str, dict[str, float | None]]


class GateError(ValueError):
    """A path-free input, reference or protocol gate did not pass."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise GateError(message)


def _fingerprint(content: bytes, expected_bytes: int, expected_hash: str) -> str:
    require(len(content) <= LIMIT, "inputs: response exceeds the 2 MiB limit")
    digest = hashlib.sha256(content).hexdigest()
    require(len(content) == expected_bytes and digest == expected_hash,
            "inputs: byte length or SHA256 differs from the fixed public source")
    return digest


def fetch_inputs(inputs_dir: Path, *, files=None) -> None:
    """Fetch only fixed URLs; retain a failed fresh attempt for inspection."""
    inputs_dir = Path(inputs_dir)
    if inputs_dir.exists() or inputs_dir.is_symlink():
        raise FileExistsError("fetch: inputs directory must be fresh")
    inputs_dir.mkdir(parents=True, exist_ok=False)
    for name, url, expected_bytes, expected_hash in FILES if files is None else files:
        request = Request(url, headers={
            "User-Agent": "RankProbe-local-validation/0.1", "Accept": "text/plain",
        })
        with urlopen(request, timeout=30) as response:
            require(response.status == 200, "fetch: unexpected HTTP status")
            content = response.read(LIMIT + 1)
        _fingerprint(content, expected_bytes, expected_hash)
        with (inputs_dir / name).open("xb") as handle:
            handle.write(content)


def _verified_inputs(inputs_dir: Path, *, files=None) -> tuple[dict[str, Path], dict[str, str]]:
    inputs_dir = Path(inputs_dir)
    require(inputs_dir.is_dir() and not inputs_dir.is_symlink(),
            "inputs: directory must already exist and must not be a symlink")
    paths, hashes = {}, {}
    for name, _url, expected_bytes, expected_hash in FILES if files is None else files:
        path = inputs_dir / name
        require(path.is_file() and not path.is_symlink(),
                "inputs: each fixed source must be an existing regular file")
        with path.open("rb") as handle:
            content = handle.read(LIMIT + 1)
        hashes[name] = _fingerprint(content, expected_bytes, expected_hash)
        paths[name] = path.resolve(strict=True)
    return paths, hashes


def _validate_case(
    rows: list[Row], qrels: Qrels, *, counts=(2601, 781, 1820)
) -> tuple[list[str], int, int]:
    queries = sorted({row.query_id for row in rows})
    require(set(queries) == set(qrels) == {str(i) for i in range(1, 31)},
            "inputs: run and qrels must have the same fixed 30 queries")
    require(len(rows) == counts[0] and sum(map(len, qrels.values())) == 8691,
            "inputs: fixed run or qrels record count differs")
    require(len({(row.query_id, row.item_id) for row in rows}) == len(rows),
            "inputs: repeated retrieved document")
    require(all(row.relevance is None for row in rows),
            "inputs: original run must not have inline relevance labels")
    require(all(row.item_id.isascii() and row.query_id.isascii() for row in rows),
            "inputs: reference tie alignment requires ASCII identifiers")
    require(all(item.isascii() and grade in (0, 1, 2)
                for labels in qrels.values() for item, grade in labels.items()),
            "inputs: qrels must have ASCII document IDs and grades 0, 1 or 2")
    require(all(any(grade > 0 for grade in labels.values()) for labels in qrels.values()),
            "inputs: each fixed query must have a positive known judgment")
    supplied = sum(row.item_id in qrels[row.query_id] for row in rows)
    unknown = len(rows) - supplied
    require((supplied, unknown) == counts[1:],
            "inputs: supplied and missing candidate judgment counts differ")
    return queries, supplied, unknown


def _protocol(*, unjudged: str, tie_policy: str = "item_id") -> Protocol:
    return Protocol(cutoffs=CUTOFFS, tie_policy=tie_policy, gain="linear",
                    relevance_threshold=0, unjudged=unjudged, qrels_complete=False)


def _unknown_control(
    rows: list[Row], qrels: Qrels, *, unknown=1820, coverage=(27, 19, 17)
) -> dict:
    protocol = _protocol(unjudged="unknown")
    resolved = resolve_rows(rows, protocol, qrels)
    require(sum(row.relevance is None for row in resolved) == unknown,
            "default unknown: missing judgments were not preserved")
    metrics = evaluate_metrics(rows, protocol, qrels)
    for cutoff, count in zip(CUTOFFS, coverage):
        mrr = metrics[f"mrr@{cutoff}"]
        status = "ok" if count == len(qrels) else "partial"
        require(mrr["status"] == status and mrr["evaluated_queries"] == count
                and mrr["eligibility_rule"] == "known_first_relevant_prefix"
                and mrr["value"] is not None,
                "default unknown: MRR coverage differs")
        for prefix in ("ndcg", "recall"):
            metric = metrics[f"{prefix}@{cutoff}"]
            require(metric["value"] is None and metric["status"] == "not_checked"
                    and metric["evaluated_queries"] == 0,
                    "default unknown: unavailable metric became a value")
    return metrics


def _assumed_metrics(rows: list[Row], qrels: Qrels, *, tie_policy="item_id") -> dict:
    protocol = _protocol(unjudged="nonrelevant", tie_policy=tie_policy)
    require(all(row.relevance is not None for row in resolve_rows(rows, protocol, qrels)),
            "reference assumption: unresolved candidate")
    metrics = evaluate_metrics(rows, protocol, qrels)
    for cutoff in CUTOFFS:
        for prefix, reference in (("mrr", "submitted_candidates"),
                                  ("ndcg", "known_qrels_pool")):
            metric = metrics[f"{prefix}@{cutoff}"]
            require(metric["value"] is not None and metric["status"] == "partial"
                    and metric["reference"] == reference
                    and metric["evaluated_queries"] == len(qrels)
                    and metric["eligible_query_ids"] == sorted(qrels),
                    "reference assumption: availability, coverage or pool differs")
        recall = metrics[f"recall@{cutoff}"]
        require(recall["value"] is None and recall["status"] == "not_checked"
                and recall["evaluated_queries"] == 0,
                "reference assumption: incomplete qrels made Recall available")
    return metrics


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


def _compare_output(
    output: str, expected: dict[tuple[str, str], float], stage: str
) -> tuple[int, float]:
    values = {}
    for line in output.splitlines():
        if not line.strip():
            continue
        fields = line.split()
        require(len(fields) == 3, "reference output: expected three fields")
        metric, query, raw = fields
        try:
            value = float(raw)
        except ValueError as exc:
            raise GateError("reference output: nonnumeric value") from exc
        require(math.isfinite(value), "reference output: nonfinite value")
        key = metric, query
        require(key not in values, "reference output: repeated metric/query key")
        values[key] = value
    require(bool(expected) and values.keys() == expected.keys(),
            "reference output: metric/query keys differ")
    largest = 0.0
    for key, value in values.items():
        error = abs(value - expected[key])
        require(math.isclose(value, expected[key], rel_tol=0, abs_tol=ABSOLUTE_TOLERANCE),
                f"{stage}: numerical mismatch")
        largest = max(largest, error)
    return len(values), largest


def _macro_summary(metrics: dict) -> dict:
    fields = ("value", "status", "evaluated_queries", "total_queries",
              "excluded_queries", "reference", "query_universe", "eligibility_rule")
    return {key: {field: value[field] for field in fields if field in value}
            for key, value in sorted(metrics.items())}


def check_reference(
    executable: str | Path, inputs_dir: str | Path, *, fetch=False, case="cle_lmd"
) -> dict:
    """Execute the native comparison and return aggregate, path-free evidence."""
    require(case in CASES, "inputs: unknown fixed run")
    run_file, row_count, supplied_count, unknown_count, coverage = CASES[case]
    files = (run_file, FILES[1])
    executable = Path(executable).resolve(strict=True)
    require(executable.is_file(), "reference: executable must be a file")
    binary_hash = hashlib.sha256(executable.read_bytes()).hexdigest()
    checkout = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="rankprobe covid reference ") as temporary:
        root = Path(temporary).resolve()
        require(not root.is_relative_to(checkout), "reference: temporary directory is inside checkout")
        version = _run(executable, ["-v"], root)
        require(version.returncode == 0, "reference: version subprocess failed")
        match = re.search(r"trec_eval version ([A-Za-z0-9.+_-]+)",
                          version.stdout + "\n" + version.stderr)
        require(match is not None, "reference: trec_eval version was not identified")
        inputs_dir = Path(inputs_dir)
        if fetch:
            fetch_inputs(inputs_dir, files=files)
        paths, hashes_before = _verified_inputs(inputs_dir, files=files)
        run_path, qrels_path = (paths[item[0]] for item in files)
        try:
            rows = read_predictions(run_path, format="trec")
            qrels = read_qrels(qrels_path, format="trec")
        except InputError as exc:
            raise GateError("inputs: invalid TREC content") from exc
        queries, supplied, unknown = _validate_case(
            rows, qrels, counts=(row_count, supplied_count, unknown_count),
        )
        original_rows = list(rows)
        original_qrels = {query: dict(labels) for query, labels in qrels.items()}
        try:
            default = _unknown_control(rows, qrels, unknown=unknown_count, coverage=coverage)
            ascending = _assumed_metrics(rows, qrels)
            # Stable score sorting under input ties makes this new view match
            # NIST's descending ASCII docno ties. The original rows stay intact.
            aligned_rows = sorted(rows, key=lambda row: row.item_id, reverse=True)
            aligned = _assumed_metrics(aligned_rows, qrels, tie_policy="input")
            per_query = {}
            changed_ndcg_queries = {cutoff: 0 for cutoff in CUTOFFS}
            for query in queries:
                query_rows = [row for row in aligned_rows if row.query_id == query]
                labels = {query: qrels[query]}
                per_query[query] = _assumed_metrics(query_rows, labels, tie_policy="input")
                query_ascending = _assumed_metrics(query_rows, labels)
                for cutoff in CUTOFFS:
                    key = f"ndcg@{cutoff}"
                    changed_ndcg_queries[cutoff] += not math.isclose(
                        per_query[query][key]["value"], query_ascending[key]["value"],
                        rel_tol=0, abs_tol=1e-14,
                    )
            evaluated = {**per_query, "all": aligned}
            expected_ndcg = {
                (f"ndcg_cut_{cutoff}", query): metrics[f"ndcg@{cutoff}"]["value"]
                for query, metrics in evaluated.items() for cutoff in CUTOFFS
            }
            native = _run(executable, ["-q", "-l", "1", "-m", "ndcg_cut.1,5,10",
                                      str(qrels_path), str(run_path)], root)
            require(native.returncode == 0, "reference NDCG: subprocess failed")
            comparisons, largest_error = _compare_output(native.stdout, expected_ndcg,
                                                         "reference NDCG")
            native_macro = {
                f"ndcg@{metric.removeprefix('ndcg_cut_')}": float(value)
                for metric, query, value in (line.split() for line in native.stdout.splitlines()
                                              if line.strip()) if query == "all"
            }
            for cutoff in CUTOFFS:
                expected_mrr = {("recip_rank", query): metrics[f"mrr@{cutoff}"]["value"]
                                for query, metrics in evaluated.items()}
                native = _run(executable, ["-q", "-M", str(cutoff), "-l", "1",
                                          "-m", "recip_rank", str(qrels_path), str(run_path)],
                              root)
                require(native.returncode == 0, "reference MRR: subprocess failed")
                count, error = _compare_output(native.stdout, expected_mrr, "reference MRR")
                native_macro[f"mrr@{cutoff}"] = next(
                    float(value) for _metric, query, value in
                    (line.split() for line in native.stdout.splitlines() if line.strip())
                    if query == "all"
                )
                comparisons += count
                largest_error = max(largest_error, error)
            require(comparisons == 186, "reference: expected 186 comparisons")
        finally:
            _paths_after, hashes_after = _verified_inputs(inputs_dir, files=files)
            require(hashes_after == hashes_before, "inputs: original files changed during check")
            require(rows == original_rows and qrels == original_qrels,
                    "inputs: original in-memory rows or qrels changed during check")
            require(hashlib.sha256(executable.read_bytes()).hexdigest() == binary_hash,
                    "reference: executable changed during check")
    return {
        "status": "passed",
        "run": case,
        "reference_version": match.group(1),
        "reference_binary_sha256": binary_hash,
        "reference_provenance": (
            "Version/hash identify only the supplied binary; source pin requires build evidence"
        ),
        "sources": [{"filename": name, "url": url, "bytes": size, "sha256": digest}
                    for name, url, size, digest in files],
        "input_counts": {"prediction_rows": len(rows), "prediction_queries": len(queries),
                         "qrels_rows": sum(map(len, qrels.values())),
                         "qrels_queries": len(qrels), "supplied_candidate_judgments": supplied,
                         "missing_candidate_judgments": unknown},
        "shared_protocol": {"cutoffs": list(CUTOFFS), "comparisons": comparisons,
                            "maximum_absolute_error": largest_error,
                            "absolute_tolerance": ABSOLUTE_TOLERANCE, "relative_tolerance": 0,
                            "gain": "linear", "relevance_threshold": 0,
                            "unjudged": "nonrelevant", "qrels_complete": False,
                            "assumed_nonrelevant_candidates": unknown,
                            "query_universe": "same 30 submitted and qrels queries",
                            "query_ids": queries,
                            "ndcg_reference": "known_qrels_pool",
                            "tie_adapter": "new descending ASCII docno view; input tie policy",
                            "native_inputs": "original run and qrels; no rewritten files"},
        "default_unknown_control": {"assumed_nonrelevant_candidates": 0,
                                    "unknown_candidates": unknown,
                                    "qrels_complete": False,
                                    "macro_metrics": _macro_summary(default)},
        "nonrelevant_ascending_docno": _macro_summary(ascending),
        "nonrelevant_native_docno": _macro_summary(aligned),
        "native_macro_as_printed": native_macro,
        "tie_observation": {
            "ndcg_changed_queries": {str(k): count for k, count in changed_ndcg_queries.items()},
            "ndcg_at_10_macro_delta": aligned["ndcg@10"]["value"] - ascending["ndcg@10"]["value"],
        },
        "input_file_integrity": {"sha256_before": hashes_before, "sha256_after": hashes_after,
                                 "unchanged": True},
        "original_in_memory_inputs_unchanged": True,
        "scope": "Fixed public-input MRR/NDCG assumption comparison; Recall remains unavailable",
        "limits": [
            "The original unknown-policy report is not replaced or compared as a 30-query macro.",
            "No qrels completeness, full-corpus NDCG or universal evaluator parity is established.",
            "The supplied modern reference is not an identified historical 2020 executable.",
            "Historical 0.2286 is a rounded observation, not this check's acceptance target.",
            "No model quality, external adoption or human time saved is established.",
        ],
    }


def _end_to_end_summary(left: dict, right: dict) -> dict:
    """Compare whole runs only after both fixed native checks passed."""
    expected = {
        "cutoffs": list(CUTOFFS), "gain": "linear", "relevance_threshold": 0,
        "unjudged": "nonrelevant", "qrels_complete": False,
        "ndcg_reference": "known_qrels_pool",
        "tie_adapter": "new descending ASCII docno view; input tie policy",
        "query_ids": sorted(str(i) for i in range(1, 31)),
    }
    require(left.get("status") == right.get("status") == "passed",
            "pair: both native checks must pass")
    for field in ("reference_version", "reference_binary_sha256"):
        require(left.get(field) is not None and left[field] == right.get(field),
                "pair: native reference identity differs")
    for result in (left, right):
        require(all(result.get("shared_protocol", {}).get(k) == v for k, v in expected.items()),
                "pair: declared protocol or topics differ")
    differences = {}
    for prefix, reference in (("mrr", "submitted_candidates"), ("ndcg", "known_qrels_pool")):
        for cutoff in CUTOFFS:
            key = f"{prefix}@{cutoff}"
            values, printed = [], []
            for result in (left, right):
                metric = result.get("nonrelevant_native_docno", {}).get(key, {})
                value = metric.get("value")
                native = result.get("native_macro_as_printed", {}).get(key)
                require(isinstance(value, (int, float)) and math.isfinite(value)
                        and isinstance(native, (int, float)) and math.isfinite(native)
                        and metric.get("evaluated_queries") == metric.get("total_queries") == 30
                        and metric.get("status") == "partial"
                        and metric.get("reference") == reference,
                        "pair: macro availability, query population or reference differs")
                require(math.isclose(value, native, rel_tol=0, abs_tol=ABSOLUTE_TOLERANCE),
                        "pair: native macro evidence differs")
                values.append(value)
                printed.append(native)
            differences[key] = {
                "left": values[0], "right": values[1], "delta": values[1] - values[0],
                "native_left_as_printed": printed[0], "native_right_as_printed": printed[1],
                "native_delta_as_printed": printed[1] - printed[0],
                "native_delta_absolute_tolerance": 2 * ABSOLUTE_TOLERANCE,
            }
    return {
        "scope": "Whole submitted retrieval runs under the separate native protocol; "
                 "not a matched-pool delta or a significance test",
        "left": "cle_lmd", "right": "cle_dfr", "query_count": 30,
        "macro_difference_dfr_minus_lmd": differences,
        "recall": "unavailable; qrels completeness was not declared",
    }


def check_pair(executable: str | Path, inputs_dir: str | Path, *, fetch=False) -> dict:
    """Recheck the public diagnostic with a separate whole-retrieval experiment."""
    files = (*FILES, DFR_FILE)
    inputs_dir = Path(inputs_dir)
    if fetch:
        fetch_inputs(inputs_dir, files=files)
    paths, before = _verified_inputs(inputs_dir, files=files)
    try:
        results = {case: check_reference(executable, inputs_dir, case=case) for case in CASES}
        comparison = _end_to_end_summary(results["cle_lmd"], results["cle_dfr"])
        rows = {case: read_predictions(paths[spec[0][0]], format="trec")
                for case, spec in CASES.items()}
        qrels = read_qrels(paths[FILES[1][0]], format="trec")
        diagnostic = compare_runs(rows, _protocol(unjudged="unknown"), qrels)["pairs"][0]
        matched = diagnostic["matched_pool_comparison"]
        require(diagnostic["status"] == "not_comparable" and matched["query_count"] == 0
                and diagnostic["candidate_sets"]["differing_queries"] == 30
                and all(v["delta"] is None for v in matched["delta_right_minus_left"].values()),
                "pair: default same-pool diagnostic changed")
    finally:
        _, after = _verified_inputs(inputs_dir, files=files)
        require(before == after, "pair: original files changed during check")
    return {
        "status": "passed", "comparisons": 372, "runs": results,
        "end_to_end_comparison": comparison,
        "same_pool_control": {"status": diagnostic["status"], "matched_queries": 0,
                              "differing_candidate_sets": 30, "metric_deltas": "unavailable"},
        "input_file_integrity": {"sha256_before": before, "sha256_after": after,
                                 "unchanged": True},
        "limits": ["No candidate intersection, missing-score synthesis or source rewriting.",
                   "Native assumptions do not supply judgments or replace the default reports.",
                   "No historical executable reproduction, significance, model certification, "
                   "external adoption or human time saved is established."],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trec-eval", required=True, type=Path,
                        help="explicit native reference executable")
    parser.add_argument("--inputs-dir", required=True, type=Path,
                        help="existing fixed inputs, or a fresh directory with --fetch")
    parser.add_argument("--fetch", action="store_true",
                        help="explicitly fetch the fixed public files into a fresh directory")
    parser.add_argument("--pair", action="store_true",
                        help="check both original runs and a separate end-to-end comparison")
    parser.add_argument("--summary", type=Path, help="write a new path-free JSON summary")
    arguments = parser.parse_args()
    if arguments.summary and (arguments.summary.exists() or arguments.summary.is_symlink()):
        parser.error("--summary must name a new file; existing paths are never replaced")
    try:
        check = check_pair if arguments.pair else check_reference
        result = check(arguments.trec_eval, arguments.inputs_dir, fetch=arguments.fetch)
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
