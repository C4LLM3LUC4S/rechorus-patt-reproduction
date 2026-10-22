from __future__ import annotations

from io import BytesIO
import csv
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile

import pytest

from rankprobe import Protocol, audit_run, compare_runs
from rankprobe.io import read_predictions

np = pytest.importorskip("numpy")
SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "export_rechorus.py"
SPEC = importlib.util.spec_from_file_location("export_rechorus", SCRIPT)
exporter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(exporter)


def write_npz(tmp_path, **arrays):
    source = tmp_path / "predictions.npz"
    np.savez(source, **arrays)
    return source


@pytest.mark.parametrize("identity", ["local", "source"])
def test_output_fingerprint_distinguishes_same_source_exports_and_edited_copy(tmp_path, identity):
    source = write_npz(
        tmp_path, scores=np.array([[9007199254740993, 9007199254740992]], dtype=np.int64),
        item_id=np.array([["positive", "other"]]), query_id=np.array(["event-1"]),
    )
    source_bytes = source.read_bytes()
    outputs = [tmp_path / "first.csv", tmp_path / "second.csv"]
    metadata = [exporter.export_npz(source, out, positive_index=index, identity=identity)
                for index, out in enumerate(outputs)]
    original_outputs = [out.read_bytes() for out in outputs]
    assert metadata[0]["source_sha256"] == metadata[1]["source_sha256"]
    assert metadata[0]["exported_rows"] == metadata[1]["exported_rows"] == 2
    assert metadata[0]["predictions_sha256"] != metadata[1]["predictions_sha256"]
    for index, out in enumerate(outputs):
        assert metadata[index]["predictions_sha256"] == hashlib.sha256(out.read_bytes()).hexdigest()
        assert json.loads(out.with_suffix(".csv.metadata.json").read_text(encoding="utf-8")) == metadata[index]
        rows = read_predictions(out)
        assert [row.score for row in rows] == [9007199254740993, 9007199254740992]
        assert [row.relevance for row in rows] == ([1, None] if index == 0 else [None, 1])
        assert metadata[index]["other_candidates"] == "unknown"
        assert not metadata[index]["qrels_complete"]

    copied = tmp_path / "edited-copy.csv"
    copied.write_bytes(original_outputs[0].replace(b",9007199254740993,", b",9007199254740994,", 1))
    assert hashlib.sha256(copied.read_bytes()).hexdigest() != metadata[0]["predictions_sha256"]
    assert [out.read_bytes() for out in outputs] == original_outputs
    assert source.read_bytes() == source_bytes


def test_cli_output_fingerprint_matches_saved_sidecar_and_exact_csv(tmp_path):
    source = write_npz(
        tmp_path, scores=np.array([[9007199254740993, 9007199254740992]], dtype=np.int64),
        item_id=np.array([["positive", "other"]]), query_id=np.array(["event-1"]),
    )
    original = source.read_bytes()
    out = tmp_path / "cli.csv"
    process = subprocess.run(
        [sys.executable, str(SCRIPT), str(source), "--out", str(out), "--positive-index", "0",
         "--identity", "source"], capture_output=True, text=True, encoding="utf-8", timeout=30,
    )
    assert process.returncode == 0 and process.stderr == ""
    metadata = json.loads(process.stdout)
    assert metadata == json.loads(out.with_suffix(".csv.metadata.json").read_text(encoding="utf-8"))
    assert metadata["source_sha256"] == hashlib.sha256(original).hexdigest()
    assert metadata["predictions_sha256"] == hashlib.sha256(out.read_bytes()).hexdigest()
    rows = read_predictions(out)
    assert [(row.query_id, row.item_id, row.score, row.relevance) for row in rows] == [
        ("event-1", "positive", 9007199254740993, 1),
        ("event-1", "other", 9007199254740992, None),
    ]
    assert source.read_bytes() == original


@pytest.mark.parametrize("suffix", [".npy", ".npz"])
def test_single_array_has_format_guidance_and_named_capture_can_retry(tmp_path, suffix):
    source = tmp_path / ("single-array" + suffix)
    with source.open("xb") as handle:
        np.save(handle, np.array([[0.75, 0.25]]), allow_pickle=False)
    original = source.read_bytes()
    out = tmp_path / "new-export" / "scores.csv"
    with pytest.raises(ValueError, match="NPZ.*scores.*item_id"):
        exporter.export_npz(source, out, positive_index=0)
    assert not out.parent.exists()
    process = subprocess.run(
        [sys.executable, str(SCRIPT), str(source), "--out", str(out), "--positive-index", "0"],
        capture_output=True, text=True, encoding="utf-8", timeout=30,
    )
    assert process.returncode == 2 and process.stdout == ""
    assert "NPY" in process.stderr and "numpy.savez" in process.stderr
    assert "scores" in process.stderr and "item_id" in process.stderr
    assert "original unchanged" in process.stderr and "Traceback" not in process.stderr
    assert not out.parent.exists()
    assert source.read_bytes() == original

    named = tmp_path / "complete-named-capture.npz"
    np.savez(named, scores=np.array([[0.75, 0.25]]), item_id=np.array([["positive", "other"]]))
    complete = named.read_bytes()
    metadata = exporter.export_npz(named, out, positive_index=0)
    rows = read_predictions(out)
    assert [row.score for row in rows] == [0.75, 0.25]
    assert [row.relevance for row in rows] == [1, None]
    assert metadata["other_candidates"] == "unknown" and not metadata["qrels_complete"]
    assert source.read_bytes() == original and named.read_bytes() == complete


def test_named_archive_content_is_accepted_with_npy_suffix(tmp_path):
    source = tmp_path / "named-archive.npy"
    with source.open("xb") as handle:
        np.savez(handle, scores=np.array([[0.75, 0.25]]),
                 item_id=np.array([["positive", "other"]]), query_id=np.array(["event-1"]))
    original = source.read_bytes()
    out = tmp_path / "scores.csv"
    exporter.export_npz(source, out, positive_index=0, identity="source")
    rows = read_predictions(out)
    assert [(row.query_id, row.item_id, row.score, row.relevance) for row in rows] == [
        ("event-1", "positive", 0.75, 1), ("event-1", "other", 0.25, None),
    ]
    assert source.read_bytes() == original


def damage_npz(source, kind):
    original = source.read_bytes()
    if kind == "empty":
        damaged = b""
    elif kind == "truncated":
        damaged = original[:-30]
    else:
        with zipfile.ZipFile(BytesIO(original)) as archive:
            entry = archive.getinfo("scores.npy")
        assert entry.compress_type == zipfile.ZIP_STORED
        header = entry.header_offset
        name_size = int.from_bytes(original[header + 26:header + 28], "little")
        extra_size = int.from_bytes(original[header + 28:header + 30], "little")
        offset = header + 30 + name_size + extra_size + entry.compress_size - 1
        damaged = bytearray(original)
        damaged[offset] ^= 1
    source.write_bytes(damaged)
    return bytes(damaged)


@pytest.mark.parametrize("values,dtype", [
    ([9007199254740993, 9007199254740992], np.int64),
    ([0.625, 0.125], np.float64),
])
def test_complete_compressed_npz_preserves_scores_ids_and_unknown_labels(tmp_path, values, dtype):
    source = tmp_path / "compressed-capture.npz"
    np.savez_compressed(
        source, scores=np.array([values], dtype=dtype),
        item_id=np.array([["z-positive", "a-other"]]), query_id=np.array(["event-1"]),
    )
    original = source.read_bytes()
    out = tmp_path / "scores.csv"
    metadata = exporter.export_npz(source, out, positive_index=0, identity="source")
    rows = read_predictions(out)
    assert [(row.query_id, row.item_id) for row in rows] == [
        ("event-1", "z-positive"), ("event-1", "a-other"),
    ]
    assert [row.score for row in rows] == values
    assert [row.relevance for row in rows] == [1, None]
    report = audit_run(rows, protocol=Protocol(cutoffs=(1,)))
    assert report["tie_analysis"]["tie_groups"] == 0
    assert report["metrics"]["mrr@1"]["value"] == 1
    assert report["summary"]["unknown_candidates"] == 1
    assert report["summary"]["assumed_nonrelevant_candidates"] == 0
    assert metadata["qrels_complete"] is False
    assert source.read_bytes() == original


@pytest.mark.parametrize("member", ["scores.npy", "item_id.npy", "query_id.npy"])
def test_bad_deflate_npz_has_input_error_and_allows_fresh_capture(tmp_path, member):
    source = tmp_path / "damaged-capture.npz"
    values = [9007199254740993, 9007199254740992]
    np.savez_compressed(
        source, scores=np.array([values], dtype=np.int64),
        item_id=np.array([["z-positive", "a-other"]]), query_id=np.array(["event-1"]),
    )
    complete = source.read_bytes()
    with zipfile.ZipFile(source) as archive:
        entry = archive.getinfo(member)
    assert entry.compress_type == zipfile.ZIP_DEFLATED
    header = entry.header_offset
    name_size = int.from_bytes(complete[header + 26:header + 28], "little")
    extra_size = int.from_bytes(complete[header + 28:header + 30], "little")
    offset = header + 30 + name_size + extra_size
    damaged = bytearray(complete)
    damaged[offset] = (damaged[offset] & 0xf8) | 0x07  # Reserved DEFLATE block type.
    source.write_bytes(damaged)
    out = tmp_path / "new-export" / "scores.csv"
    with pytest.raises(ValueError, match="NPZ archive.*new NPZ"):
        exporter.export_npz(source, out, positive_index=0, identity="source")
    assert source.read_bytes() == damaged
    assert not out.parent.exists()

    def run(capture):
        return subprocess.run(
            [sys.executable, str(SCRIPT), str(capture), "--out", str(out),
             "--positive-index", "0", "--identity", "source"],
            capture_output=True, text=True, encoding="utf-8", timeout=30,
        )

    failed = run(source)
    assert failed.returncode == 2
    assert failed.stdout == ""
    assert "Export error: NPZ archive" in failed.stderr
    assert "original unchanged" in failed.stderr and "new NPZ" in failed.stderr
    assert "Traceback" not in failed.stderr
    assert not out.parent.exists()
    new_source = tmp_path / "complete-new-capture.npz"
    new_source.write_bytes(complete)
    retried = run(new_source)
    assert retried.returncode == 0, retried.stderr
    assert json.loads(retried.stdout)["other_candidates"] == "unknown"
    rows = read_predictions(out)
    assert [row.score for row in rows] == values
    assert [(row.query_id, row.item_id) for row in rows] == [
        ("event-1", "z-positive"), ("event-1", "a-other"),
    ]
    assert [row.relevance for row in rows] == [1, None]
    assert source.read_bytes() == damaged
    assert new_source.read_bytes() == complete


@pytest.mark.parametrize("kind", ["empty", "truncated", "bad-checksum"])
def test_unreadable_npz_rejected_before_output_and_fresh_capture_can_retry(tmp_path, kind):
    source = write_npz(
        tmp_path, scores=np.array([[0.9, 0.2]]), item_id=np.array([["positive", "other"]]),
    )
    original = source.read_bytes()
    damaged = damage_npz(source, kind)
    out = tmp_path / "new-export" / "scores.csv"
    with pytest.raises(ValueError, match="NPZ archive.*new NPZ"):
        exporter.export_npz(source, out, positive_index=0)
    assert source.read_bytes() == damaged
    assert not out.parent.exists()

    new_capture = tmp_path / "complete-capture.npz"
    new_capture.write_bytes(original)
    metadata = exporter.export_npz(new_capture, out, positive_index=0)
    rows = read_predictions(out)
    assert [row.score for row in rows] == [0.9, 0.2]
    assert [row.relevance for row in rows] == [1, None]
    assert metadata["other_candidates"] == "unknown"
    assert metadata["qrels_complete"] is False
    assert source.read_bytes() == damaged
    assert new_capture.read_bytes() == original


@pytest.mark.parametrize("kind", ["empty", "truncated", "bad-checksum"])
def test_unreadable_npz_cli_has_bounded_error_and_allows_fresh_capture(tmp_path, kind):
    source = write_npz(
        tmp_path, scores=np.array([[0.9, 0.2]]), item_id=np.array([["positive", "other"]]),
    )
    original = source.read_bytes()
    damaged = damage_npz(source, kind)
    out = tmp_path / "new-export" / "scores.csv"

    def run(capture):
        return subprocess.run(
            [sys.executable, str(SCRIPT), str(capture), "--out", str(out),
             "--positive-index", "0"],
            capture_output=True, text=True, encoding="utf-8", timeout=30,
        )

    failed = run(source)
    assert failed.returncode == 2
    assert failed.stdout == ""
    assert "Export error: NPZ archive" in failed.stderr
    assert "new NPZ" in failed.stderr and "original unchanged" in failed.stderr
    assert "Traceback" not in failed.stderr
    assert not out.parent.exists()
    assert source.read_bytes() == damaged

    new_capture = tmp_path / "complete-capture.npz"
    new_capture.write_bytes(original)
    retried = run(new_capture)
    assert retried.returncode == 0, retried.stderr
    metadata = json.loads(retried.stdout)
    assert metadata["exported_rows"] == 2 and metadata["other_candidates"] == "unknown"
    rows = read_predictions(out)
    report = audit_run(rows, protocol=Protocol(cutoffs=(1,)))
    assert report["summary"]["unknown_candidates"] == 1
    assert report["summary"]["assumed_nonrelevant_candidates"] == 0
    assert report["metrics"]["mrr@1"]["value"] == 1
    assert source.read_bytes() == damaged
    assert new_capture.read_bytes() == original


def test_queries_are_events_not_users_and_ids_are_remapped(tmp_path):
    source = write_npz(
        tmp_path,
        scores=np.array([[0.9, 0.2], [0.8, 0.1]]),
        item_id=np.array([[987654321, 345678912], [345678912, 987654321]]),
        user_id=np.array([123456789, 123456789]),
    )
    before = source.read_bytes()
    out = tmp_path / "export.csv"
    metadata = exporter.export_npz(source, out, positive_index=0)
    rows = list(csv.DictReader(out.open(encoding="utf-8")))
    assert [row["query_id"] for row in rows] == [
        "query_000001",
        "query_000001",
        "query_000002",
        "query_000002",
    ]
    assert rows[1]["relevance"] == ""
    assert rows[0]["item_id"] == rows[3]["item_id"]
    assert "123456789" not in out.read_text(encoding="utf-8")
    assert "987654321" not in out.read_text(encoding="utf-8")
    assert metadata["qrels_complete"] is False
    assert source.read_bytes() == before


def test_explicit_negative_assumption_and_limit(tmp_path):
    source = write_npz(
        tmp_path,
        scores=np.array([[0.1, 0.9], [0.8, 0.2]]),
        item_id=np.array([[10, 20], [30, 40]]),
    )
    out = tmp_path / "export.csv"
    metadata = exporter.export_npz(
        source, out, positive_index=1, other_candidates="nonrelevant", limit_queries=1
    )
    rows = list(csv.DictReader(out.open(encoding="utf-8")))
    assert [row["relevance"] for row in rows] == ["0", "1"]
    assert metadata["source_queries"] == 2
    assert metadata["exported_queries"] == 1


@pytest.mark.parametrize("identity", ["local", "source"])
@pytest.mark.parametrize("dtype,values", [
    (np.int64, [9007199254740993, 9007199254740992]),
    (np.int64, [-9007199254740992, -9007199254740993]),
    (np.int64, [9223372036854775807, 9223372036854775806]),
    (np.uint64, [9223372036854775809, 9223372036854775808]),
    (np.uint64, [18446744073709551615, 18446744073709551614]),
])
def test_integer_scores_preserve_order_without_creating_ties(tmp_path, identity, dtype, values):
    source = write_npz(
        tmp_path, scores=np.array([values], dtype=dtype),
        item_id=np.array([["z-positive", "a-other"]]), query_id=np.array(["event-1"]),
    )
    before = source.read_bytes()
    out = tmp_path / "export.csv"
    metadata = exporter.export_npz(source, out, positive_index=0, identity=identity)
    with out.open(encoding="utf-8", newline="") as handle:
        exported = list(csv.DictReader(handle))
    assert [row["score"] for row in exported] == [str(value) for value in values]
    rows = read_predictions(out)
    assert [row.score for row in rows] == values
    assert all(type(row.score) is int for row in rows)
    assert [row.relevance for row in rows] == [1, None]
    report = audit_run(rows, protocol=Protocol(cutoffs=(1, 2)))
    assert report["tie_analysis"]["tie_groups"] == 0
    assert report["metrics"]["mrr@1"]["value"] == 1
    assert report["metrics"]["mrr@1"]["evaluated_queries"] == 1
    assert report["summary"]["unknown_candidates"] == 1
    assert report["summary"]["assumed_nonrelevant_candidates"] == 0
    assert metadata["other_candidates"] == "unknown"
    assert metadata["qrels_complete"] is False
    assert source.read_bytes() == before


@pytest.mark.parametrize("dtype", [np.float16, np.float32, np.float64])
def test_adjacent_float_scores_keep_their_values_and_order(tmp_path, dtype):
    values = np.array([[np.nextafter(dtype(0.5), dtype(1)), dtype(0.5)]], dtype=dtype)
    source = write_npz(tmp_path, scores=values, item_id=np.array([["z-positive", "a-other"]]))
    before = source.read_bytes()
    out = tmp_path / "export.csv"
    exporter.export_npz(source, out, positive_index=0)
    rows = read_predictions(out)
    assert [row.score for row in rows] == values[0].tolist()
    assert rows[0].score > rows[1].score
    assert source.read_bytes() == before


def test_large_integer_scores_survive_export_and_audit_commands(tmp_path):
    values = [18446744073709551615, 18446744073709551614]
    source = write_npz(
        tmp_path, scores=np.array([values], dtype=np.uint64),
        item_id=np.array([["z-positive", "a-other"]]), query_id=np.array(["event-1"]),
    )
    before = source.read_bytes()
    out = tmp_path / "export.csv"
    exported = subprocess.run(
        [sys.executable, str(SCRIPT), str(source), "--out", str(out),
         "--positive-index", "0", "--identity", "source"],
        capture_output=True, text=True, encoding="utf-8", timeout=30,
    )
    assert exported.returncode == 0, exported.stderr
    assert [row.score for row in read_predictions(out)] == values
    report_dir = tmp_path / "report"
    audited = subprocess.run(
        [sys.executable, "-m", "rankprobe", "audit", str(out), "--cutoffs", "1,2",
         "--out", str(report_dir)],
        capture_output=True, text=True, encoding="utf-8", timeout=30,
    )
    assert audited.returncode == 0, audited.stderr
    report = json.loads((report_dir / "report.json").read_text(encoding="utf-8"))
    assert (report_dir / "report.html").is_file()
    assert report["tie_analysis"]["tie_groups"] == 0
    assert report["metrics"]["mrr@1"]["value"] == 1
    assert report["summary"]["unknown_candidates"] == 1
    assert report["summary"]["assumed_nonrelevant_candidates"] == 0
    assert source.read_bytes() == before


@pytest.mark.parametrize(
    "scores,items",
    [
        (np.array([[float("nan"), 0.3]]), np.array([[1, 2]])),
        (np.array([0.2, 0.3]), np.array([1, 2])),
        (np.array([[0.2, 0.3]]), np.array([[1, 1]])),
    ],
)
def test_invalid_matrices_are_rejected_without_output(tmp_path, scores, items):
    source = write_npz(tmp_path, scores=scores, item_id=items)
    out = tmp_path / "export.csv"
    with pytest.raises(ValueError):
        exporter.export_npz(source, out, positive_index=0)
    assert not out.exists()


def test_cannot_overwrite_source_or_existing_output(tmp_path):
    source = write_npz(tmp_path, scores=np.array([[0.9, 0.2]]), item_id=np.array([[1, 2]]))
    with pytest.raises(ValueError, match="source NPZ"):
        exporter.export_npz(source, source, positive_index=0, overwrite=True)
    out = tmp_path / "export.csv"
    exporter.export_npz(source, out, positive_index=0)
    with pytest.raises(ValueError, match="already exists"):
        exporter.export_npz(source, out, positive_index=0)


def test_pickle_arrays_are_not_loaded(tmp_path):
    source = write_npz(
        tmp_path, scores=np.array([[0.9, 0.2]]), item_id=np.array([[{}, {}]], dtype=object)
    )
    with pytest.raises(ValueError):
        exporter.export_npz(source, tmp_path / "export.csv", positive_index=0)


def test_source_identity_exposes_different_physical_pools_hidden_by_local_names(tmp_path):
    exported = {"local": {}, "source": {}}
    for run, physical_items in (("left", ["A", "B", "C"]), ("right", ["A", "D", "E"])):
        source = tmp_path / f"{run}.npz"
        np.savez(source, scores=np.array([[3.0, 2.0, 1.0]]),
                 item_id=np.array([physical_items]), query_id=np.array(["shared-event"]))
        before = source.read_bytes()
        for mode in exported:
            out = tmp_path / f"{run}-{mode}.csv"
            metadata = exporter.export_npz(source, out, positive_index=0, identity=mode)
            assert metadata["identity_mode"] == mode
            exported[mode][run] = read_predictions(out)
        assert source.read_bytes() == before
    local_pair = compare_runs(exported["local"], Protocol(cutoffs=(1,)))["pairs"][0]
    # Local pseudonyms only establish equality inside their own export namespace.
    assert local_pair["matched_pool_comparison"]["query_count"] == 1
    assert local_pair["candidate_sets"]["differing_queries"] == 0
    source_pair = compare_runs(exported["source"], Protocol(cutoffs=(1,)))["pairs"][0]
    assert source_pair["matched_pool_comparison"]["query_count"] == 0
    assert source_pair["candidate_sets"]["differing_queries"] == 1
    assert source_pair["status"] == "not_comparable"


def test_stable_event_ids_align_reordered_context_rows(tmp_path):
    runs = {}
    for run, events, items in (
        ("left", ["event-a", "event-b"], [["A", "B"], ["C", "D"]]),
        ("right", ["event-b", "event-a"], [["C", "D"], ["A", "B"]]),
    ):
        source = tmp_path / f"{run}.npz"
        np.savez(source, scores=np.array([[2.0, 1.0], [2.0, 1.0]]),
                 item_id=np.array(items), query_id=np.array(events), user_id=np.array([7, 7]))
        out = tmp_path / f"{run}.csv"
        metadata = exporter.export_npz(source, out, positive_index=0, identity="source")
        runs[run] = read_predictions(out)
        assert [row.query_id for row in runs[run]][::2] == events
        assert metadata["user_ids_exported"] is None
        assert metadata["user_id_array_exported"] is False
        assert metadata["retained_source_ids"] is True
        assert metadata["qrels_complete"] is False
    pair = compare_runs(runs, Protocol(cutoffs=(1,)))["pairs"][0]
    assert pair["matched_pool_comparison"]["query_ids"] == ["event-a", "event-b"]
    assert pair["matched_pool_comparison"]["query_count"] == 2
    assert pair["status"] == "comparable"


def test_source_utf8_tokens_preserve_exact_whitespace_and_canonically_distinct_text(tmp_path):
    source = write_npz(
        tmp_path, scores=np.array([[1.0000000000000002, -0.0, -2.0]]),
        query_id=np.array([" 事件,甲\n ".encode()]),
        item_id=np.array([[" é ".encode(), "e\u0301".encode(), "é".encode()]]),
    )
    out = tmp_path / "export.csv"
    exporter.export_npz(source, out, positive_index=0, identity="source")
    rows = read_predictions(out)
    assert [row.item_id for row in rows] == [" é ", "e\u0301", "é"]
    assert {row.query_id for row in rows} == {" 事件,甲\n "}
    assert [row.score for row in rows] == [1.0000000000000002, -0.0, -2.0]
    assert [row.relevance for row in rows] == [1.0, None, None]


def test_large_integer_item_ids_are_never_converted_through_float(tmp_path):
    values = [2**63 + 1, 2**63 + 2]
    source = write_npz(
        tmp_path, scores=np.array([[0.9, 0.2]]),
        item_id=np.array([values], dtype=np.uint64), query_id=np.array(["event"]),
    )
    out = tmp_path / "export.csv"
    exporter.export_npz(source, out, positive_index=0, identity="source")
    assert [row.item_id for row in read_predictions(out)] == [str(value) for value in values]


def test_duplicate_nonpositive_items_remain_visible_to_audit(tmp_path):
    source = write_npz(
        tmp_path, scores=np.array([[3.0, 2.0, 1.0]]),
        item_id=np.array([["positive", "duplicate", "duplicate"]]), query_id=np.array(["event"]),
    )
    out = tmp_path / "export.csv"
    exporter.export_npz(source, out, positive_index=0, identity="source")
    rows = read_predictions(out)
    assert [row.item_id for row in rows] == ["positive", "duplicate", "duplicate"]
    assert [row.relevance for row in rows] == [1.0, None, None]
    report = audit_run(rows, Protocol(cutoffs=(1,)))
    assert "duplicate_candidates" in {finding["code"] for finding in report["findings"]}


@pytest.mark.parametrize("query_ids", [
    None, np.array(["same", "same"]), np.array(["event"]), np.array([["a", "b"]]),
    np.array([1, 2]), np.array(["", "event"]), np.array([" \t", "event"]),
    np.array([b"\xff", b"event"]), np.array(["\ud800", "event"]),
    np.array(["x" * 4097, "event"]),
])
def test_invalid_source_event_ids_fail_before_output_even_with_limit(tmp_path, query_ids):
    arrays = {"scores": np.array([[2.0, 1.0], [2.0, 1.0]]),
              "item_id": np.array([["A", "B"], ["C", "D"]])}
    if query_ids is not None:
        arrays["query_id"] = query_ids
    source = write_npz(tmp_path, **arrays)
    before = source.read_bytes()
    out = tmp_path / "export.csv"
    with pytest.raises(ValueError, match="query_id"):
        exporter.export_npz(source, out, positive_index=0, identity="source", limit_queries=1)
    assert not out.exists()
    assert not out.with_suffix(".csv.metadata.json").exists()
    assert source.read_bytes() == before


@pytest.mark.parametrize("items", [
    np.array([["A", ""]]), np.array([["A", " \t"]]), np.array([[b"A", b"\xff"]]),
    np.array([["A", "\ud800"]]), np.array([["A", "x" * 4097]]),
    np.array([[1.0, 2.0]]), np.array([["same", "same"]]),
])
def test_invalid_source_item_ids_or_repeated_positive_fail_before_output(tmp_path, items):
    source = write_npz(
        tmp_path, scores=np.array([[2.0, 1.0]]), item_id=items, query_id=np.array(["event"]),
    )
    out = tmp_path / "export.csv"
    with pytest.raises(ValueError):
        exporter.export_npz(source, out, positive_index=0, identity="source")
    assert not out.exists()


def test_source_mode_keeps_explicit_negative_assertion_and_prefix_selection(tmp_path):
    source = write_npz(
        tmp_path, scores=np.array([[1.0, 2.0], [1.0, 2.0]]),
        item_id=np.array([["A", "B"], ["C", "D"]]), query_id=np.array(["event-a", "event-b"]),
    )
    out = tmp_path / "export.csv"
    metadata = exporter.export_npz(source, out, positive_index=1, identity="source",
                                   other_candidates="nonrelevant", limit_queries=1)
    rows = read_predictions(out)
    assert [(row.query_id, row.item_id, row.relevance) for row in rows] == [
        ("event-a", "A", 0.0), ("event-a", "B", 1.0),
    ]
    assert metadata["source_queries"] == 2 and metadata["exported_queries"] == 1
    assert metadata["qrels_complete"] is False


@pytest.mark.parametrize("target", ["csv", "metadata"])
def test_hardlink_alias_cannot_overwrite_original_npz(tmp_path, target):
    source = write_npz(tmp_path, scores=np.array([[2.0, 1.0]]),
                       item_id=np.array([["A", "B"]]), query_id=np.array(["event"]))
    before = source.read_bytes()
    out = tmp_path / "export.csv"
    metadata = out.with_suffix(".csv.metadata.json")
    alias = out if target == "csv" else metadata
    try:
        os.link(source, alias)
    except OSError as exc:
        pytest.skip(f"hard links unavailable: {exc}")
    with pytest.raises(ValueError, match="source NPZ"):
        exporter.export_npz(source, out, positive_index=0, identity="source", overwrite=True)
    assert source.read_bytes() == alias.read_bytes() == before
    assert not (metadata if target == "csv" else out).exists()


def test_csv_and_metadata_hardlink_alias_is_rejected_before_either_write(tmp_path):
    source = write_npz(tmp_path, scores=np.array([[2.0, 1.0]]), item_id=np.array([["A", "B"]]))
    before = source.read_bytes()
    out = tmp_path / "export.csv"
    out.write_bytes(b"keep prior output\n")
    metadata = out.with_suffix(".csv.metadata.json")
    try:
        os.link(out, metadata)
    except OSError as exc:
        pytest.skip(f"hard links unavailable: {exc}")
    with pytest.raises(ValueError, match="same file"):
        exporter.export_npz(source, out, positive_index=0, overwrite=True)
    assert out.read_bytes() == metadata.read_bytes() == b"keep prior output\n"
    assert source.read_bytes() == before


def test_csv_and_metadata_symlink_alias_is_rejected_before_either_write(tmp_path):
    source = write_npz(tmp_path, scores=np.array([[2.0, 1.0]]), item_id=np.array([["A", "B"]]))
    out = tmp_path / "export.csv"
    metadata = out.with_suffix(".csv.metadata.json")
    metadata.write_bytes(b"keep prior output\n")
    try:
        out.symlink_to(metadata)
    except OSError as exc:
        pytest.skip(f"symbolic links unavailable: {exc}")
    with pytest.raises(ValueError, match="same file"):
        exporter.export_npz(source, out, positive_index=0, overwrite=True)
    assert out.read_bytes() == metadata.read_bytes() == b"keep prior output\n"


def test_source_identity_cli_flag_emits_loadable_rows_and_explicit_privacy_metadata(tmp_path):
    source = write_npz(tmp_path, scores=np.array([[2.0, 1.0]]),
                       item_id=np.array([["A", "B"]]), query_id=np.array(["event"]))
    out = tmp_path / "source.csv"
    process = subprocess.run(
        [sys.executable, str(SCRIPT), str(source), "--out", str(out),
         "--positive-index", "0", "--identity", "source"],
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert process.returncode == 0, process.stderr
    metadata = json.loads(process.stdout)
    assert metadata["identity_mode"] == "source"
    assert metadata["retained_source_ids"] is True
    assert metadata["user_ids_exported"] is None
    assert "may identify people" in metadata["privacy_note"]
    assert [(row.query_id, row.item_id) for row in read_predictions(out)] == [
        ("event", "A"), ("event", "B"),
    ]
