"""Test bounded reference-output and pre-execution guards without running Perl."""

from copy import deepcopy
import hashlib
import importlib.util
from pathlib import Path
import sys

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/check_gdeval_policy.py"
SPEC = importlib.util.spec_from_file_location("check_gdeval_policy", SCRIPT)
checker = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = checker
SPEC.loader.exec_module(checker)
HEADER = "runid,topic,ndcg@1,err@1\n"
CASES = ("baseline_default", "baseline_complete", "spam_first", "unknown_first", "zero_first")


def policy_outputs():
    outputs = {}
    for name in CASES:
        query = 1 if name.startswith("baseline_") else 0
        mean = .5 if name == "baseline_complete" else query
        outputs[name] = checker.parse_output(
            HEADER + f"policy,1,{query},0.125\npolicy,amean,{mean},0.25\n"
        )
    return outputs


def test_csv_parser_retains_zero_values_and_separate_err_without_native_execution():
    assert checker.parse_output(HEADER + "original,1,0,0.125\noriginal,amean,0,0.25\n") == {
        "1": {"runid": "original", "ndcg": 0.0, "err": .125},
        "amean": {"runid": "original", "ndcg": 0.0, "err": .25},
    }


@pytest.mark.parametrize("text", [
    "", HEADER,
    "runid,topic,ndcg@2,err@1\noriginal,1,1,0.1\n",
    HEADER + "original,1,1\n",
    HEADER + "original,1,1,0.1,extra\n",
    HEADER + "original,1,1,0.1\noriginal,1,0,0.1\n",
    HEADER + "original,1,NaN,0.1\n",
    HEADER + "original,1,1,inf\n",
    HEADER + "original,1,1e999,0.1\n",
    HEADER + "original,1,not-a-number,0.1\n",
    HEADER + "original,1,1,0.1\nanother,amean,1,0.1\n",
])
def test_csv_parser_rejects_malformed_duplicate_or_nonfinite_output(text):
    with pytest.raises(checker.GateError):
        checker.parse_output(text)


def test_policy_accepts_distinct_default_and_complete_means_without_certifying_err():
    outputs = policy_outputs()
    before = deepcopy(outputs)
    observations = checker.validate_policy(outputs)
    assert observations["reported_topic_ids"] == {name: ["1"] for name in CASES}
    assert observations["mean_ndcg_at_1"] == {
        "baseline_default": 1, "baseline_complete": .5,
        "spam_first": 0, "unknown_first": 0, "zero_first": 0,
    }
    assert observations["baseline_topic_ndcg_at_1"] == {
        "baseline_default": 1, "baseline_complete": 1,
    }
    assert observations["nonpositive_first_ndcg_at_1"] == {
        "spam_first": 0, "unknown_first": 0, "zero_first": 0,
    }
    assert observations["missing_run_positive_topic"] == "2"
    assert observations["nonpositive_only_run_topic"] == "3"
    assert outputs == before


def test_valid_zero_csv_cannot_pass_the_policy_gate():
    parsed = checker.parse_output(HEADER + "policy,1,0,0\npolicy,amean,0,0\n")
    with pytest.raises(checker.GateError):
        checker.validate_policy({name: deepcopy(parsed) for name in CASES})


@pytest.mark.parametrize("name, topic, wrong_value", [
    ("baseline_default", "1", .5),
    ("baseline_default", "amean", .5),
    ("baseline_complete", "1", .5),
    ("baseline_complete", "amean", 1),
    ("spam_first", "1", .5),
    ("unknown_first", "amean", .5),
    ("zero_first", "amean", 1),
])
def test_policy_rejects_wrong_per_topic_values_or_averaging(name, topic, wrong_value):
    outputs = policy_outputs()
    outputs[name][topic]["ndcg"] = wrong_value
    with pytest.raises(checker.GateError):
        checker.validate_policy(outputs)


@pytest.mark.parametrize("topic", ["2", "3"])
def test_complete_mean_does_not_make_unreturned_or_nonpositive_topics_output_rows(topic):
    outputs = policy_outputs()
    outputs["baseline_complete"][topic] = {"runid": "policy", "ndcg": 0, "err": 0}
    with pytest.raises(checker.GateError):
        checker.validate_policy(outputs)


def test_policy_requires_all_five_cases_and_the_mean_row():
    outputs = policy_outputs()
    del outputs["unknown_first"]
    with pytest.raises(checker.GateError):
        checker.validate_policy(outputs)
    outputs = policy_outputs()
    del outputs["baseline_default"]["amean"]
    with pytest.raises(checker.GateError):
        checker.validate_policy(outputs)


def unexpected_perl(*args, **kwargs):
    pytest.fail("Perl must not start before source/output preflight passes")


def test_existing_output_is_preserved_before_perl_can_start(tmp_path, monkeypatch):
    source = tmp_path / "source script.pl"
    source.write_bytes(b"inert source placeholder\n")
    out = tmp_path / "existing output"
    out.mkdir()
    sentinel = out / "keep.txt"
    sentinel.write_bytes(b"existing private output\n")
    before = hashlib.sha256(sentinel.read_bytes()).hexdigest()
    monkeypatch.setattr(checker.subprocess, "run", unexpected_perl)
    with pytest.raises(checker.GateError):
        checker.check_policy(source, "unused-perl", out)
    assert hashlib.sha256(sentinel.read_bytes()).hexdigest() == before
    assert list(out.iterdir()) == [sentinel]


def test_wrong_source_hash_is_rejected_before_perl_can_start(tmp_path, monkeypatch):
    source = tmp_path / "changed script.pl"
    source.write_bytes(b"not the pinned reference\n")
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    assert before != checker.SOURCE_SHA256
    out = tmp_path / "fresh output"
    monkeypatch.setattr(checker.subprocess, "run", unexpected_perl)
    with pytest.raises(checker.GateError):
        checker.check_policy(source, "unused-perl", out)
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before
    assert not out.exists()
