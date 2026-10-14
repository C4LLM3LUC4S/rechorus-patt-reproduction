import json
import math

import pytest

from rankprobe.io import InputError, read_predictions, read_qrels
from rankprobe.model import Protocol, Row


def test_csv_utf8_bom_unicode_identifiers_and_unknown(tmp_path):
    path = tmp_path / "predictions.csv"
    path.write_text(
        "query_id,item_id,score,relevance\n查询,001,-2.5,\n查询,002,3,1\n", encoding="utf-8-sig"
    )
    rows = read_predictions(path)
    assert rows == [Row("查询", "001", -2.5), Row("查询", "002", 3, 1)]


def test_jsonl_order_and_null(tmp_path):
    path = tmp_path / "runs.jsonl"
    path.write_text(
        '\n{"query_id":"q","item_id":"x","score":1,"relevance":null}\n', encoding="utf-8"
    )
    assert read_predictions(path) == [Row("q", "x", 1)]


@pytest.mark.parametrize(
    "payload",
    [
        '{"query_id":"q","item_id":"x","score":NaN}',
        '{"query_id":"q","item_id":"x","score":1,"score":2}',
        '{"query_id":1,"item_id":"x","score":1}',
        '{"query_id":"q","item_id":"x","score":true}',
        '{"query_id":"q","item_id":"x","score":1,"relevance":-1}',
        "[1,2,3]",
    ],
)
def test_jsonl_rejects_ambiguous_or_invalid_rows(tmp_path, payload):
    path = tmp_path / "bad.jsonl"
    path.write_text(payload, encoding="utf-8")
    with pytest.raises(InputError, match=r"bad.jsonl:1:"):
        read_predictions(path)


@pytest.mark.parametrize(
    "body",
    [
        "query_id,item_id,score,score\nq,x,1,2\n",
        "query_id,item_id\nq,x\n",
        "query_id,item_id,score\nq,x,1,extra\n",
        "query_id,item_id,score\nq,x\n",
        "query_id,item_id,score\nq,x,inf\n",
        "query_id,item_id,score\n",
    ],
)
def test_csv_rejects_bad_structure(tmp_path, body):
    path = tmp_path / "bad.csv"
    path.write_text(body, encoding="utf-8")
    with pytest.raises(InputError):
        read_predictions(path)


def test_qrels_conflicts_and_missing_labels(tmp_path):
    path = tmp_path / "qrels.csv"
    path.write_text("query_id,item_id,relevance\nq,x,1\nq,x,2\n", encoding="utf-8")
    with pytest.raises(InputError, match="duplicate qrels entry"):
        read_qrels(path)
    path.write_text("query_id,item_id,relevance\nq,x,\n", encoding="utf-8")
    with pytest.raises(InputError):
        read_qrels(path)


def test_qrels_jsonl_and_missing_file(tmp_path):
    path = tmp_path / "qrels.jsonl"
    path.write_text(json.dumps({"query_id": "q", "item_id": "a", "relevance": 2}), encoding="utf-8")
    assert read_qrels(path) == {"q": {"a": 2.0}}
    with pytest.raises(InputError, match="cannot read input"):
        read_predictions(tmp_path / "missing.csv")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"cutoffs": ()},
        {"cutoffs": (0,)},
        {"cutoffs": (True,)},
        {"tie_policy": "random"},
        {"gain": "unknown"},
        {"unjudged": "zero"},
        {"qrels_complete": 1},
        {"relevance_threshold": math.nan},
        {"duplicate_policy": "keep"},
    ],
)
def test_protocol_validation(kwargs):
    with pytest.raises(ValueError):
        Protocol(**kwargs)


def test_protocol_normalizes_cutoffs_and_freezes():
    assert Protocol(cutoffs=(10, 1, 10, 5)).cutoffs == (1, 5, 10)
    with pytest.raises(AttributeError):
        Protocol().gain = "exp2"


def test_row_rejects_nonfinite_and_invalid_identifiers():
    for value in [math.nan, math.inf, True, "1", 10**400]:
        with pytest.raises(ValueError):
            Row("q", "a", value)
    with pytest.raises(ValueError):
        Row(" ", "a", 1)
    with pytest.raises(ValueError):
        Row("q", "a" * 4097, 1)
