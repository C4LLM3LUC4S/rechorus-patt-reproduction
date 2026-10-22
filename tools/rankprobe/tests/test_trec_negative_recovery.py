"""Unsupported source grades stay rejected; structure-only recovery keeps unknowns."""

import hashlib
import json
import subprocess
import sys

import pytest

from rankprobe.io import read_qrels


def hashes(*paths):
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}


@pytest.fixture
def source_files(tmp_path):
    folder = tmp_path / "original source files"
    folder.mkdir()
    run = folder / "scores.run"
    run.write_text("qA Q0 dA 1 2 original\nqA Q0 dB 2 1 original\n", encoding="utf-8")
    qrels = folder / "source annotations.qrels"
    qrels.write_text(
        "# Original invented source annotations\n\nqA 0 dA -2\nqA 0 dB 0\n",
        encoding="utf-8",
    )
    return run, qrels


def invoke(tmp_path, *arguments):
    return subprocess.run(
        [sys.executable, "-m", "rankprobe", *map(str, arguments)],
        cwd=tmp_path, shell=False, check=False, capture_output=True,
        text=True, encoding="utf-8", errors="strict", timeout=30,
    )


@pytest.mark.parametrize(
    "options", [(), ("--unjudged", "nonrelevant"), ("--qrels-complete",)]
)
def test_unsupported_negative_grade_is_not_repaired_by_protocol_flags(
    tmp_path, source_files, options
):
    run, qrels = source_files
    before = hashes(run, qrels)
    destination = tmp_path / "fresh rejected report"

    result = invoke(
        tmp_path, "audit", run, "--qrels", qrels, "--out", destination, *options,
    )

    assert result.returncode == 2
    assert result.stdout == ""
    assert "source annotations.qrels:3:" in result.stderr
    assert "TREC relevance must be non-negative or -1 (unjudged)" in result.stderr
    assert "Other negative values may be source-specific annotations" in result.stderr
    assert "--unjudged does not reinterpret them" in result.stderr
    assert (
        "https://github.com/C4LLM3LUC4S/rechorus-patt-reproduction/"
        "blob/main/tools/rankprobe/docs/input-format.md"
        "#source-specific-negative-judgments"
    ) in result.stderr
    assert "Traceback" not in result.stderr
    assert not destination.exists()
    assert hashes(run, qrels) == before


def test_accepted_unknown_zero_and_positive_grades_keep_their_meanings(tmp_path):
    source = tmp_path / "ordinary judgments.qrels"
    source.write_text("qA 0 unknown -1\nqA 0 zero 0\nqA 0 positive 2\n", encoding="utf-8")
    before = hashes(source)

    assert read_qrels(source) == {"qA": {"unknown": None, "zero": 0, "positive": 2}}
    assert hashes(source) == before


def test_omitting_unsupported_qrels_audits_only_prediction_structure(tmp_path, source_files):
    run, qrels = source_files
    before = hashes(run, qrels)
    destination = tmp_path / "fresh structure report"

    result = invoke(tmp_path, "audit", run, "--cutoffs", "1", "--out", destination)

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert (destination / "report.html").is_file()
    report = json.loads((destination / "report.json").read_text(encoding="utf-8"))
    assert report["protocol"]["unjudged"] == "unknown"
    assert report["protocol"]["qrels_complete"] is False
    assert report["summary"]["rows"] == 2
    assert report["summary"]["unknown_candidates"] == 2
    assert report["summary"]["judged_candidates"] == 0
    assert report["summary"]["assumed_nonrelevant_candidates"] == 0
    assert report["summary"]["explicit_unjudged_qrels"] == 0
    assert report["summary"]["qrels_queries"] is None
    assert all(metric["value"] is None for metric in report["metrics"].values())
    assert all(metric["status"] == "not_checked" for metric in report["metrics"].values())
    sources = report["provenance"]["sources"]
    assert len(sources) == 1
    assert sources[0]["role"] == "predictions"
    assert sources[0]["filename"] == run.name
    assert sources[0]["sha256"] == before[run.name]
    assert sources[0]["input_format"] == "trec"
    assert hashes(run, qrels) == before
