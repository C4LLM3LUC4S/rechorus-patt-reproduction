import builtins
import importlib.util
import json
from pathlib import Path
import subprocess

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_beir_workflow.py"
SPEC = importlib.util.spec_from_file_location("check_beir_workflow", SCRIPT)
checker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checker)


def test_existing_output_is_rejected_before_optional_imports(tmp_path, monkeypatch):
    out = tmp_path / "existing"
    out.mkdir()
    kept = out / "summary.json"
    kept.write_bytes(b"keep original")
    real_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        assert name != "beir", "output guard must run before optional imports"
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    with pytest.raises(checker.GateError, match="directory must be new"):
        checker.check_workflow(out)
    assert kept.read_bytes() == b"keep original"


def test_missing_optional_dependencies_do_not_create_output(tmp_path, monkeypatch, capsys):
    real_import = builtins.__import__

    def absent_beir(name, *args, **kwargs):
        if name == "beir":
            raise ImportError("test intentionally lacks optional dependency")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", absent_beir)
    out = tmp_path / "private-output-name"
    assert checker.main(["--out", str(out)]) == 1
    output = capsys.readouterr().out
    assert json.loads(output)["status"] == "failed"
    assert "private-output-name" not in output
    assert not out.exists()


def test_missing_parent_is_rejected_without_creating_directories(tmp_path):
    missing = tmp_path / "absent-parent"
    with pytest.raises(checker.GateError, match="parent directory"):
        checker.check_workflow(missing / "out")
    assert not missing.exists()


def test_failed_cli_does_not_expose_captured_private_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(checker.subprocess, "run", lambda *args, **kwargs:
                        subprocess.CompletedProcess([], 2, "private-path", "private-path"))
    with pytest.raises(checker.GateError, match="nonzero exit status") as caught:
        checker.run_comparison(tmp_path, tmp_path / "a.run", tmp_path / "b.run", tmp_path / "labels.qrels")
    assert "private-path" not in str(caught.value)


def test_downstream_cli_preserves_unknowns_and_separates_changed_candidate_pool(tmp_path):
    original, filtered, qrels = (tmp_path / name for name in ("original.run", "filtered.run", "judgments.qrels"))
    original.write_text("q1 Q0 q1 0 3 raw\nq1 Q0 d1 0 2 raw\nq1 Q0 u 0 1 raw\nq2 Q0 d2 0 4 raw\nq2 Q0 d3 0 3 raw\n", encoding="utf-8")
    filtered.write_text("q1 Q0 d1 0 2 filtered\nq1 Q0 u 0 1 filtered\nq2 Q0 d2 0 4 filtered\nq2 Q0 d3 0 3 filtered\n", encoding="utf-8")
    qrels.write_text("q1 0 q1 0\nq1 0 d1 1\nq2 0 d2 1\nq2 0 d3 0\n", encoding="utf-8")
    before = [path.read_bytes() for path in (original, filtered, qrels)]
    report = checker.run_comparison(tmp_path, original, filtered, qrels)
    assert report["runs"]["original"]["metrics"]["mrr@1"]["value"] == .5
    assert report["runs"]["filtered"]["metrics"]["mrr@1"]["value"] == 1
    assert report["runs"]["original"]["audit"]["summary"]["unknown_candidates"] == 1
    matched = report["pairs"][0]["matched_pool_comparison"]
    assert matched["query_ids"] == ["q2"]
    assert matched["delta_right_minus_left"]["mrr@1"]["delta"] == 0
    assert report["protocol"]["unjudged"] == "unknown"
    assert report["protocol"]["qrels_complete"] is False
    assert [path.read_bytes() for path in (original, filtered, qrels)] == before
