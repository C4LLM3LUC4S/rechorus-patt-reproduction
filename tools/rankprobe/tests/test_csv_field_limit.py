"""CSV metadata-size errors give a safe recovery route without changing the cap."""

import csv
import hashlib
import json

import pytest

from rankprobe import Protocol, Row, audit_run
from rankprobe.cli import main
from rankprobe.io import InputError, read_predictions, read_qrels


@pytest.fixture
def small_csv_limit():
    previous = csv.field_size_limit(64)
    try:
        yield 64
    finally:
        csv.field_size_limit(previous)
        assert csv.field_size_limit() == previous


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def records(kind, limit):
    rows = [
        {"query_id": "q-01", "item_id": "doc-A", "relevance": 1, "text": "x" * (limit + 1)},
        {"query_id": "q-01", "item_id": "doc-B", "relevance": 0, "text": "short"},
    ]
    if kind == "predictions":
        rows[0]["score"], rows[1]["score"] = .9, .1
        rows[1]["relevance"] = None
    return rows


def write_csv(path, rows):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def loader(kind):
    return read_predictions if kind == "predictions" else read_qrels


@pytest.mark.parametrize("kind", ("predictions", "qrels"))
def test_oversized_unused_column_has_kind_specific_recovery_hint(tmp_path, small_csv_limit, kind):
    source = tmp_path / f"{kind}.csv"
    write_csv(source, records(kind, small_csv_limit))
    before = digest(source)
    with pytest.raises(InputError) as failure:
        loader(kind)(source)
    message = str(failure.value)
    assert message.startswith(f"{source}: cannot read input: field larger than field limit (64)")
    assert "CSV parser stopped at physical line 2" in message
    assert "also applies to unused text columns" in message
    assert "new minimal CSV" in message and "equivalent JSONL" in message
    assert "all supplied labels" in message and "original unchanged" in message
    if kind == "predictions":
        assert "query_id,item_id,score and relevance when supplied" in message
    else:
        assert "query_id,item_id,relevance" in message
        assert "query_id,item_id,score" not in message
    assert digest(source) == before
    assert csv.field_size_limit() == small_csv_limit


@pytest.mark.parametrize("kind", ("predictions", "qrels"))
def test_cli_field_limit_is_exit_two_before_output(tmp_path, capsys, small_csv_limit, kind):
    source = tmp_path / f"{kind}.csv"
    write_csv(source, records(kind, small_csv_limit))
    before = digest(source)
    out = tmp_path / "report"
    if kind == "predictions":
        arguments = [str(source)]
    else:
        predictions = tmp_path / "predictions.csv"
        write_csv(predictions, [{"query_id": "q-01", "item_id": "doc-A", "score": 1}])
        arguments = [str(predictions), "--qrels", str(source)]
    assert main(["audit", *arguments, "--out", str(out)]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith(f"rankprobe: {source}: cannot read input: ")
    assert "field larger than field limit (64)" in captured.err
    assert "CSV parser stopped at physical line 2" in captured.err
    assert "new minimal CSV" in captured.err
    assert "Traceback" not in captured.err
    assert not out.exists()
    assert digest(source) == before
    assert csv.field_size_limit() == small_csv_limit


@pytest.mark.parametrize("kind", ("predictions", "qrels"))
def test_new_minimal_csv_and_jsonl_preserve_rows_labels_and_metrics(
    tmp_path, capsys, small_csv_limit, kind,
):
    original = records(kind, small_csv_limit)
    source = tmp_path / "original.csv"
    write_csv(source, original)
    minimal = tmp_path / "minimal.csv"
    write_csv(minimal, [{key: value for key, value in row.items() if key != "text"}
                        for row in original])
    jsonl = tmp_path / "equivalent.jsonl"
    jsonl.write_text("".join(json.dumps(row) + "\n" for row in original), encoding="utf-8")
    paths = (source, minimal, jsonl)
    hashes = {path.name: digest(path) for path in paths}
    csv_values, jsonl_values = loader(kind)(minimal), loader(kind)(jsonl)
    assert csv_values == jsonl_values
    if kind == "predictions":
        assert csv_values == [Row("q-01", "doc-A", .9, 1), Row("q-01", "doc-B", .1)]
        expected = audit_run(csv_values, Protocol(cutoffs=(1,)))
    else:
        assert csv_values == {"q-01": {"doc-A": 1, "doc-B": 0}}
        predictions = tmp_path / "predictions.csv"
        write_csv(predictions, [{"query_id": "q-01", "item_id": "doc-A", "score": .9},
                                {"query_id": "q-01", "item_id": "doc-B", "score": .1}])
        expected = audit_run(read_predictions(predictions), Protocol(cutoffs=(1,)), csv_values)
    for input_path in (minimal, jsonl):
        out = tmp_path / input_path.stem
        arguments = [str(input_path)] if kind == "predictions" else [
            str(predictions), "--qrels", str(input_path),
        ]
        assert main(["audit", *arguments, "--cutoffs", "1", "--fail-on", "never",
                     "--out", str(out)]) == 0
        actual = json.loads((out / "report.json").read_text(encoding="utf-8"))
        assert (out / "report.html").is_file()
        assert actual["metrics"] == expected["metrics"]
        assert actual["summary"]["unknown_candidates"] == (1 if kind == "predictions" else 0)
        assert actual["summary"]["assumed_nonrelevant_candidates"] == 0
        assert actual["protocol"]["qrels_complete"] is False
    assert capsys.readouterr().err == ""
    assert {path.name: digest(path) for path in paths} == hashes
    assert csv.field_size_limit() == small_csv_limit


@pytest.mark.parametrize("kind", ("predictions", "qrels"))
def test_other_csv_errors_keep_generic_diagnostic(tmp_path, small_csv_limit, kind):
    field = "score" if kind == "predictions" else "relevance"
    source = tmp_path / "bad-quote.csv"
    source.write_text(f'query_id,item_id,{field}\nq,a,"1\n', encoding="utf-8")
    before = digest(source)
    with pytest.raises(InputError) as failure:
        loader(kind)(source)
    message = str(failure.value)
    assert message.startswith(f"{source}: cannot read input: unexpected end of data")
    assert "CSV parser stopped at physical line 2" in message
    assert "field limit" not in message
    assert "minimal CSV" not in message and "JSONL" not in message
    assert digest(source) == before
    assert csv.field_size_limit() == small_csv_limit
