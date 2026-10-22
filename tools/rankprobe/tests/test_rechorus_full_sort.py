from __future__ import annotations

from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from rankprobe import Protocol, audit_run
from rankprobe.io import read_predictions

np = pytest.importorskip("numpy")
SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "export_rechorus_full_sort.py"
SPEC = importlib.util.spec_from_file_location("export_rechorus_full_sort", SCRIPT)
exporter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(exporter)


class Dataset:
    def __init__(self):
        self.phase = "test"
        self.model = SimpleNamespace(test_all=1)
        self.corpus = SimpleNamespace(
            n_items=7, n_users=9, train_clicked_set={7: {1}},
            residual_clicked_set={7: {3, 4, 5}},
        )
        self.data = {"user_id": [7, 7], "item_id": [3, 5]}
        self.rows = [{"user_id": 7, "item_id": np.array([target, 1, 2, 3, 4, 5, 6])}
                     for target in self.data["item_id"]]

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, index):
        return self.rows[index]


def fixture():
    return np.array([
        [.9, -np.inf, .5, -np.inf, -np.inf, -np.inf, .25],
        [.75, -np.inf, .5, -np.inf, -np.inf, -np.inf, .25],
    ]), Dataset(), ["event-0003", "event-0005"]


def test_full_sort_retains_positive_column_and_unknowns_with_actual_core_metrics(tmp_path):
    scores, dataset, events = fixture()
    before_scores, before_data = scores.copy(), deepcopy(dataset.data)
    before_rows = deepcopy(dataset.rows)
    before_train, before_residual = (deepcopy(dataset.corpus.train_clicked_set),
                                    deepcopy(dataset.corpus.residual_clicked_set))
    scores.setflags(write=False)
    out = tmp_path / "full sort export"
    metadata = exporter.export_full_sort(scores, dataset, events, out)
    rows = read_predictions(out / "predictions.csv")
    assert [(row.query_id, row.item_id, row.score, row.relevance) for row in rows] == [
        ("event-0003", "3", .9, 1.0), ("event-0003", "2", .5, None),
        ("event-0003", "6", .25, None), ("event-0005", "5", .75, 1.0),
        ("event-0005", "2", .5, None), ("event-0005", "6", .25, None),
    ]
    assert metadata["exported_rows"] == 6
    assert metadata["observed_positive_rows"] == 2 and metadata["unknown_rows"] == 4
    assert metadata["excluded_rows"] == 8
    assert metadata["exclusions_by_reason"] == {
        "train_clicked": 2, "residual_clicked": 6, "own_target_catalog_duplicate": 2,
    }
    assert metadata["queries"][0]["exclusions"][1] == {
        "column_index": 3, "item_id": "3",
        "reasons": ["residual_clicked", "own_target_catalog_duplicate"],
    }
    assert metadata["qrels_complete"] is False
    assert json.loads((out / "exclusions.json").read_text(encoding="utf-8")) == metadata
    assert hashlib.sha256((out / "predictions.csv").read_bytes()).hexdigest() == metadata["predictions_sha256"]
    assert str(tmp_path) not in (out / "exclusions.json").read_text(encoding="utf-8")
    report = audit_run(rows, Protocol(cutoffs=(1,)))
    assert report["summary"]["unknown_candidates"] == 4
    assert report["metrics"]["mrr@1"]["value"] == 1.0
    assert report["metrics"]["ndcg@1"]["value"] is None
    assert report["metrics"]["recall@1"]["value"] is None
    np.testing.assert_array_equal(scores, before_scores)
    assert dataset.data == before_data
    for row, original in zip(dataset.rows, before_rows):
        assert row["user_id"] == original["user_id"]
        np.testing.assert_array_equal(row["item_id"], original["item_id"])
    assert dataset.corpus.train_clicked_set == before_train
    assert dataset.corpus.residual_clicked_set == before_residual


def test_unknown_top_candidate_is_not_assumed_to_be_negative(tmp_path):
    scores, dataset, events = fixture()
    scores[:, 0] = .1
    exporter.export_full_sort(scores, dataset, events, tmp_path / "export")
    report = audit_run(read_predictions(tmp_path / "export" / "predictions.csv"),
                       Protocol(cutoffs=(1,)))
    assert report["metrics"]["mrr@1"]["value"] is None
    assert report["summary"]["unknown_candidates"] == 4


def test_overlapping_reasons_are_preserved_without_inflating_unique_exclusions(tmp_path):
    scores, dataset, events = fixture()
    dataset.corpus.train_clicked_set[7].add(3)
    metadata = exporter.export_full_sort(scores, dataset, events, tmp_path / "export")
    assert metadata["queries"][0]["exclusions"][1]["reasons"] == [
        "train_clicked", "residual_clicked", "own_target_catalog_duplicate",
    ]
    assert metadata["exclusions_by_reason"] == {
        "train_clicked": 4, "residual_clicked": 6, "own_target_catalog_duplicate": 2,
    }
    assert metadata["excluded_rows"] == 8


def test_all_catalog_items_masked_still_retains_each_observed_positive(tmp_path):
    scores, dataset, events = fixture()
    dataset.corpus.train_clicked_set[7] = set(range(1, 7))
    scores[:, 1:] = -np.inf
    metadata = exporter.export_full_sort(scores, dataset, events, tmp_path / "export")
    rows = read_predictions(tmp_path / "export" / "predictions.csv")
    assert [(row.query_id, row.item_id, row.relevance) for row in rows] == [
        ("event-0003", "3", 1.0), ("event-0005", "5", 1.0),
    ]
    assert metadata["unknown_rows"] == 0 and metadata["excluded_rows"] == 12


@pytest.mark.parametrize("bad_score", [np.nan, np.inf, -np.inf])
def test_positive_column_zero_is_never_treated_as_padding(tmp_path, bad_score):
    scores, dataset, events = fixture()
    scores[0, 0] = bad_score
    with pytest.raises(ValueError, match="Column zero observed positive score must be finite"):
        exporter.export_full_sort(scores, dataset, events, tmp_path / "export")
    assert not (tmp_path / "export").exists()


@pytest.mark.parametrize("bad_score", [np.nan, np.inf, -np.inf])
def test_eligible_nonfinite_scores_are_rejected_instead_of_silently_dropped(tmp_path, bad_score):
    scores, dataset, events = fixture()
    scores[1, 2] = bad_score
    with pytest.raises(ValueError, match="Eligible scores must be finite"):
        exporter.export_full_sort(scores, dataset, events, tmp_path / "export")
    assert not (tmp_path / "export").exists()


@pytest.mark.parametrize("column", [1, 3, 4, 5])
def test_each_native_catalog_mask_must_already_be_negative_infinity(tmp_path, column):
    scores, dataset, events = fixture()
    scores[0, column] = .7
    with pytest.raises(ValueError, match="Declared catalog masks must be -inf"):
        exporter.export_full_sort(scores, dataset, events, tmp_path / "export")
    assert not (tmp_path / "export").exists()


def test_missing_own_target_in_native_mask_is_rejected_not_added(tmp_path):
    scores, dataset, events = fixture()
    dataset.corpus.residual_clicked_set[7].remove(3)
    scores[:, 3] = .9
    with pytest.raises(ValueError, match="target catalog duplicate is absent"):
        exporter.export_full_sort(scores, dataset, events, tmp_path / "export")
    assert not (tmp_path / "export").exists()


@pytest.mark.parametrize("candidates", [
    [3, 0, 2, 3, 4, 5, 6], [5, 1, 2, 3, 4, 5, 6], [3, 1, 6, 3, 4, 5, 2],
    [3, 1, 2, 3, 4, 5], [3.0, 1, 2, 3, 4, 5, 6],
])
def test_wrong_candidate_layout_or_padding_rejected_before_write(tmp_path, candidates):
    scores, dataset, events = fixture()
    dataset.rows[0]["item_id"] = candidates
    with pytest.raises(ValueError):
        exporter.export_full_sort(scores, dataset, events, tmp_path / "export")
    assert not (tmp_path / "export").exists()


@pytest.mark.parametrize("phase,flag", [("train", 1), ("valid", 1), ("test", False),
                                       ("test", "1"), ("test", 2), ("test", 1.0)])
def test_unsupported_phase_or_full_sort_flag_rejected(tmp_path, phase, flag):
    scores, dataset, events = fixture()
    dataset.phase, dataset.model.test_all = phase, flag
    with pytest.raises(ValueError):
        exporter.export_full_sort(scores, dataset, events, tmp_path / "export")
    assert not (tmp_path / "export").exists()


def test_dev_and_true_flag_are_supported_without_merging_repeated_users(tmp_path):
    scores, dataset, events = fixture()
    dataset.phase, dataset.model.test_all = "dev", True
    metadata = exporter.export_full_sort(scores, dataset, events, tmp_path / "export")
    assert metadata["dataset_phase"] == "dev" and metadata["query_count"] == 2


def test_user_zero_is_valid_in_rechorus_native_user_namespace(tmp_path):
    scores, dataset, events = fixture()
    dataset.corpus.n_users = 1
    dataset.corpus.train_clicked_set = {0: {1}}
    dataset.corpus.residual_clicked_set = {0: {3, 4, 5}}
    dataset.data["user_id"] = [0, 0]
    for row in dataset.rows:
        row["user_id"] = 0
    metadata = exporter.export_full_sort(scores, dataset, events, tmp_path / "export")
    assert metadata["exported_rows"] == 6


@pytest.mark.parametrize("user", [-1, 9, True, 7.0])
def test_invalid_source_users_are_rejected(tmp_path, user):
    scores, dataset, events = fixture()
    dataset.data["user_id"][0] = user
    dataset.rows[0]["user_id"] = user
    with pytest.raises(ValueError, match="user_id"):
        exporter.export_full_sort(scores, dataset, events, tmp_path / "export")
    assert not (tmp_path / "export").exists()


@pytest.mark.parametrize("target", [0, 7, True, 3.0])
def test_invalid_source_targets_are_rejected(tmp_path, target):
    scores, dataset, events = fixture()
    dataset.data["item_id"][0] = target
    with pytest.raises(ValueError, match="target item_id"):
        exporter.export_full_sort(scores, dataset, events, tmp_path / "export")
    assert not (tmp_path / "export").exists()


@pytest.mark.parametrize("clicked", [{0}, {7}, {-1}, {True}, {1.0}, [1], None])
def test_invalid_clicked_sets_are_not_used_as_masks(tmp_path, clicked):
    scores, dataset, events = fixture()
    dataset.corpus.train_clicked_set[7] = clicked
    with pytest.raises(ValueError, match="train_clicked_set"):
        exporter.export_full_sort(scores, dataset, events, tmp_path / "export")
    assert not (tmp_path / "export").exists()


@pytest.mark.parametrize("events", [
    ["same", "same"], ["one"], [["one", "two"]], ["", "two"], ["one", " \t"],
    ["one", 2], [b"\xff", b"two"], ["\ud800", "two"], ["one", "x" * 4097],
])
def test_invalid_event_ids_are_rejected_before_any_output(tmp_path, events):
    scores, dataset, _ = fixture()
    with pytest.raises(ValueError, match="query_ids"):
        exporter.export_full_sort(scores, dataset, events, tmp_path / "export")
    assert not (tmp_path / "export").exists()


def test_event_tokens_and_adjacent_scores_round_trip_without_normalization(tmp_path):
    scores, dataset, _ = fixture()
    events = [" 事件,甲\n ".encode(), "e\u0301".encode()]
    scores[0, 0] = 1.0000000000000002
    scores[0, 2] = 1.0
    exporter.export_full_sort(scores, dataset, events, tmp_path / "export")
    rows = read_predictions(tmp_path / "export" / "predictions.csv")
    assert rows[0].query_id == " 事件,甲\n " and rows[3].query_id == "e\u0301"
    assert rows[0].score == 1.0000000000000002 and rows[1].score == 1.0


def test_additional_context_fields_and_misaligned_users_are_rejected(tmp_path):
    scores, dataset, events = fixture()
    dataset.rows[0]["history_items"] = np.array([1])
    with pytest.raises(ValueError, match="exactly user_id/item_id"):
        exporter.export_full_sort(scores, dataset, events, tmp_path / "export")
    del dataset.rows[0]["history_items"]
    dataset.rows[0]["user_id"] = 8
    with pytest.raises(ValueError, match="user row alignment"):
        exporter.export_full_sort(scores, dataset, events, tmp_path / "export")
    assert not (tmp_path / "export").exists()


def test_score_shape_and_missing_clicked_mapping_fail_before_writes(tmp_path):
    scores, dataset, events = fixture()
    with pytest.raises(ValueError, match="scores shape"):
        exporter.export_full_sort(scores[:, :6], dataset, events, tmp_path / "export")
    del dataset.corpus.residual_clicked_set[7]
    with pytest.raises(ValueError, match="residual_clicked_set is unavailable"):
        exporter.export_full_sort(scores, dataset, events, tmp_path / "export")
    assert not (tmp_path / "export").exists()


def test_existing_outputs_or_source_file_cannot_be_replaced(tmp_path):
    scores, dataset, events = fixture()
    source = tmp_path / "source.npz"
    np.savez(source, scores=scores, item_id=np.stack([row["item_id"] for row in dataset.rows]))
    before = source.read_bytes()
    with pytest.raises(ValueError, match="must be new"):
        exporter.export_full_sort(scores, dataset, events, source)
    assert source.read_bytes() == before
    out = tmp_path / "export"
    exporter.export_full_sort(scores, dataset, events, out)
    outputs = {path.name: path.read_bytes() for path in out.iterdir()}
    with pytest.raises(ValueError, match="must be new"):
        exporter.export_full_sort(scores, dataset, events, out)
    assert {path.name: path.read_bytes() for path in out.iterdir()} == outputs
    assert source.read_bytes() == before


def test_symlink_output_and_ancestors_are_rejected(tmp_path):
    scores, dataset, events = fixture()
    linked = tmp_path / "linked"
    try:
        linked.symlink_to(tmp_path, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symbolic links unavailable: {exc}")
    with pytest.raises(ValueError, match="must be new"):
        exporter.export_full_sort(scores, dataset, events, linked)
    with pytest.raises(ValueError, match="symbolic-link ancestors"):
        exporter.export_full_sort(scores, dataset, events, linked / "export")
    assert not (tmp_path / "export").exists()
