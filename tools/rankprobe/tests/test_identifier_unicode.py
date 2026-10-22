"""Reject malformed Unicode identifiers before report generation."""

import hashlib
import json
import re
import subprocess
import sys

import pytest

from rankprobe import Protocol, Row, audit_run
from rankprobe.io import InputError, read_predictions, read_qrels
from rankprobe.report import write_report


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize("kind", ("predictions", "qrels"))
@pytest.mark.parametrize("field", ("query_id", "item_id"))
@pytest.mark.parametrize("invalid", ("bad-\ud800-tail", "bad-\udfff-tail"))
def test_jsonl_bad_id_has_original_line_and_field_before_cli_writes(tmp_path, kind, field, invalid):
    first = {"query_id": "q1", "item_id": "a", "relevance": 1}
    second = {"query_id": "q2", "item_id": "a", "relevance": 1}
    if kind == "predictions":
        first["score"] = second["score"] = 1
    second[field] = invalid
    source = tmp_path / "bad-identifiers.jsonl"
    source.write_text("\n".join(json.dumps(row) for row in (first, second)) + "\n",
                      encoding="ascii")
    before = digest(source)
    expected = f"{source}:2: {field} must contain valid Unicode text"
    loader = read_predictions if kind == "predictions" else read_qrels
    with pytest.raises(InputError, match=re.escape(expected)):
        loader(source)
    out = tmp_path / "report"
    if kind == "predictions":
        arguments = [str(source)]
    else:
        predictions = tmp_path / "predictions.csv"
        predictions.write_text("query_id,item_id,score\nq1,a,1\n", encoding="ascii")
        arguments = [str(predictions), "--qrels", str(source)]
    child = subprocess.run(
        [sys.executable, "-m", "rankprobe", "audit", *arguments, "--out", str(out)],
        capture_output=True, text=True, encoding="utf-8", errors="strict",
    )
    assert child.returncode == 2
    assert child.stderr.strip() == "rankprobe: " + expected
    assert child.stdout == ""
    assert "Traceback" not in child.stderr
    assert not out.exists()
    assert digest(source) == before


@pytest.mark.parametrize("field", ("query_id", "item_id"))
@pytest.mark.parametrize("invalid", ("bad-\ud800-tail", "bad-\udfff-tail"))
def test_direct_row_bad_unicode_rejected_in_its_field(field, invalid):
    values = {"query_id": "q", "item_id": "a", "score": 1}
    values[field] = invalid
    with pytest.raises(ValueError, match=f"{field} must contain valid Unicode text"):
        Row(**values)


@pytest.mark.parametrize("field", ("query_id", "item_id"))
@pytest.mark.parametrize("invalid", ("bad-\ud800-tail", "bad-\udfff-tail"))
def test_direct_qrels_bad_unicode_rejected_before_report_creation(field, invalid):
    qrels = {invalid: {"a": 1}} if field == "query_id" else {"q": {invalid: 1}}
    with pytest.raises(ValueError, match=f"qrels {field} must contain valid Unicode text"):
        audit_run([Row("q", "a", 1)], Protocol(cutoffs=(1,)), qrels=qrels)


@pytest.mark.parametrize("escaped", (False, True))
def test_valid_unicode_and_json_surrogate_pairs_reach_reports_unchanged(tmp_path, escaped):
    query, item = "查询-🧪", "文档-🧪"
    source = tmp_path / "valid.jsonl"
    source.write_text(json.dumps({"query_id": query, "item_id": item, "score": 1},
                                 ensure_ascii=escaped) + "\n", encoding="utf-8")
    before = digest(source)
    rows = read_predictions(source)
    assert rows[0].query_id == query
    assert rows[0].item_id == item
    report = audit_run(rows, Protocol(cutoffs=(1,)))
    json_path, html_path = write_report(report, tmp_path / "api-report")
    stored = json.loads(json_path.read_text(encoding="utf-8"))
    assert stored["summary"]["unknown_candidates"] == 1
    assert query in json_path.read_text(encoding="utf-8")
    assert item in html_path.read_text(encoding="utf-8")
    qrels_source = tmp_path / "valid-qrels.jsonl"
    qrels_source.write_text(json.dumps({"query_id": query, "item_id": item, "relevance": 1},
                                       ensure_ascii=escaped) + "\n", encoding="utf-8")
    qrels_before = digest(qrels_source)
    assert read_qrels(qrels_source) == {query: {item: 1}}
    child = subprocess.run(
        [sys.executable, "-m", "rankprobe", "audit", str(source), "--cutoffs", "1",
         "--qrels", str(qrels_source),
         "--out", str(tmp_path / "cli-report")],
        capture_output=True, text=True, encoding="utf-8", errors="strict",
    )
    assert child.returncode == 0
    assert child.stderr == ""
    assert (tmp_path / "cli-report" / "report.html").is_file()
    assert (tmp_path / "cli-report" / "report.json").is_file()
    cli_report = json.loads((tmp_path / "cli-report" / "report.json").read_text(encoding="utf-8"))
    assert cli_report["metrics"]["mrr@1"]["value"] == 1
    assert cli_report["metrics"]["mrr@1"]["eligible_query_ids"] == [query]
    assert digest(source) == before
    assert digest(qrels_source) == qrels_before


def test_direct_qrels_legacy_id_bounds_do_not_expand_with_unicode_check():
    for identifier in (" ", "x" * 4097):
        report = audit_run([Row("q", "a", 1)], Protocol(cutoffs=(1,)),
                           qrels={identifier: {identifier: 1}})
        assert report["summary"]["qrels_queries_without_predictions"] == 1
    with pytest.raises(ValueError, match="qrels query IDs must be nonempty strings"):
        audit_run([Row("q", "a", 1)], Protocol(), qrels={"": {"a": 1}})
    with pytest.raises(ValueError, match="qrels item IDs must be nonempty strings"):
        audit_run([Row("q", "a", 1)], Protocol(), qrels={"q": {"": 1}})
    with pytest.raises(ValueError, match="4096-character input limit"):
        Row("x" * 4097, "a", 1)
