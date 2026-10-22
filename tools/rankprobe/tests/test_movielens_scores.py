from __future__ import annotations

import hashlib
import importlib.util
from io import BytesIO
import csv
import json
import math
from pathlib import Path
import sys

import pytest

np = pytest.importorskip("numpy")
SCRIPT = Path(__file__).resolve().parents[1] / "scripts/check_movielens_scores.py"
SPEC = importlib.util.spec_from_file_location("check_movielens_scores", SCRIPT)
case = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(case)


@pytest.mark.parametrize("content", [b"", b"1 2 3\n", b"1 2 x 4\n", b"0 2 3 4\n",
                                     b"1 2 0 4\n", b"1 2 3 0\n", b"1 2 3 4\n1 2 5 6\n"])
def test_invalid_or_repeated_observed_ratings_are_not_repaired(content):
    with pytest.raises(case.GateError, match="ratings:"):
        case.parse_ratings(content)


def test_existing_output_is_preserved_before_source_read(tmp_path):
    out = tmp_path / "existing"
    out.mkdir()
    sentinel = out / "keep.txt"
    sentinel.write_bytes(b"original output")
    with pytest.raises(case.GateError, match="new directory"):
        case.check(tmp_path / "absent.zip", out)
    assert sentinel.read_bytes() == b"original output"


def test_wrong_archive_is_rejected_without_output_or_source_changes(tmp_path):
    archive = tmp_path / "not-fixed.zip"
    archive.write_bytes(b"original invalid input")
    out = tmp_path / "new"
    with pytest.raises(case.GateError, match="fixed source"):
        case.check(archive, out)
    assert archive.read_bytes() == b"original invalid input"
    assert not out.exists()


def test_fetch_hash_mismatch_leaves_no_archive(tmp_path, monkeypatch):
    monkeypatch.setattr(case, "ARCHIVE_BYTES", 3)
    monkeypatch.setattr(case, "ARCHIVE_SHA256", hashlib.sha256(b"yes").hexdigest())
    monkeypatch.setattr(case, "urlopen", lambda *_args, **_kwargs: BytesIO(b"bad"))
    out = tmp_path / "new.zip"
    with pytest.raises(case.GateError, match="fixed source"):
        case.fetch_archive(out)
    assert not out.exists()


def test_cli_existing_output_does_not_download(tmp_path, monkeypatch, capsys):
    out = tmp_path / "existing"
    out.mkdir()
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "--fetch", str(tmp_path / "new.zip"), "--out", str(out)])
    monkeypatch.setattr(case, "urlopen", lambda *_args, **_kwargs: pytest.fail("unexpected download"))
    assert case.main() == 2
    error = json.loads(capsys.readouterr().err)
    assert error["status"] == "failed" and "new directory" in error["reason"]
    assert not (tmp_path / "new.zip").exists()


def test_fit_is_independent_of_unrelated_evaluation_ids_and_preserves_training():
    train = [(1, 1, 5, 1), (1, 2, 2, 2), (2, 1, 3, 3), (2, 2, 4, 4)]
    original = list(train)
    pairs = [(1, 2), (2, 1)]
    baseline, metadata = case.fitted_scores(train, pairs)
    extended, _ = case.fitted_scores(train, [*pairs, (100, 100)])
    np.testing.assert_array_equal(baseline, extended[:, :2])
    assert extended[0, 2] == extended[1, 2] == 3.5
    assert train == original and metadata["missing_ratings_added"] == 0
    assert metadata["test_rating_access"] is False


def test_independent_formula_uses_lexical_ties_and_counts_known_zero_ideal():
    records = [(1, 2, 5, 1), (1, 10, 1, 2), (2, 1, 2, 3)]
    per_query, macro = case.independent_metrics(records, [1, 1, 0])
    assert per_query["ml100k-u1-user:1"]["mrr@1"] == 0
    assert per_query["ml100k-u1-user:1"]["mrr@5"] == 0.5
    assert per_query["ml100k-u1-user:2"]["ndcg@5"] == 0
    assert macro["mrr@5"] == 0.25
    assert math.isclose(macro["ndcg@5"], 0.5 / math.log2(3), abs_tol=1e-15)


def test_independent_check_rejects_a_well_formed_constant_zero_engine(tmp_path, monkeypatch):
    records = [(1, 1, 5, 1)]
    path = tmp_path / "scores.csv"
    case.write_predictions(path, records, [0.8])
    fake = {f"{metric}@{cutoff}": {"value": 0.0, "evaluated_queries": 1}
            for cutoff in case.CUTOFFS for metric in ("mrr", "ndcg")}
    monkeypatch.setattr(case, "evaluate_metrics", lambda *_args: fake)
    with pytest.raises(case.GateError, match="per-query"):
        case.verify_metrics(path, records, [0.8], {"ml100k-u1-user:1": {"1": 1}}, fake)


def test_original_miniature_exercises_cli_recovery_and_unknown_controls(tmp_path, monkeypatch):
    train = [(1, 1, 3, 1), (1, 2, 3, 2), (2, 3, 3, 3), (2, 4, 3, 4),
             (3, 1, 3, 5), (3, 3, 3, 6)]
    test = [(1, 3, 5, 7), (1, 4, 1, 8), (2, 1, 1, 9), (2, 2, 4, 10),
            (3, 2, 2, 11), (3, 4, 5, 12)]
    archive = tmp_path / "original-synthetic.bin"
    archive.write_bytes(b"original synthetic unit input")
    source_hash = case.digest(archive)
    monkeypatch.setattr(case, "verified_inputs", lambda _path: (train, test))
    monkeypatch.setattr(case, "ARCHIVE_SHA256", source_hash)
    out = tmp_path / "unit outputs"
    result = case.check(archive, out)
    assert result["status"] == "passed" and result["evaluation_rows"] == 6
    assert result["scores_only_unknown"] == 6
    assert result["tie_groups"]["rounded"] > result["tie_groups"]["factors"]
    assert result["recovery_csv_byte_identical"]
    assert result["manual_recovery_csv_byte_identical"]
    assert all(value == 0 for value in result["matched_deltas"]["recovery"].values())
    assert case.digest(archive) == source_hash


def test_manual_recovery_preserves_score_bits_order_and_unknown_labels(tmp_path, monkeypatch):
    capture = tmp_path / "retained.npz"
    pairs = np.array([[2, 10], [1, 3], [2, 2]], dtype=np.int64)
    scores = np.array([[3, 4, 5], [np.nextafter(1.0, 2.0), np.nextafter(1.0, 0.0), -0.0]])
    np.savez(capture, pairs=pairs, scores=scores)
    before = capture.read_bytes()
    monkeypatch.setattr(case, "fitted_scores", lambda *_a: pytest.fail("unexpected fit"))
    monkeypatch.setattr(case, "fetch_archive", lambda *_a: pytest.fail("unexpected download"))
    out = tmp_path / "manual action"
    receipt = case.recover(capture, out)
    with (out / "recovered.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert [(r["query_id"], r["item_id"]) for r in rows] == [
        ("ml100k-u1-user:2", "10"), ("ml100k-u1-user:1", "3"), ("ml100k-u1-user:2", "2")]
    actual = np.array([float(r["score"]) for r in rows])
    assert actual.tobytes() == scores[1].tobytes()
    assert set(rows[0]) == {"query_id", "item_id", "score"}
    assert capture.read_bytes() == before
    assert receipt["rows"] == 3 and receipt["queries"] == 2
    assert receipt["judgments_read_or_added"] == 0 and receipt["refitted"] is False
    assert receipt["capture_sha256"] == hashlib.sha256(before).hexdigest()
    assert receipt["csv_sha256"] == case.digest(out / "recovered.csv")
    assert json.loads((out / "recovery.json").read_text(encoding="utf-8")) == receipt
    report = case.cli_report(tmp_path, "no-judgments", ["audit", str(out / "recovered.csv")])
    assert report["summary"]["unknown_candidates"] == 3
    assert report["summary"]["assumed_nonrelevant_candidates"] == 0
    assert all(v["value"] is None for v in report["metrics"].values())


@pytest.mark.parametrize("kind", ["empty", "pair-shape", "pair-float", "pair-zero",
                                 "duplicate", "score-shape", "float32", "integer-scores",
                                 "nonfinite", "object", "extra-key", "missing-key", "npy", "broken"])
def test_manual_recovery_rejects_bad_capture_without_output(tmp_path, kind):
    capture = tmp_path / "retained.npz"
    payload = {"pairs": np.array([[1, 2], [1, 3]], dtype=np.int64),
               "scores": np.array([[1., 2.], [3., 4.]])}
    if kind == "empty":
        payload = {"pairs": np.empty((0, 2), dtype=np.int64), "scores": np.empty((2, 0))}
    elif kind == "pair-shape":
        payload["pairs"] = np.array([1, 2])
    elif kind == "pair-float":
        payload["pairs"] = payload["pairs"].astype(float)
    elif kind == "pair-zero":
        payload["pairs"][0, 0] = 0
    elif kind == "duplicate":
        payload["pairs"][1] = payload["pairs"][0]
    elif kind == "score-shape":
        payload["scores"] = np.ones((2, 3))
    elif kind == "float32":
        payload["scores"] = payload["scores"].astype(np.float32)
    elif kind == "integer-scores":
        payload["scores"] = payload["scores"].astype(np.int64)
    elif kind == "nonfinite":
        payload["scores"][1, 0] = np.nan
    elif kind == "object":
        payload["pairs"] = payload["pairs"].astype(object)
    elif kind == "extra-key":
        payload["unrelated"] = np.array([1])
    elif kind == "missing-key":
        del payload["scores"]
    with capture.open("xb") as handle:
        if kind == "npy":
            np.save(handle, np.ones((2, 2)))
        elif kind == "broken":
            handle.write(b"not a score capture")
        else:
            np.savez(handle, **payload)
    before = capture.read_bytes()
    out = tmp_path / "new"
    with pytest.raises(case.GateError, match="recovery:"):
        case.recover(capture, out)
    assert not out.exists() and capture.read_bytes() == before


def test_manual_recovery_cli_refuses_existing_output_then_succeeds_fresh(tmp_path, monkeypatch, capsys):
    out = tmp_path / "keep"
    out.mkdir()
    sentinel = out / "original.txt"
    sentinel.write_bytes(b"preserve previous attempt")
    capture = tmp_path / "absent.npz"
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "--recover", str(capture), "--out", str(out)])
    assert case.main() == 2
    assert "new directory" in json.loads(capsys.readouterr().err)["reason"]
    assert sentinel.read_bytes() == b"preserve previous attempt"
    np.savez(capture, pairs=np.array([[1, 2]]), scores=np.array([[1.], [1.23456789012345]]))
    fresh = tmp_path / "fresh"
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "--recover", str(capture), "--out", str(fresh)])
    monkeypatch.setattr(case, "verified_inputs", lambda *_a: pytest.fail("unexpected rating read"))
    monkeypatch.setattr(case, "fitted_scores", lambda *_a: pytest.fail("unexpected fit"))
    monkeypatch.setattr(case, "fetch_archive", lambda *_a: pytest.fail("unexpected download"))
    assert case.main() == 0
    assert json.loads(capsys.readouterr().out)["rows"] == 1
    assert (fresh / "recovered.csv").is_file()
    assert sentinel.read_bytes() == b"preserve previous attempt"
