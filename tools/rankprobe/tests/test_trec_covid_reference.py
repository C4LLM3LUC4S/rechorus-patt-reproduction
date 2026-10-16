"""Failure controls for the optional real-input reference checker."""

import hashlib
import importlib.util
from pathlib import Path
import sys

import pytest


@pytest.fixture
def checker():
    script = Path(__file__).resolve().parents[1] / "scripts" / "check_trec_covid.py"
    spec = importlib.util.spec_from_file_location("covid_reference_test_module", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Response:
    status = 200

    def __init__(self, content):
        self.content = content

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, limit):
        return self.content[:limit]


def fixture_source(checker, monkeypatch, content=b"expected input\n"):
    monkeypatch.setattr(checker, "FILES", ((
        "predictions.run", "https://example.invalid/predictions.run", len(content),
        hashlib.sha256(content).hexdigest(),
    ),))


def test_changed_remote_content_is_not_written(checker, monkeypatch, tmp_path):
    fixture_source(checker, monkeypatch)
    monkeypatch.setattr(checker, "urlopen", lambda *args, **kwargs: Response(b"tampered input\n"))
    destination = tmp_path / "inputs"
    with pytest.raises(ValueError):
        checker.fetch_inputs(destination)
    assert destination.is_dir()
    assert list(destination.iterdir()) == []


def test_oversized_response_is_not_written(checker, monkeypatch, tmp_path):
    fixture_source(checker, monkeypatch)
    monkeypatch.setattr(checker, "LIMIT", 16)
    monkeypatch.setattr(checker, "urlopen", lambda *args, **kwargs: Response(b"x" * 17))
    destination = tmp_path / "inputs"
    with pytest.raises(ValueError):
        checker.fetch_inputs(destination)
    assert list(destination.iterdir()) == []


def test_existing_input_directory_is_preserved_without_request(checker, monkeypatch, tmp_path):
    destination = tmp_path / "inputs"
    destination.mkdir()
    source = destination / "predictions.run"
    source.write_bytes(b"keep source")

    def unexpected_request(*args, **kwargs):
        raise AssertionError("existing destination must fail before network access")

    monkeypatch.setattr(checker, "urlopen", unexpected_request)
    with pytest.raises(OSError):
        checker.fetch_inputs(destination)
    assert source.read_bytes() == b"keep source"


@pytest.mark.parametrize("output", [
    "ndcg_cut_10 all 0.2000\n",
    "ndcg_cut_10 q1 0.2000\nndcg_cut_10 all 0.2000\nndcg_cut_10 q1 0.2000\n",
    "ndcg_cut_10 q1 nan\nndcg_cut_10 all 0.2000\n",
    "ndcg_cut_10 q1 0.3000\nndcg_cut_10 all 0.2000\n",
    "ndcg_cut_10 q1 0.2000\nndcg_cut_10 all 0.2000\nndcg_cut_5 q1 0.2000\n",
])
def test_incomplete_or_corrupt_native_results_fail(checker, output):
    expected = {("ndcg_cut_10", "q1"): 0.2, ("ndcg_cut_10", "all"): 0.2}
    with pytest.raises(ValueError):
        checker._compare_output(output, expected, "negative control")


def test_complete_native_results_use_declared_text_tolerance(checker):
    expected = {("ndcg_cut_10", "q1"): 0.200049, ("ndcg_cut_10", "all"): 0.2}
    count, error = checker._compare_output(
        "ndcg_cut_10 q1 0.2000\nndcg_cut_10 all 0.2000\n", expected, "text tolerance",
    )
    assert count == 2
    assert 0.000048 < error < 0.00005


def test_existing_summary_is_preserved_before_check(checker, monkeypatch, tmp_path):
    summary = tmp_path / "summary.json"
    summary.write_bytes(b"keep summary")
    monkeypatch.setattr(sys, "argv", [
        "check_trec_covid.py", "--trec-eval", str(tmp_path / "not-a-binary"),
        "--inputs-dir", str(tmp_path / "inputs"), "--summary", str(summary),
    ])

    def unexpected_check(*args, **kwargs):
        raise AssertionError("existing summary must fail before reference execution")

    monkeypatch.setattr(checker, "check_reference", unexpected_check)
    with pytest.raises(SystemExit) as exc:
        checker.main()
    assert exc.value.code == 2
    assert summary.read_bytes() == b"keep summary"
