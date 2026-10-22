"""Execute the documented local runner on original CLI integration controls."""

import ast
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest


DOC = Path(__file__).resolve().parents[1] / "docs/local-ci.md"


@pytest.fixture
def recipe(tmp_path):
    source = DOC.read_text(encoding="utf-8").split("```python\n", 1)[1].split("\n```", 1)[0]
    ast.parse(source)
    folder = tmp_path / "runner folder with spaces"
    folder.mkdir()
    script = folder / "local_rankprobe_check.py"
    script.write_text(source + "\n", encoding="utf-8")
    cwd = tmp_path / "working directory with spaces"
    cwd.mkdir()
    return script, cwd


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize("case", ("warning", "error", "invalid", "partial", "stale"))
def test_documented_runner_preserves_status_reports_inputs_and_unknowns(tmp_path, recipe, case):
    script, cwd = recipe
    inputs = tmp_path / "input exports with spaces"
    inputs.mkdir()
    sparse = inputs / "sparse scores.csv"
    sparse.write_text("query_id,item_id,score,relevance\nq,a,1,1\nq,b,0,\n", encoding="utf-8")
    left = inputs / "left scores.csv"
    left.write_text("query_id,item_id,score,relevance\nq,a,1,1\n", encoding="utf-8")
    right = inputs / "right scores.csv"
    right.write_text("query_id,item_id,score,relevance\nq,a,1,0\n", encoding="utf-8")
    invalid = inputs / "invalid scores.csv"
    invalid.write_text("query_id,item_id,score\nq,a,not-a-score\n", encoding="utf-8")
    qrels = inputs / "sparse judgments.csv"
    qrels.write_text("query_id,item_id,relevance\nq,a,1\n", encoding="utf-8")
    originals = [sparse, left, right, invalid, qrels]
    hashes = {path.name: digest(path) for path in originals}
    out = cwd / "new report artifacts"
    arguments = [str(sparse), "--qrels", str(qrels)]
    expected = 1
    if case == "error":
        arguments = [str(left), str(right), "--fail-on", "error"]
    elif case == "invalid":
        arguments, expected = [str(invalid)], 2
    elif case == "partial":
        arguments, expected = [str(sparse), "--fail-on", "error"], 0
    elif case == "stale":
        expected = 2
        out.mkdir()
        # These deliberately unreadable-as-JSON old reports must never be collected.
        (out / "report.json").write_bytes(b"previous private report\n")
        (out / "report.html").write_bytes(b"previous private html\n")
        (out / "notes.txt").write_bytes(b"keep unrelated file\n")
        previous = {path.name: digest(path) for path in out.iterdir()}

    result = subprocess.run(
        [sys.executable, str(script), *arguments, "--out", str(out)],
        cwd=cwd, shell=False, check=False, capture_output=True,
        text=True, encoding="utf-8", errors="strict", timeout=30,
    )
    assert result.returncode == expected, result.stderr
    assert "Traceback" not in result.stderr
    assert {path.name: digest(path) for path in originals} == hashes
    if case == "stale":
        assert "--out already exists" in result.stderr
        assert "old reports were not read" in result.stderr
        assert result.stdout == ""
        assert {path.name: digest(path) for path in out.iterdir()} == previous
        return
    if case == "invalid":
        assert "score must be a finite number" in result.stderr
        assert "Local artifact:" not in result.stdout
        assert not out.exists()
        return

    assert result.stderr == ""
    assert (out / "report.html").is_file()
    report = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert f"Local artifact: {out / 'report.json'}" in result.stdout
    assert f"Local artifact: {out / 'report.html'}" in result.stdout
    assert report["schema_version"] == "0.1"
    assert report["protocol"]["unjudged"] == "unknown"
    assert report["protocol"]["qrels_complete"] is False
    if case == "error":
        assert any(finding["severity"] == "error" for finding in report["findings"])
        assert any(finding["code"] == "cross_run_label_mismatch" for finding in report["findings"])
        assert set(report["runs"]) == {"baseline", "candidate"}
        for run in report["runs"].values():
            assert run["audit"]["summary"]["assumed_nonrelevant_candidates"] == 0
    else:
        assert any(finding["severity"] == "warning" for finding in report["findings"])
        assert report["summary"]["unknown_candidates"] == 1
        assert report["summary"]["assumed_nonrelevant_candidates"] == 0
        assert report["metrics"]["ndcg@1"]["value"] is None
        assert report["metrics"]["mrr@1"]["value"] == 1
