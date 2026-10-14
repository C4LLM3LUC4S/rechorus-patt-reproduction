from __future__ import annotations

import csv
import importlib.util
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "export_rechorus.py"
SPEC = importlib.util.spec_from_file_location("export_rechorus", SCRIPT)
exporter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(exporter)


def write_npz(tmp_path, **arrays):
    source = tmp_path / "predictions.npz"
    np.savez(source, **arrays)
    return source


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
