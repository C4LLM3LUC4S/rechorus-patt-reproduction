"""Exercise fitted scores, a shared observed-item pool and retained-score recovery.

MovieLens data and row-level outputs stay local. Only summary.json is intended
for reviewed aggregate evidence. This is a research/software case, not a native
framework benchmark, production retrieval stage or human adoption experiment.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import csv
import hashlib
import json
import math
from pathlib import Path
import platform
import subprocess
import sys
import time
from urllib.request import urlopen
from zipfile import BadZipFile, ZipFile
import zlib

from rankprobe.io import read_predictions, read_qrels
from rankprobe.metrics import evaluate_metrics
from rankprobe.model import Protocol


URL = "https://files.grouplens.org/datasets/movielens/ml-100k.zip"
ARCHIVE_BYTES = 4924029
ARCHIVE_SHA256 = "50d2a982c66986937beb9ffb3aa76efe955bf3d5c6b761f4e3a7cd717c6a3229"
SOURCES = {
    "ml-100k/README": "4883b8cf340ed0059971b33f56ad3adc88a40792108ebca3d24aafc4c82e8b52",
    "ml-100k/u1.base": "ce253ec86c448b44fb3ba9a30d12dcfc2e9210cbde71efada3730c22e9ac212a",
    "ml-100k/u1.test": "18c6014a4b2c7324f250a63f8904a7b16b2b19f911129e346141507b0cbac950",
}
CUTOFFS = (1, 5, 10)
MODEL = {"bias_iterations": 10, "bias_regularization": 10.0, "factors": 8,
         "epochs": 8, "batch_size": 512, "learning_rate": 0.01,
         "factor_regularization": 0.02, "seed": 20261021}


class GateError(ValueError):
    """A bounded input, score or report acceptance failed."""


def require(condition, message):
    if not condition:
        raise GateError(message)


def digest(path):
    checksum = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            checksum.update(block)
    return checksum.hexdigest()


def new_output(path):
    path = Path(path).absolute()
    require(not path.exists() and not path.is_symlink(), "output: choose a new directory")
    require(path.parent.is_dir(), "output: parent directory must already exist")
    require(not any(parent.is_symlink() for parent in path.parents),
            "output: symbolic-link ancestors are unsupported")
    return path


def fetch_archive(path):
    path = Path(path)
    require(not path.exists() and not path.is_symlink(), "fetch: choose a new archive path")
    require(path.parent.is_dir(), "fetch: parent directory must already exist")
    with urlopen(URL, timeout=60) as response:
        content = response.read(ARCHIVE_BYTES + 1)
    require(len(content) == ARCHIVE_BYTES
            and hashlib.sha256(content).hexdigest() == ARCHIVE_SHA256,
            "fetch: fixed source byte length or SHA256 differs")
    with path.open("xb") as handle:
        handle.write(content)


def parse_ratings(content):
    records, seen = [], set()
    for line in content.splitlines():
        fields = line.split()
        require(len(fields) == 4, "ratings: expected four integer fields")
        try:
            user, item, rating, timestamp = map(int, fields)
        except ValueError as exc:
            raise GateError("ratings: expected four integer fields") from exc
        require(user > 0 and item > 0 and timestamp > 0 and 1 <= rating <= 5,
                "ratings: invalid ID, timestamp or observed rating")
        require((user, item) not in seen, "ratings: repeated user-item pair")
        seen.add((user, item))
        records.append((user, item, rating, timestamp))
    require(bool(records), "ratings: empty input")
    return records


def verified_inputs(archive):
    archive = Path(archive)
    require(archive.is_file() and not archive.is_symlink(), "inputs: expected a regular archive")
    require(archive.stat().st_size == ARCHIVE_BYTES and digest(archive) == ARCHIVE_SHA256,
            "inputs: fixed source byte length or SHA256 differs")
    with ZipFile(archive) as package:
        content = {name: package.read(name) for name in SOURCES}
    for name, value in content.items():
        require(hashlib.sha256(value).hexdigest() == SOURCES[name],
                "inputs: selected source member SHA256 differs")
    train = parse_ratings(content["ml-100k/u1.base"])
    test = parse_ratings(content["ml-100k/u1.test"])
    require(len(train) == 80000 and len(test) == 20000, "inputs: fixed split counts differ")
    require(not ({r[:2] for r in train} & {r[:2] for r in test}),
            "inputs: a source pair occurs in both predefined splits")
    return train, test


def fitted_scores(train, test_pairs):
    """Fit only observed training ratings; no test rating enters this interface."""
    try:
        import numpy as np
    except ImportError as exc:
        raise GateError('optional case needs NumPy: pip install -e ".[adapters]"') from exc
    training = np.asarray(train, dtype=np.int64)
    pairs = np.asarray(test_pairs, dtype=np.int64)
    require(training.ndim == 2 and training.shape[1] == 4 and pairs.ndim == 2
            and pairs.shape[1] == 2 and len(training) > 0 and len(pairs) > 0,
            "fit: expected observed training rows and evaluation ID pairs")
    users, items = training[:, 0], training[:, 1]
    ratings = training[:, 2].astype(np.float64)
    user_count = int(users.max()) + 1
    item_count = int(items.max()) + 1
    user_n = np.bincount(users, minlength=user_count)
    item_n = np.bincount(items, minlength=item_count)
    mean = float(ratings.mean())
    user_bias, item_bias = np.zeros(user_count), np.zeros(item_count)
    for _ in range(MODEL["bias_iterations"]):
        user_bias = np.bincount(users, weights=ratings - mean - item_bias[items],
                                minlength=user_count) / (MODEL["bias_regularization"] + user_n)
        item_bias = np.bincount(items, weights=ratings - mean - user_bias[users],
                                minlength=item_count) / (MODEL["bias_regularization"] + item_n)
    rng = np.random.default_rng(MODEL["seed"])
    p = rng.normal(0, 0.1, (user_count, MODEL["factors"]))
    q = rng.normal(0, 0.1, (item_count, MODEL["factors"]))
    p[user_n == 0] = 0
    q[item_n == 0] = 0
    for _ in range(MODEL["epochs"]):
        order = rng.permutation(len(training))
        for offset in range(0, len(order), MODEL["batch_size"]):
            batch = order[offset:offset + MODEL["batch_size"]]
            u, i = users[batch], items[batch]
            pu, qi = p[u].copy(), q[i].copy()
            error = ratings[batch] - mean - user_bias[u] - item_bias[i] - (pu * qi).sum(axis=1)
            np.add.at(p, u, MODEL["learning_rate"] * (
                error[:, None] * qi - MODEL["factor_regularization"] * pu))
            np.add.at(q, i, MODEL["learning_rate"] * (
                error[:, None] * pu - MODEL["factor_regularization"] * qi))
    # Cold evaluation IDs use the zero-bias/factor sentinel, not a larger fit.
    u = np.where(pairs[:, 0] < user_count, pairs[:, 0], 0)
    i = np.where(pairs[:, 1] < item_count, pairs[:, 1], 0)
    bias = mean + user_bias[u] + item_bias[i]
    factors = bias + (p[u] * q[i]).sum(axis=1)
    require(np.isfinite(bias).all() and np.isfinite(factors).all(), "fit: nonfinite predictions")
    return np.stack([bias, factors]), {"numpy": np.__version__, "training_mean": mean,
        "unseen_training_items_in_evaluation": int((item_n[i] == 0).sum()),
        "parameters": dict(MODEL), "training_ratings_used": len(training),
        "test_rating_access": False, "missing_ratings_added": 0}


def write_predictions(path, records, scores, *, rounded=False):
    require(len(records) == len(scores), "export: source record and score lengths differ")
    with Path(path).open("x", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(("query_id", "item_id", "score"))
        for (user, item, _rating, _timestamp), score in zip(records, scores):
            require(math.isfinite(float(score)), "export: nonfinite score")
            writer.writerow((f"ml100k-u1-user:{user}", str(item),
                             format(float(score), ".1f" if rounded else ".17g")))


def recover(capture, output):
    """Re-export this case's retained factor scores without fitting or labels."""
    out = new_output(output)
    capture = Path(capture)
    require(capture.is_file() and not capture.is_symlink(),
            "recovery: expected a regular retained-scores.npz capture")
    try:
        import numpy as np
        from numpy.lib.npyio import NpzFile
    except ImportError as exc:
        raise GateError('optional case needs NumPy: pip install -e ".[adapters]"') from exc
    before = digest(capture)
    try:
        retained = np.load(capture, allow_pickle=False)
        require(isinstance(retained, NpzFile),
                "recovery: expected named pairs/scores NPZ arrays, not a single NPY array")
        with retained:
            require(sorted(retained.files) == ["pairs", "scores"],
                    "recovery: expected only pairs and scores from this case's capture")
            pairs, scores = retained["pairs"], retained["scores"]
            require(pairs.ndim == 2 and pairs.shape[1] == 2 and len(pairs) > 0
                    and pairs.dtype.kind in "iu" and bool(np.all(pairs > 0)),
                    "recovery: pairs must be nonempty positive integer user/item rows")
            require(len(np.unique(pairs, axis=0)) == len(pairs),
                    "recovery: repeated user/item pairs; obtain an intact original capture")
            require(scores.shape == (2, len(pairs)) and scores.dtype.kind == "f"
                    and scores.dtype.itemsize == 8 and bool(np.all(np.isfinite(scores))),
                    "recovery: scores must be two finite binary64 vectors in bias/factors order")
    except GateError:
        raise
    except (ValueError, OSError, KeyError, BadZipFile, EOFError, zlib.error) as exc:
        raise GateError("recovery: unreadable capture; keep it and obtain an intact original "
                        "pairs/scores NPZ, without reconstructing scores from rounded values") from exc
    require(digest(capture) == before, "recovery: capture changed while reading; retry from a stable copy")
    out.mkdir()
    csv_path = out / "recovered.csv"
    # The shared writer ignores rating/timestamp; no labels are read or invented.
    records = ((int(user), int(item), None, None) for user, item in pairs)
    write_predictions(csv_path, list(records), scores[1])
    require(digest(capture) == before, "recovery: source capture changed during export")
    receipt = {"status": "passed", "operation": "reexport_retained_factor_scores",
               "capture_sha256": before, "csv_sha256": digest(csv_path),
               "rows": len(pairs), "queries": len(np.unique(pairs[:, 0])),
               "score_source": "second binary64 vector in this case's retained capture",
               "judgments_read_or_added": 0, "refitted": False,
               "capture_unchanged": True,
               "scope": "format/export check; source identity and quality are not certified"}
    (out / "recovery.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return receipt


def independent_metrics(records, scores):
    """Independent binary RR/DCG formula, lexical IDs and zero-IDCG convention."""
    require(len(records) == len(scores), "oracle: source record and score lengths differ")
    grouped = defaultdict(list)
    for (user, item, rating, _timestamp), score in zip(records, scores):
        grouped[f"ml100k-u1-user:{user}"].append((str(item), float(score), int(rating >= 4)))
    per_query = {}
    for query, rows in grouped.items():
        ranked = sorted(rows, key=lambda r: (-r[1], r[0]))
        positives = sum(row[2] for row in rows)
        values = {}
        for cutoff in CUTOFFS:
            values[f"mrr@{cutoff}"] = next(
                (1 / rank for rank, row in enumerate(ranked[:cutoff], 1) if row[2]), 0.0)
            dcg = sum(row[2] / math.log2(rank + 1)
                      for rank, row in enumerate(ranked[:cutoff], 1))
            ideal = sum(1 / math.log2(rank + 1) for rank in range(1, min(positives, cutoff) + 1))
            values[f"ndcg@{cutoff}"] = dcg / ideal if ideal else 0.0
        per_query[query] = values
    keys = [f"{metric}@{cutoff}" for cutoff in CUTOFFS for metric in ("mrr", "ndcg")]
    return per_query, {key: sum(v[key] for v in per_query.values()) / len(per_query) for key in keys}


def verify_metrics(csv_path, records, scores, qrels, report_metrics):
    per_query, macro = independent_metrics(records, scores)
    grouped = defaultdict(list)
    for row in read_predictions(csv_path):
        grouped[row.query_id].append(row)
    require(set(grouped) == set(per_query), "oracle: exported query population differs")
    checked = 0
    for query, expected in per_query.items():
        actual = evaluate_metrics(grouped[query], Protocol(
            cutoffs=CUTOFFS, tie_policy="item_id", gain="linear", relevance_threshold=0,
            unjudged="unknown", qrels_complete=False), {query: qrels[query]})
        for key, value in expected.items():
            require(math.isclose(actual[key]["value"], value, rel_tol=0, abs_tol=1e-12),
                    "oracle: per-query score/label result differs")
            checked += 1
    for key, value in macro.items():
        require(math.isclose(report_metrics[key]["value"], value, rel_tol=0, abs_tol=1e-12),
                "oracle: CLI macro differs")
        require(report_metrics[key]["evaluated_queries"] == len(per_query),
                "oracle: CLI metric population differs")
        checked += 1
    return macro, checked


def cli_report(out, name, arguments):
    result = subprocess.run([sys.executable, "-m", "rankprobe", *arguments,
                             "--cutoffs", "1,5,10", "--tie-policy", "item_id", "--gain", "linear",
                             "--relevance-threshold", "0", "--unjudged", "unknown",
                             "--out", str(out / name)],
                            capture_output=True, text=True, timeout=120)
    require(result.returncode == 0, "CLI: report did not complete; inspect retained local files")
    return json.loads((out / name / "report.json").read_text(encoding="utf-8"))


def check(archive, output):
    out = new_output(output)
    train, test = verified_inputs(archive)
    started = time.monotonic()
    scores, model = fitted_scores(train, [r[:2] for r in test])
    fit_seconds = time.monotonic() - started
    out.mkdir()
    import numpy as np
    capture = out / "retained-scores.npz"
    np.savez(capture, pairs=np.array([r[:2] for r in test], dtype=np.int64), scores=scores)
    original_capture_hash = digest(capture)
    predictions = {name: out / (name + ".csv") for name in ("bias", "factors", "rounded", "recovered")}
    write_predictions(predictions["bias"], test, scores[0])
    write_predictions(predictions["factors"], test, scores[1])
    write_predictions(predictions["rounded"], test, scores[1], rounded=True)
    with np.load(capture, allow_pickle=False) as retained:
        require(np.array_equal(retained["pairs"], np.array([r[:2] for r in test])),
                "recovery: captured pair order differs")
        require(np.array_equal(retained["scores"], scores), "recovery: captured score values differ")
        write_predictions(predictions["recovered"], test, retained["scores"][1])
    require(predictions["factors"].read_bytes() == predictions["recovered"].read_bytes(),
            "recovery: fresh export differs from original score-bearing CSV")
    manual = recover(capture, out / "manual-recovery")
    require(manual["csv_sha256"] == digest(predictions["factors"]),
            "recovery: separate recovery action differs from original factor export")
    qrels_path = out / "observed-judgments.csv"
    with qrels_path.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(("query_id", "item_id", "relevance"))
        writer.writerows((f"ml100k-u1-user:{u}", str(i), int(r >= 4)) for u, i, r, _ in test)
    originals = {path.name: digest(path) for path in [capture, qrels_path, *predictions.values()]}
    model_report = cli_report(out, "models", ["compare", "--run", f"bias={predictions['bias']}",
        "--run", f"factors={predictions['factors']}", "--qrels", str(qrels_path)])
    no_labels = cli_report(out, "scores-only", ["audit", str(predictions["factors"])])
    rounding = cli_report(out, "rounding", ["compare", "--run", f"exact={predictions['factors']}",
        "--run", f"rounded={predictions['rounded']}", "--qrels", str(qrels_path)])
    recovery = cli_report(out, "recovery", ["compare", "--run", f"exact={predictions['factors']}",
        "--run", f"recovered={predictions['recovered']}", "--qrels", str(qrels_path)])
    qrels = read_qrels(qrels_path)
    model_audits = {name: model_report["runs"][name]["audit"] for name in ("bias", "factors")}
    model_audits["rounded"] = rounding["runs"]["rounded"]["audit"]
    model_audits["recovered"] = recovery["runs"]["recovered"]["audit"]
    score_views = {"bias": scores[0], "factors": scores[1],
                   "rounded": [float(format(float(v), ".1f")) for v in scores[1]],
                   "recovered": scores[1]}
    macros, comparisons = {}, 0
    for name, audit in model_audits.items():
        macros[name], count = verify_metrics(predictions[name], test, score_views[name], qrels, audit["metrics"])
        comparisons += count
        require(audit["summary"]["unknown_candidates"] == 0
                and audit["summary"]["assumed_nonrelevant_candidates"] == 0,
                "labels: observed judgments changed")
        require(all(v["value"] is None for k, v in audit["metrics"].items() if k.startswith("recall")),
                "labels: complete-corpus Recall was inferred")
    deltas = {}
    for name, report, left, right in [("models", model_report, "bias", "factors"),
                                      ("rounding", rounding, "factors", "rounded"),
                                      ("recovery", recovery, "factors", "recovered")]:
        pair = report["pairs"][0]
        require(pair["status"] == "comparable" and pair["candidate_sets"]["differing_queries"] == 0,
                "pair: original common candidates or labels differ")
        require(pair["matched_pool_comparison"]["query_count"] == len(qrels),
                "pair: matched query population differs")
        deltas[name] = {}
        for key in macros[left]:
            delta = pair["matched_pool_comparison"]["delta_right_minus_left"][key]["delta"]
            expected = macros[right][key] - macros[left][key]
            require(delta is not None and math.isclose(delta, expected, rel_tol=0, abs_tol=1e-12),
                    "pair: matched delta differs from independent formula")
            deltas[name][key] = delta
            comparisons += 1
    require(no_labels["summary"]["unknown_candidates"] == len(test)
            and no_labels["summary"]["assumed_nonrelevant_candidates"] == 0
            and all(v["value"] is None for v in no_labels["metrics"].values()),
            "labels: scores-only control supplied missing judgments")
    ties = {name: audit["tie_analysis"]["tie_groups"] for name, audit in model_audits.items()}
    require(ties["rounded"] > ties["factors"], "rounding: stated one-decimal control did not add tie groups")
    require(macros["recovered"] == macros["factors"] and digest(capture) == original_capture_hash,
            "recovery: scores or source capture changed")
    require(all(digest(out / name) == value for name, value in originals.items()),
            "source: retained input/export bytes changed")
    require(digest(archive) == ARCHIVE_SHA256, "source: original archive changed")
    summary = {"status": "passed", "source_archive_sha256": ARCHIVE_SHA256,
        "source_members_sha256": SOURCES, "train_rows": len(train), "evaluation_rows": len(test),
        "evaluation_queries": len(qrels), "observed_positive_labels": sum(r[2] >= 4 for r in test),
        "candidate_scope": "all held-out observed pairs, not full catalog retrieval",
        "binary_label_rule": "actual held-out rating >=4 -> 1; observed 1..3 -> 0",
        "model": model, "protocol": model_report["protocol"], "macro_metrics": macros,
        "matched_deltas": deltas, "tie_groups": ties, "independent_numeric_comparisons": comparisons,
        "scores_only_unknown": len(test), "scores_only_metrics_unavailable": True,
        "assumed_nonrelevant_candidates": 0, "recovery_csv_byte_identical": True,
        "manual_recovery_csv_byte_identical": True,
        "archive_capture_and_exports_unchanged": True, "local_file_sha256": originals,
        "python": platform.python_version(), "machine_fit_seconds": fit_seconds,
        "evidence_scope": "public real ratings and newly fitted NumPy models; deliberately rounded export control",
        "human_trial_and_active_time": "not measured", "model_quality_or_significance": "not established",
        "data_policy": "research use; raw data and row-level outputs not redistributed",
        "historical_lost_scores": "cannot recover without retained score evidence"}
    (out / "summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--archive", type=Path, help="existing fixed official ZIP, read-only")
    source.add_argument("--fetch", type=Path, help="explicitly download fixed ZIP to a new file")
    source.add_argument("--recover", type=Path, help="re-export this case's retained NPZ; no fetch or fit")
    parser.add_argument("--out", type=Path, required=True, help="new directory; row-level files stay local")
    args = parser.parse_args()
    try:
        new_output(args.out)
        if args.recover:
            result = recover(args.recover, args.out)
        else:
            if args.fetch:
                fetch_archive(args.fetch)
            result = check(args.archive or args.fetch, args.out)
    except (ValueError, OSError, KeyError, BadZipFile, EOFError, subprocess.TimeoutExpired) as exc:
        reason = str(exc) if isinstance(exc, GateError) else type(exc).__name__
        print(json.dumps({"status": "failed", "reason": reason}), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
