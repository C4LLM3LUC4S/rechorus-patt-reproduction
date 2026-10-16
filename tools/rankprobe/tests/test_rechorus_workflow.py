import builtins
import importlib.util
import json
from pathlib import Path
import subprocess

import numpy as np
import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_rechorus_workflow.py"
SPEC = importlib.util.spec_from_file_location("check_rechorus_workflow", SCRIPT)
checker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checker)


def test_existing_output_is_rejected_before_source_reads_and_optional_imports(tmp_path, monkeypatch):
    out = tmp_path / "existing"
    out.mkdir()
    kept = out / "summary.json"
    kept.write_bytes(b"keep original")
    monkeypatch.setattr(checker, "validated_source", lambda source: pytest.fail("source was read"))
    with pytest.raises(checker.GateError, match="directory must be new"):
        checker.check_workflow(out, tmp_path / "unavailable-source")
    assert kept.read_bytes() == b"keep original"


def test_unpinned_source_is_rejected_before_optional_imports(tmp_path, monkeypatch):
    source = tmp_path / "source"
    for name in checker.SOURCE_SHA256:
        path = source / "src" / (name.replace(".", "/") + ".py")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("unverified fixture, never imported", encoding="utf-8")
    real_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        assert name not in {"numpy", "torch", "pandas"}
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    out = tmp_path / "new-output"
    with pytest.raises(checker.GateError, match="differ from pinned source"):
        checker.check_workflow(out, source)
    assert not out.exists()


def test_missing_optional_dependencies_do_not_create_output(tmp_path, monkeypatch, capsys):
    # This unit test bypasses source validation to isolate dependency handling;
    # it does not stand in for execution of any upstream framework module.
    monkeypatch.setattr(checker, "validated_source", lambda source: (source, {}))
    real_import = builtins.__import__

    def absent_numpy(name, *args, **kwargs):
        if name == "numpy":
            raise ImportError("test intentionally lacks an optional dependency")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", absent_numpy)
    out = tmp_path / "private-output-name"
    assert checker.main(["--out", str(out), "--source", str(tmp_path / "private-source")]) == 1
    output = capsys.readouterr().out
    assert json.loads(output)["status"] == "failed"
    assert "private-output-name" not in output
    assert "private-source" not in output
    assert not out.exists()


def test_missing_output_parent_is_not_created(tmp_path):
    missing = tmp_path / "absent-parent"
    with pytest.raises(checker.GateError, match="parent directory"):
        checker.check_workflow(missing / "out", tmp_path / "source")
    assert not missing.exists()


def test_symlink_source_is_rejected(tmp_path):
    source = tmp_path / "original"
    source.mkdir()
    link = tmp_path / "linked"
    try:
        link.symlink_to(source, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("creating symlinks is unavailable in this environment")
    with pytest.raises(checker.GateError, match="directory is unavailable"):
        checker.validated_source(link)
    assert list(source.iterdir()) == []


def test_failed_cli_does_not_expose_captured_private_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(checker.subprocess, "run", lambda *args, **kwargs:
                        subprocess.CompletedProcess([], 2, "private-path", "private-path"))
    with pytest.raises(checker.GateError, match="nonzero exit status") as caught:
        checker.run_audit(tmp_path, tmp_path / "predictions.csv")
    assert "private-path" not in str(caught.value)


def test_existing_npz_bridge_and_actual_cli_keep_contexts_and_unknowns(tmp_path):
    candidates = np.array([[101, *range(1, 101), 102], [102, *range(1, 101), 101]])
    table = np.arange(103, dtype=np.float64) / 1024
    table[101:] = .75
    scores = table[candidates]
    source = tmp_path / "sampled.npz"
    with source.open("xb") as handle:
        np.savez(handle, scores=scores, item_id=candidates, user_id=[7, 7])
    before = source.read_bytes()
    destination = tmp_path / "predictions.csv"
    export_metadata = checker._load_exporter()(source, destination, positive_index=0)
    report = checker.run_audit(tmp_path, destination)
    assert export_metadata["exported_rows"] == 204
    assert export_metadata["positive_index"] == 0
    assert export_metadata["other_candidates"] == "unknown"
    assert export_metadata["user_ids_exported"] is False
    assert report["summary"]["queries"] == 2
    assert report["summary"]["unknown_candidates"] == 202
    assert report["metrics"]["mrr@1"]["eligible_query_ids"] == ["query_000001"]
    assert report["metrics"]["mrr@1"]["excluded_query_ids"] == ["query_000002"]
    assert report["metrics"]["mrr@1"]["value"] == 1
    assert report["metrics"]["mrr@2"]["value"] == 1
    assert report["metrics"]["mrr@2"]["eligible_query_ids"] == ["query_000001"]
    assert report["metrics"]["mrr@2"]["excluded_query_ids"] == ["query_000002"]
    assert report["metrics"]["ndcg@1"]["value"] is None
    assert report["metrics"]["recall@1"]["value"] is None
    assert report["protocol"]["qrels_complete"] is False
    assert "score_ties" in {finding["code"] for finding in report["findings"]}
    assert source.read_bytes() == before


def test_explicit_synthetic_tie_oracle_is_separate_from_unknown_export(tmp_path):
    from rankprobe.io import read_predictions
    from rankprobe.metrics import evaluate_metrics
    from rankprobe.model import Protocol, Row

    source = tmp_path / "tie.npz"
    with source.open("xb") as handle:
        np.savez(handle, scores=[[1., 1.]], item_id=[[101, 102]])
    destination = tmp_path / "tie.csv"
    checker._load_exporter()(source, destination, positive_index=0)
    before = destination.read_bytes()
    exported = read_predictions(destination)
    assert exported[1].relevance is None
    unknown = evaluate_metrics(exported, Protocol(cutoffs=(1,)))
    assert unknown["ndcg@1"]["value"] is None
    explicit_oracle = [Row(row.query_id, row.item_id, row.score, float(index == 0))
                       for index, row in enumerate(exported)]
    judged = evaluate_metrics(explicit_oracle, Protocol(cutoffs=(1,)))
    assert judged["ndcg@1"]["value"] == 1
    assert read_predictions(destination)[1].relevance is None
    assert destination.read_bytes() == before
