from __future__ import annotations

from copy import deepcopy
import csv
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from rankprobe.io import read_predictions

np = pytest.importorskip("numpy")
SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "export_recbole.py"
SPEC = importlib.util.spec_from_file_location("export_recbole", SCRIPT)
exporter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(exporter)


def fixture():
    tokens = {
        "user_id": np.array(["[PAD]", "user, one", "user-two"]),
        "item_id": np.array(["[PAD]", "history", "known", "unknown"]),
    }
    dataset = SimpleNamespace(
        user_num=3, item_num=4, uid_field="user_id", iid_field="item_id",
        id2token=lambda field, ids: tokens[field][ids],
    )
    data = SimpleNamespace(
        is_sequential=False, dataset=dataset,
        uid2history_item={1: np.array([1]), 2: np.array([], dtype=np.int64)},
    )
    scores = np.array([
        [-np.inf, -np.inf, 1.0000000000000002, 1.0],
        [-np.inf, -0.0, 0.25, -0.5],
    ])
    return scores, np.array([1, 2]), data, tokens


def test_known_masks_have_reasons_and_scores_ids_labels_remain_exact(tmp_path):
    scores, users, data, tokens = fixture()
    before_scores, before_users = scores.copy(), users.copy()
    before_history, before_tokens = deepcopy(data.uid2history_item), deepcopy(tokens)
    out = tmp_path / "export with spaces"
    result = exporter.export_full_sort(scores, users, data, out)
    rows = read_predictions(out / "predictions.csv")
    assert [(row.query_id, row.item_id, row.score, row.relevance) for row in rows] == [
        ("user, one", "known", 1.0000000000000002, None),
        ("user, one", "unknown", 1.0, None),
        ("user-two", "history", -0.0, None),
        ("user-two", "known", 0.25, None),
        ("user-two", "unknown", -0.5, None),
    ]
    with (out / "predictions.csv").open(encoding="utf-8", newline="") as handle:
        assert csv.DictReader(handle).fieldnames == ["query_id", "item_id", "score"]
    assert result["exclusions_by_reason"] == {"padding": 2, "history": 1}
    assert result["exported_rows"] == 5
    assert result["excluded_rows"] == 3
    assert result["queries"][0]["exclusions"] == [
        {"internal_item_id": 0, "item_id": "[PAD]", "reason": "padding"},
        {"internal_item_id": 1, "item_id": "history", "reason": "history"},
    ]
    assert result["qrels_complete"] is False
    assert json.loads((out / "exclusions.json").read_text(encoding="utf-8")) == result
    assert str(tmp_path) not in (out / "exclusions.json").read_text(encoding="utf-8")
    np.testing.assert_array_equal(scores, before_scores)
    np.testing.assert_array_equal(users, before_users)
    for uid in data.uid2history_item:
        np.testing.assert_array_equal(data.uid2history_item[uid], before_history[uid])
    for field in tokens:
        np.testing.assert_array_equal(tokens[field], before_tokens[field])


def test_row_and_column_identity_follow_declared_order_not_sort_order(tmp_path):
    scores, users, data, _ = fixture()
    exporter.export_full_sort(scores[::-1], users[::-1], data, tmp_path / "export")
    rows = read_predictions(tmp_path / "export" / "predictions.csv")
    assert [row.query_id for row in rows] == ["user-two"] * 3 + ["user, one"] * 2
    assert rows[-2].score == 1.0000000000000002


@pytest.mark.parametrize("bad_score", [float("nan"), float("inf"), float("-inf")])
def test_eligible_nonfinite_score_is_rejected_not_dropped(tmp_path, bad_score):
    scores, users, data, _ = fixture()
    scores[1, 2] = bad_score
    with pytest.raises(ValueError, match="Eligible scores must be finite at score row 1"):
        exporter.export_full_sort(scores, users, data, tmp_path / "export")
    assert not (tmp_path / "export").exists()


@pytest.mark.parametrize("column,bad_score", [(0, 0.0), (1, 0.5), (1, np.nan), (1, np.inf)])
def test_mask_must_match_declared_loader_history(tmp_path, column, bad_score):
    scores, users, data, _ = fixture()
    scores[0, column] = bad_score
    with pytest.raises(ValueError, match="Declared padding/history mask must be -inf"):
        exporter.export_full_sort(scores, users, data, tmp_path / "export")
    assert not (tmp_path / "export").exists()


def test_all_masked_query_fails_instead_of_disappearing(tmp_path):
    scores, users, data, _ = fixture()
    data.uid2history_item[2] = np.array([1, 2, 3])
    scores[1] = -np.inf
    with pytest.raises(ValueError, match="No eligible candidates remain at score row 1"):
        exporter.export_full_sort(scores, users, data, tmp_path / "export")
    assert not (tmp_path / "export").exists()


@pytest.mark.parametrize("users", [[1, 1], [0, 2], [1, 3], [1.0, 2.0], [True, True], [[1, 2]], []])
def test_invalid_user_identity_rejected_before_writes(tmp_path, users):
    scores, _, data, _ = fixture()
    with pytest.raises(ValueError, match="uid_series"):
        exporter.export_full_sort(scores, users, data, tmp_path / "export")
    assert not (tmp_path / "export").exists()


@pytest.mark.parametrize("history", [None, [4], [-1], [1.5], [1, 1], [[1]], [True]])
def test_invalid_history_rejected_before_writes(tmp_path, history):
    scores, users, data, _ = fixture()
    data.uid2history_item[1] = history
    with pytest.raises(ValueError, match="History"):
        exporter.export_full_sort(scores, users, data, tmp_path / "export")
    assert not (tmp_path / "export").exists()


@pytest.mark.parametrize("field,replacement", [
    ("user_id", ["[PAD]", "same", "same"]),
    ("item_id", ["[PAD]", "same", "same", "other"]),
    ("user_id", ["[PAD]", " ", "other"]),
    ("item_id", ["[PAD]", "ok", "", "other"]),
])
def test_ambiguous_external_tokens_fail(tmp_path, field, replacement):
    scores, users, data, tokens = fixture()
    tokens[field] = np.array(replacement)
    with pytest.raises(ValueError, match="external tokens"):
        exporter.export_full_sort(scores, users, data, tmp_path / "export")
    assert not (tmp_path / "export").exists()


def test_sequential_contexts_and_topk_shapes_are_rejected(tmp_path):
    scores, users, data, _ = fixture()
    data.is_sequential = True
    with pytest.raises(ValueError, match="nonsequential"):
        exporter.export_full_sort(scores, users, data, tmp_path / "export")
    data.is_sequential = False
    with pytest.raises(ValueError, match="scores shape"):
        exporter.export_full_sort(scores[:, :2], users, data, tmp_path / "export")
    assert not (tmp_path / "export").exists()


def test_output_cannot_replace_file_or_existing_directory(tmp_path):
    scores, users, data, _ = fixture()
    source = tmp_path / "original.csv"
    source.write_bytes(b"keep original\n")
    with pytest.raises(ValueError, match="must be new"):
        exporter.export_full_sort(scores, users, data, source)
    assert source.read_bytes() == b"keep original\n"
    out = tmp_path / "export"
    exporter.export_full_sort(scores, users, data, out)
    original = {path.name: path.read_bytes() for path in out.iterdir()}
    with pytest.raises(ValueError, match="must be new"):
        exporter.export_full_sort(scores, users, data, out)
    assert {path.name: path.read_bytes() for path in out.iterdir()} == original


def test_symlink_output_and_ancestors_are_rejected(tmp_path):
    scores, users, data, _ = fixture()
    linked = tmp_path / "linked"
    try:
        linked.symlink_to(tmp_path, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symbolic links unavailable: {exc}")
    with pytest.raises(ValueError, match="must be new"):
        exporter.export_full_sort(scores, users, data, linked)
    with pytest.raises(ValueError, match="symbolic-link ancestors"):
        exporter.export_full_sort(scores, users, data, linked / "export")
    assert not (tmp_path / "export").exists()


def test_padding_declared_twice_has_one_exclusion_reason(tmp_path):
    scores, users, data, _ = fixture()
    data.uid2history_item[1] = np.array([0, 1])
    result = exporter.export_full_sort(scores, users, data, tmp_path / "export")
    assert result["exclusions_by_reason"] == {"padding": 2, "history": 1}
    assert result["excluded_rows"] == 3
