"""Writing a report must never replace one of its own input files."""

import os

import pytest

from rankprobe.cli import main


def test_audit_cannot_overwrite_its_jsonl_input_named_report_json(tmp_path, capsys):
    source = tmp_path / "report.json"
    original = b'{"query_id":"q","item_id":"a","score":1,"relevance":1}\n'
    source.write_bytes(original)
    assert main([
        "audit", str(source), "--input-format", "jsonl", "--out", str(tmp_path), "--overwrite",
    ]) == 2
    assert source.read_bytes() == original
    assert not (tmp_path / "report.html").exists()
    assert "would replace input" in capsys.readouterr().err


def test_demo_cannot_overwrite_its_qrels_named_report_html(tmp_path):
    source = tmp_path / "report.html"
    original = b"query_id,item_id,relevance\nq,a,1\n"
    source.write_bytes(original)
    assert main([
        "demo", "--qrels", str(source), "--qrels-format", "csv",
        "--out", str(tmp_path), "--overwrite",
    ]) == 2
    assert source.read_bytes() == original
    assert not (tmp_path / "report.json").exists()


def test_compare_checks_all_run_inputs_before_writing(tmp_path):
    safe = tmp_path / "safe.csv"
    safe.write_text("query_id,item_id,score,relevance\nq,a,1,1\n", encoding="utf-8")
    source = tmp_path / "report.html"
    original = safe.read_bytes()
    source.write_bytes(original)
    assert main([
        "compare", "--run", f"safe={safe}", "--run", f"collision={source}",
        "--input-format", "csv", "--out", str(tmp_path), "--overwrite",
    ]) == 2
    assert source.read_bytes() == original
    assert not (tmp_path / "report.json").exists()


def test_existing_input_alias_cannot_be_replaced(tmp_path):
    source = tmp_path / "scores.csv"
    original = b"query_id,item_id,score,relevance\nq,a,1,1\n"
    source.write_bytes(original)
    alias = tmp_path / "report.json"
    try:
        os.link(source, alias)
    except OSError as exc:
        pytest.skip(f"hard links unavailable: {exc}")
    assert main(["audit", str(source), "--out", str(tmp_path), "--overwrite"]) == 2
    assert source.read_bytes() == alias.read_bytes() == original
    assert not (tmp_path / "report.html").exists()


def test_symlink_loop_is_a_concise_input_error(tmp_path, capsys):
    first, second = tmp_path / "first.csv", tmp_path / "second.csv"
    try:
        first.symlink_to(second)
        second.symlink_to(first)
    except OSError as exc:
        pytest.skip(f"symbolic links unavailable: {exc}")
    out = tmp_path / "output"
    assert main(["audit", str(first), "--out", str(out)]) == 2
    error = capsys.readouterr().err
    assert "rankprobe:" in error
    assert "Traceback" not in error
    assert not out.exists()
