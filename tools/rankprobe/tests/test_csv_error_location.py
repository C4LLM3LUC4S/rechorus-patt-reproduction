"""CSV diagnostics locate the parser stop without guessing a record's start."""

import csv
import json
import subprocess
import sys

import pytest

from rankprobe import Row
from rankprobe.io import InputError, read_predictions, read_qrels


def body(kind, newline, failure):
    if kind == "predictions":
        header = "query_id,item_id,score,relevance,metadata"
        first = 'q,a,9007199254740993,1,"one' + newline + 'two"'
        second = "q,b,9007199254740992,,"
    else:
        header = "query_id,item_id,relevance,metadata"
        first = 'q,a,1,"one' + newline + 'two"'
        second = "q,b,0,"
    suffix = (
        '"unfinished' + newline + "last line" + newline
        if failure == "unclosed" else '"closed"oops' + newline
    )
    return header + newline + first + newline * 2 + second + suffix


def loader(kind):
    return read_predictions if kind == "predictions" else read_qrels


@pytest.mark.parametrize("kind", ["predictions", "qrels"])
@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"])
@pytest.mark.parametrize("failure,stop", [("unclosed", 6), ("after_quote", 5)])
def test_parser_stop_counts_physical_lines_after_multiline_record(
    tmp_path, kind, newline, failure, stop,
):
    source = tmp_path / f"{kind}.csv"
    source.write_text(body(kind, newline, failure), encoding="utf-8", newline="")
    original, field_limit = source.read_bytes(), csv.field_size_limit()
    with pytest.raises(InputError) as error:
        loader(kind)(source)
    message = str(error.value)
    assert message.startswith(f"{source}: cannot read input:")
    assert f"CSV parser stopped at physical line {stop}" in message
    assert "the record may start earlier" in message
    assert "Check CSV quoting and delimiters" in message
    assert "original unchanged" in message
    assert source.read_bytes() == original
    assert csv.field_size_limit() == field_limit


@pytest.mark.parametrize("kind", ["predictions", "qrels"])
@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"])
def test_header_parse_failure_also_has_stop_position(tmp_path, kind, newline):
    source = tmp_path / "header.csv"
    field = "score" if kind == "predictions" else "relevance"
    source.write_text(
        f'query_id,item_id,"{field}' + newline + "unfinished" + newline,
        encoding="utf-8", newline="",
    )
    original = source.read_bytes()
    with pytest.raises(InputError) as error:
        loader(kind)(source)
    assert "CSV parser stopped at physical line 2" in str(error.value)
    assert source.read_bytes() == original


@pytest.mark.parametrize("kind", ["predictions", "qrels"])
def test_cli_diagnostic_and_corrected_export_preserve_rows_and_unknowns(tmp_path, kind):
    source = tmp_path / "original.csv"
    source.write_text(body(kind, "\n", "unclosed"), encoding="utf-8", newline="")
    original = source.read_bytes()
    predictions = tmp_path / "predictions.csv"
    predictions.write_text(
        "query_id,item_id,score\nq,a,3\nq,b,2\nq,c,1\n", encoding="utf-8",
    )
    output = tmp_path / "report"

    def run(path):
        arguments = [str(path)] if kind == "predictions" else [
            str(predictions), "--qrels", str(path),
        ]
        return subprocess.run(
            [sys.executable, "-m", "rankprobe", "audit", *arguments,
             "--out", str(output), "--cutoffs", "1", "--fail-on", "never"],
            capture_output=True, text=True, encoding="utf-8", timeout=30, check=False,
        )

    failed = run(source)
    assert failed.returncode == 2
    assert "CSV parser stopped at physical line 6" in failed.stderr
    assert "the record may start earlier" in failed.stderr
    assert "Traceback" not in failed.stderr
    assert failed.stdout == "" and not output.exists()

    corrected = tmp_path / "new-export.csv"
    corrected.write_text(
        body(kind, "\r\n", "unclosed").replace(
            '"unfinished\r\nlast line\r\n', '"re-exported\r\nmetadata"\r\n',
        ),
        encoding="utf-8", newline="",
    )
    expected = (
        [Row("q", "a", 9007199254740993, 1), Row("q", "b", 9007199254740992)]
        if kind == "predictions" else {"q": {"a": 1, "b": 0}}
    )
    assert loader(kind)(corrected) == expected
    successful = run(corrected)
    assert successful.returncode == 0, successful.stderr
    assert successful.stderr == "" and (output / "report.html").is_file()
    report = json.loads((output / "report.json").read_text(encoding="utf-8"))
    assert report["metrics"]["mrr@1"]["value"] == 1
    assert report["summary"]["unknown_candidates"] == 1
    assert report["summary"]["assumed_nonrelevant_candidates"] == 0
    assert source.read_bytes() == original
