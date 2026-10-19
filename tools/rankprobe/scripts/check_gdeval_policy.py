"""Check a pinned gdeval judgment/averaging policy on original miniature files.

This optional native check does not establish RankProbe metric parity or the
behavior of the unavailable historical 2011 evaluator.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
from pathlib import Path
import re
import subprocess


SOURCE_SHA256 = "723ae1254f298ceac475fbc04941a87005f3daf0b7872ee809a745a05c985d31"
SOURCE_COMMIT = "912a21f96b9d489938fc649c5545836bc16038b9"
CASES = ("baseline_default", "baseline_complete", "spam_first", "unknown_first", "zero_first")


class GateError(ValueError):
    """A bounded check failed without exposing local paths or captured logs."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise GateError(message)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_output(text: str) -> dict:
    try:
        rows = list(csv.reader(io.StringIO(text), strict=True))
    except csv.Error as exc:
        raise GateError("CSV: invalid syntax") from exc
    require(bool(rows) and rows[0] == ["runid", "topic", "ndcg@1", "err@1"],
            "CSV: expected the depth-one header")
    result = {}
    runids = set()
    for row in rows[1:]:
        require(len(row) == 4 and bool(row[0]) and bool(row[1]), "CSV: invalid record")
        require(row[1] not in result, "CSV: duplicate topic")
        try:
            ndcg, err = float(row[2]), float(row[3])
        except ValueError as exc:
            raise GateError("CSV: invalid metric number") from exc
        require(math.isfinite(ndcg) and math.isfinite(err), "CSV: nonfinite metric number")
        runids.add(row[0])
        result[row[1]] = {"runid": row[0], "ndcg": ndcg, "err": err}
    require(bool(result) and len(runids) == 1, "CSV: expected records with one run ID")
    return result


def validate_policy(outputs: dict) -> dict:
    require(set(outputs) == set(CASES), "policy: case set differs")
    for name in CASES:
        require(set(outputs[name]) == {"1", "amean"}, "policy: reported topic set differs")
    expected_means = dict.fromkeys(CASES, 0.0)
    expected_means.update(baseline_default=1.0, baseline_complete=0.5)
    for name in CASES:
        expected_topic = 1.0 if name.startswith("baseline_") else 0.0
        require(math.isclose(outputs[name]["1"]["ndcg"], expected_topic,
                             rel_tol=0, abs_tol=0.000005), "policy: topic NDCG differs")
        require(math.isclose(outputs[name]["amean"]["ndcg"], expected_means[name],
                             rel_tol=0, abs_tol=0.000005), "policy: mean NDCG differs")
    return {
        "reported_topic_ids": {name: ["1"] for name in CASES},
        "mean_ndcg_at_1": {name: outputs[name]["amean"]["ndcg"] for name in CASES},
        "baseline_topic_ndcg_at_1": {
            name: outputs[name]["1"]["ndcg"] for name in CASES[:2]
        },
        "nonpositive_first_ndcg_at_1": {
            name: outputs[name]["1"]["ndcg"] for name in CASES[2:]
        },
        "missing_run_positive_topic": "2", "nonpositive_only_run_topic": "3",
    }


def run_native(arguments: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    try:
        result = subprocess.run(arguments, cwd=cwd, shell=False, check=False,
                                capture_output=True, encoding="utf-8", errors="strict", timeout=60)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GateError("native process: could not complete within 60 seconds") from exc
    require(result.returncode == 0, "native process: nonzero exit status")
    return result


def check_policy(gdeval: Path, perl: str, out: Path) -> dict:
    out = Path(out).absolute()
    require(not out.exists() and not out.is_symlink(), "output: directory must be new")
    require(not any(parent.is_symlink() for parent in out.parents),
            "output: symbolic-link ancestors are not allowed")
    require(out.parent.is_dir(), "output: parent directory must already exist")
    source = Path(gdeval).absolute()
    require(source.is_file() and not source.is_symlink(), "source: regular file required")
    require(not source.resolve().is_relative_to(out.resolve()), "source: must be outside output")
    require(digest(source) == SOURCE_SHA256, "source: fixed SHA256 differs")
    version = run_native([perl, "-e", "print $^V;"]).stdout.strip()
    require(re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", version) is not None,
            "Perl version: unexpected output")
    out.mkdir(exist_ok=False)
    qrels = out / "judgments.qrels"
    with qrels.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write("1 0 positive 1\n1 0 spam -2\n1 0 unknown -1\n1 0 zero 0\n"
                     "2 0 second_positive 1\n3 0 third_spam -2\n"
                     "3 0 third_unknown -1\n3 0 third_zero 0\n")
    baseline = ("positive", "spam", "unknown", "zero")
    orders = dict.fromkeys(CASES[:2], baseline)
    orders.update(spam_first=("spam", "positive", "unknown", "zero"),
                  unknown_first=("unknown", "positive", "spam", "zero"),
                  zero_first=("zero", "positive", "spam", "unknown"))
    inputs = [qrels]
    for name, order in orders.items():
        path = out / f"{name}.run"
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            for rank, item in enumerate(order, 1):
                handle.write(f"1 Q0 {item} {rank} {5 - rank} policy\n")
            handle.write("3 Q0 third_zero 1 1 policy\n")
        inputs.append(path)
    hashes_before = {path.name: digest(path) for path in inputs}
    require(hashes_before["baseline_default.run"] == hashes_before["baseline_complete.run"],
            "inputs: baseline runs differ")
    outputs, csv_hashes, stderr_present = {}, {}, {}
    for name in CASES:
        require(digest(source) == SOURCE_SHA256, "source: changed before execution")
        options = ["-c"] if name == "baseline_complete" else []
        process = run_native([perl, str(source), *options, "-k", "1", qrels.name,
                              f"{name}.run"], cwd=out)
        csv_path = out / f"{name}.csv"
        with csv_path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(process.stdout)
        outputs[name] = parse_output(process.stdout)
        csv_hashes[csv_path.name] = digest(csv_path)
        stderr_present[name] = bool(process.stderr)
    observations = validate_policy(outputs)
    require(digest(source) == SOURCE_SHA256, "source: changed during execution")
    require(all(digest(path) == hashes_before[path.name] for path in inputs),
            "inputs: original miniature files changed")
    result = {
        "status": "passed", "gdeval_source_commit": SOURCE_COMMIT,
        "gdeval_source_sha256": SOURCE_SHA256, "gdeval_source_version": "1.3 (2013-04-29)",
        "perl_version": version, "invocations": 5, "synthetic_input_sha256": hashes_before,
        "csv_sha256": csv_hashes, "observations": observations,
        "stderr_present": stderr_present,
        "checks": {"fixed_source_unchanged": True, "original_inputs_unchanged": True,
                   "positive_only_topic_universe_observed": True,
                   "default_and_complete_means_observed": True,
                   "nonpositive_first_zero_ndcg_observed": True},
        "limitations": [
            "Original miniature policy cases only; no benchmark data or model was used.",
            "ERR is parsed as a finite CSV number, not validated as a metric implementation.",
            "No RankProbe metric parity, grade conversion, completeness assertion or equivalence "
            "with the unavailable historical 2011 evaluator is established.",
        ],
    }
    with (out / "summary.json").open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(result, handle, indent=2, ensure_ascii=True, allow_nan=False)
        handle.write("\n")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gdeval", required=True, type=Path)
    parser.add_argument("--perl", default="perl")
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        result = check_policy(args.gdeval, args.perl, args.out)
    except (ValueError, OSError, RuntimeError) as exc:
        result = {"status": "failed", "reason": str(exc) if isinstance(exc, GateError)
                  else type(exc).__name__}
    print(json.dumps(result, indent=2, ensure_ascii=True, allow_nan=False))
    return int(result["status"] != "passed")


if __name__ == "__main__":
    raise SystemExit(main())
