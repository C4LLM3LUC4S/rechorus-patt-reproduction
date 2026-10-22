"""Parser depth failures remain recoverable input errors, not audit findings."""

import json
import subprocess
import sys

import pytest

from rankprobe import Row
from rankprobe.io import InputError, read_predictions, read_qrels


def records(kind):
    if kind == "predictions":
        return [
            {"query_id": "q-01", "item_id": "a", "score": 9007199254740993, "relevance": 1},
            {"query_id": "q-01", "item_id": "b", "score": 9007199254740992, "relevance": None},
        ]
    return [
        {"query_id": "q-01", "item_id": "a", "relevance": 1},
        {"query_id": "q-01", "item_id": "b", "relevance": 0},
    ]


def write_deep(path, kind):
    first, second = records(kind)
    nesting = "[" * 10000 + "0" + "]" * 10000
    path.write_text(
        json.dumps(first) + "\n" + json.dumps(second)[:-1] + ', "metadata":' + nesting + "}\n",
        encoding="utf-8",
    )


def loader(kind):
    return read_predictions if kind == "predictions" else read_qrels


@pytest.mark.parametrize("kind", ["predictions", "qrels"])
def test_json_depth_error_names_file_line_and_preserves_source(tmp_path, kind):
    source = tmp_path / f"{kind}.jsonl"
    write_deep(source, kind)
    original, recursion_limit = source.read_bytes(), sys.getrecursionlimit()
    with pytest.raises(InputError) as failure:
        loader(kind)(source)
    message = str(failure.value)
    assert message.startswith(f"{source}:2: JSON nesting is too deep")
    assert "new flat JSONL" in message and "original unchanged" in message
    assert ("score" in message) == (kind == "predictions")
    assert source.read_bytes() == original
    assert sys.getrecursionlimit() == recursion_limit


@pytest.mark.parametrize("kind", ["predictions", "qrels"])
def test_actual_cli_can_retry_flat_export_without_output_from_failure(tmp_path, kind):
    source = tmp_path / f"original-{kind}.jsonl"
    write_deep(source, kind)
    original = source.read_bytes()
    out = tmp_path / "report"
    predictions = tmp_path / "predictions.csv"
    predictions.write_text(
        "query_id,item_id,score\nq-01,a,3\nq-01,b,2\nq-01,c,1\n", encoding="utf-8",
    )

    def run(path):
        arguments = [str(path)] if kind == "predictions" else [
            str(predictions), "--qrels", str(path),
        ]
        return subprocess.run(
            [sys.executable, "-m", "rankprobe", "audit", *arguments,
             "--out", str(out), "--cutoffs", "1", "--fail-on", "never"],
            capture_output=True, text=True, encoding="utf-8", timeout=30, check=False,
        )

    failed = run(source)
    assert failed.returncode == 2
    assert "JSON nesting is too deep" in failed.stderr
    assert "Traceback" not in failed.stderr
    assert failed.stdout == "" and not out.exists()
    assert source.read_bytes() == original

    flat = tmp_path / f"flat-{kind}.jsonl"
    flat.write_text("".join(json.dumps(row) + "\n" for row in records(kind)), encoding="utf-8")
    expected = (
        [Row("q-01", "a", 9007199254740993, 1), Row("q-01", "b", 9007199254740992)]
        if kind == "predictions" else {"q-01": {"a": 1, "b": 0}}
    )
    assert loader(kind)(flat) == expected
    recovered = run(flat)
    assert recovered.returncode == 0, recovered.stderr
    assert recovered.stderr == "" and (out / "report.html").is_file()
    report = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert report["metrics"]["mrr@1"]["value"] == 1
    assert report["summary"]["unknown_candidates"] == 1
    assert report["summary"]["assumed_nonrelevant_candidates"] == 0
    assert report["protocol"]["qrels_complete"] is False
    assert source.read_bytes() == original


@pytest.mark.parametrize("kind", ["predictions", "qrels"])
def test_supported_nested_metadata_keeps_evaluation_values(tmp_path, kind):
    flat, nested = tmp_path / "flat.jsonl", tmp_path / "nested.jsonl"
    original = records(kind)
    flat.write_text("".join(json.dumps(row) + "\n" for row in original), encoding="utf-8")
    nested.write_text(
        "".join(json.dumps({**row, "metadata": {"source": ["original", {"split": "test"}]}})
                + "\n" for row in original), encoding="utf-8",
    )
    assert loader(kind)(nested) == loader(kind)(flat)
