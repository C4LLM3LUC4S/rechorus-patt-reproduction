import builtins
import importlib.util
import json
from pathlib import Path
import subprocess

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_recbole_workflow.py"
SPEC = importlib.util.spec_from_file_location("check_recbole_workflow", SCRIPT)
checker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checker)


def test_existing_output_is_rejected_before_optional_imports(tmp_path, monkeypatch):
    out = tmp_path / "existing"
    out.mkdir()
    kept = out / "summary.json"
    kept.write_bytes(b"keep original")
    real_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        assert name not in {"numpy", "torch", "recbole"} and not name.startswith("recbole.")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    with pytest.raises(checker.GateError, match="directory must be new"):
        checker.check_workflow(out)
    assert kept.read_bytes() == b"keep original"


def test_requested_users_keep_requested_order_and_inputs():
    evaluation_uids = [1, 2, 3]
    requested = [3, 1]
    selected = checker.select_requested_users(evaluation_uids, requested)
    assert selected == [3, 1]
    assert evaluation_uids == [1, 2, 3]
    assert requested == [3, 1]


def test_absent_requested_user_is_refused_without_silently_dropping_it():
    evaluation_uids = [1, 2]
    requested = [2, 3, 1]
    with pytest.raises(checker.GateError):
        checker.select_requested_users(evaluation_uids, requested)
    assert evaluation_uids == [1, 2]
    assert requested == [2, 3, 1]


@pytest.mark.parametrize("requested", [[], [2, 2]])
def test_empty_or_duplicate_requested_users_are_refused(requested):
    before = requested.copy()
    with pytest.raises(checker.GateError):
        checker.select_requested_users([1, 2], requested)
    assert requested == before


def test_empty_evaluation_population_cannot_supply_requested_user():
    with pytest.raises(checker.GateError):
        checker.select_requested_users([], [1])


def test_missing_optional_dependency_does_not_create_output(tmp_path, monkeypatch, capsys):
    real_import = builtins.__import__

    def absent_numpy(name, *args, **kwargs):
        if name == "numpy":
            raise ImportError("test intentionally lacks an optional dependency")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", absent_numpy)
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


def test_symlink_ancestor_is_rejected(tmp_path):
    original = tmp_path / "original"
    original.mkdir()
    link = tmp_path / "linked"
    try:
        link.symlink_to(original, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("creating symlinks is unavailable in this environment")
    with pytest.raises(checker.GateError, match="symbolic-link ancestors"):
        checker.new_output_directory(link / "new")
    assert list(original.iterdir()) == []


def test_failed_cli_does_not_expose_captured_private_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(checker.subprocess, "run", lambda *args, **kwargs:
                        subprocess.CompletedProcess([], 2, "private-path", "private-path"))
    with pytest.raises(checker.GateError, match="nonzero exit status") as caught:
        checker.run_comparison(tmp_path, tmp_path / "a.csv", tmp_path / "b.csv", tmp_path / "labels.csv")
    assert "private-path" not in str(caught.value)


def test_naive_nonfinite_csv_is_rejected_by_actual_cli_without_report(tmp_path):
    unsafe = tmp_path / "naive.csv"
    checker.write_csv(unsafe, ["query_id", "item_id", "score"], [
        ("reader B", "[PAD]", float("-inf")), ("reader B", "known", .75),
    ])
    before = unsafe.read_bytes()
    out = tmp_path / "failed-report"
    process = checker._run_cli(tmp_path, [
        "audit", str(unsafe), "--out", str(out), "--fail-on", "never",
    ])
    assert process.returncode == 2
    assert "finite" in process.stderr
    assert not out.exists()
    assert unsafe.read_bytes() == before


def test_downstream_cli_preserves_tokens_scores_and_unknown_labels(tmp_path):
    expected, exported, qrels = (tmp_path / name for name in (
        "expected.csv", "exported.csv", "judgments.csv",
    ))
    rows = [
        ("reader B", "history one", .75), ("reader B", "paper β", .625),
        ("learner,甲", "paper,α", .75), ("learner,甲", "paper β", .625),
        ("learner,甲", "unjudged", .5), ("learner,甲", "negative", .25),
    ]
    for path in (expected, exported):
        checker.write_csv(path, ["query_id", "item_id", "score"], rows)
    checker.write_csv(qrels, ["query_id", "item_id", "relevance"], [
        ("reader B", "history one", 0), ("reader B", "paper β", 1),
        ("learner,甲", "paper,α", 1), ("learner,甲", "paper β", 0),
        ("learner,甲", "negative", 0),
    ])
    before = [path.read_bytes() for path in (expected, exported, qrels)]
    report = checker.run_comparison(tmp_path, expected, exported, qrels)
    assert report["runs"]["exported"]["metrics"]["mrr@1"]["value"] == .5
    assert report["runs"]["exported"]["metrics"]["mrr@2"]["value"] == .75
    assert report["runs"]["exported"]["audit"]["summary"]["unknown_candidates"] == 1
    assert report["runs"]["exported"]["metrics"]["ndcg@1"]["excluded_query_ids"] == ["learner,甲"]
    assert report["runs"]["exported"]["metrics"]["recall@1"]["value"] is None
    matched = report["pairs"][0]["matched_pool_comparison"]
    assert matched["query_count"] == 2
    assert matched["delta_right_minus_left"]["mrr@1"]["delta"] == 0
    assert report["protocol"]["unjudged"] == "unknown"
    assert report["protocol"]["qrels_complete"] is False
    assert [path.read_bytes() for path in (expected, exported, qrels)] == before
