import hashlib

import pytest

from rankprobe.cli import main
from rankprobe.io import InputError, read_qrels


def test_subtopic_shaped_repeated_pair_has_recovery_hint_and_no_report(tmp_path, capsys):
    predictions = tmp_path / "predictions.run"
    predictions.write_text("qA Q0 dA 1 2 toy\n", encoding="utf-8")
    qrels = tmp_path / "subtopics.qrels"
    qrels.write_text("qA 1 dA 1\nqA 2 dA 0\n", encoding="utf-8")
    before = {
        path: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (predictions, qrels)
    }

    with pytest.raises(InputError, match="subtopics.qrels:2:.*duplicate qrels entry"):
        read_qrels(qrels)
    destination = tmp_path / "report"
    assert main([
        "audit", str(predictions), "--qrels", str(qrels), "--out", str(destination)
    ]) == 2

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "subtopics.qrels:2:" in captured.err
    assert "expected one ordinary query-item judgment" in captured.err
    assert "Field 2 is ignored" in captured.err
    assert "if it represents subtopics/intents" in captured.err
    assert "native evaluator" in captured.err
    assert (
        "https://github.com/C4LLM3LUC4S/rechorus-patt-reproduction/"
        "blob/main/tools/rankprobe/docs/input-format.md"
        "#subtopic-and-diversity-judgments"
    ) in captured.err
    assert "Traceback" not in captured.err
    assert not destination.exists()
    assert {
        path: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (predictions, qrels)
    } == before


def test_nonzero_ordinary_iteration_remains_accepted(tmp_path):
    source = tmp_path / "ordinary.qrels"
    source.write_text("qA 7 dA 1\nqA 7 dB 0\n", encoding="utf-8")
    assert read_qrels(source) == {"qA": {"dA": 1.0, "dB": 0.0}}


def test_unique_pair_shape_is_parsed_only_as_ordinary_query_item_judgments(tmp_path):
    source = tmp_path / "ambiguous.qrels"
    source.write_text("qA 1 dA 1\nqA 2 dB 0\n", encoding="utf-8")
    assert read_qrels(source) == {"qA": {"dA": 1.0, "dB": 0.0}}


@pytest.mark.parametrize("format", ["csv", "jsonl"])
def test_other_qrels_formats_keep_their_duplicate_error(tmp_path, format):
    source = tmp_path / f"ordinary.{format}"
    if format == "csv":
        body = "query_id,item_id,relevance\nqA,dA,1\nqA,dA,0\n"
    else:
        body = (
            '{"query_id":"qA","item_id":"dA","relevance":1}\n'
            '{"query_id":"qA","item_id":"dA","relevance":0}\n'
        )
    source.write_text(body, encoding="utf-8")
    with pytest.raises(InputError, match="duplicate qrels entry") as error:
        read_qrels(source)
    assert "subtopics" not in str(error.value)
    assert "Field 2" not in str(error.value)
