"""Reject a whole-retrieval delta when its native protocol or topics differ."""

from copy import deepcopy
import hashlib
import importlib.util
from pathlib import Path

import pytest


@pytest.fixture
def checker():
    path = Path(__file__).resolve().parents[1] / "scripts" / "check_trec_covid.py"
    spec = importlib.util.spec_from_file_location("covid_pair_test_module", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def results():
    left = {
        "status": "passed",
        "reference_version": "control",
        "reference_binary_sha256": "same-control-binary",
        "shared_protocol": {
            "cutoffs": [1, 5, 10], "gain": "linear", "relevance_threshold": 0,
            "unjudged": "nonrelevant", "qrels_complete": False,
            "ndcg_reference": "known_qrels_pool",
            "tie_adapter": "new descending ASCII docno view; input tie policy",
            "query_ids": sorted(str(i) for i in range(1, 31)),
        },
        "nonrelevant_native_docno": {}, "native_macro_as_printed": {},
    }
    for prefix in ("mrr", "ndcg"):
        for cutoff in (1, 5, 10):
            key = f"{prefix}@{cutoff}"
            left["nonrelevant_native_docno"][key] = {
                "value": 0.20002, "evaluated_queries": 30, "total_queries": 30,
                "status": "partial",
                "reference": "submitted_candidates" if prefix == "mrr" else "known_qrels_pool",
            }
            left["native_macro_as_printed"][key] = 0.2
    right = deepcopy(left)
    for metric in right["nonrelevant_native_docno"].values():
        metric["value"] = 0.30001
    right["native_macro_as_printed"] = dict.fromkeys(left["native_macro_as_printed"], 0.3)
    return left, right


def test_separate_end_to_end_delta_records_native_rounding(checker):
    left, right = results()
    before = deepcopy((left, right))
    result = checker._end_to_end_summary(left, right)
    value = result["macro_difference_dfr_minus_lmd"]["mrr@10"]
    assert value["delta"] == pytest.approx(0.09999)
    assert value["native_delta_as_printed"] == pytest.approx(0.1)
    assert value["native_delta_absolute_tolerance"] == 2 * checker.ABSOLUTE_TOLERANCE
    assert result["query_count"] == 30
    assert "not a matched-pool delta" in result["scope"]
    assert (left, right) == before


@pytest.mark.parametrize("field,value", [
    ("gain", "exp2"), ("unjudged", "unknown"), ("qrels_complete", True),
    ("tie_adapter", "ascending IDs"), ("query_ids", ["1"]),
])
def test_protocol_drift_rejects_end_to_end_delta(checker, field, value):
    left, right = results()
    right["shared_protocol"][field] = value
    with pytest.raises(ValueError):
        checker._end_to_end_summary(left, right)


@pytest.mark.parametrize("field,value", [
    ("evaluated_queries", 29), ("total_queries", 31), ("value", None),
    ("reference", "complete_qrels"),
])
def test_partial_population_or_changed_reference_rejects_delta(checker, field, value):
    left, right = results()
    right["nonrelevant_native_docno"]["ndcg@10"][field] = value
    with pytest.raises(ValueError):
        checker._end_to_end_summary(left, right)


@pytest.mark.parametrize("change", ["binary", "failed", "missing_macro", "wrong_macro"])
def test_native_evidence_must_agree_before_delta(checker, change):
    left, right = results()
    if change == "binary":
        right["reference_binary_sha256"] = "other-binary"
    elif change == "failed":
        right["status"] = "failed"
    elif change == "missing_macro":
        del right["native_macro_as_printed"]["mrr@10"]
    else:
        right["native_macro_as_printed"]["mrr@10"] = 0.9
    with pytest.raises(ValueError):
        checker._end_to_end_summary(left, right)


def test_third_source_is_verified_before_native_execution(checker, monkeypatch, tmp_path):
    content = b"fixed source\n"
    def source(name):
        return (name, "https://example.invalid/" + name, len(content),
                hashlib.sha256(content).hexdigest())
    monkeypatch.setattr(checker, "FILES", (source("lmd"), source("qrels")))
    monkeypatch.setattr(checker, "DFR_FILE", source("dfr"))
    for name in ("lmd", "qrels", "dfr"):
        (tmp_path / name).write_bytes(content)
    (tmp_path / "dfr").write_bytes(b"wrong source\n")
    def unexpected(*args, **kwargs):
        raise AssertionError("native execution preceded input verification")
    monkeypatch.setattr(checker, "check_reference", unexpected)
    with pytest.raises(ValueError, match="SHA256"):
        checker.check_pair(tmp_path / "not-a-binary", tmp_path)
    assert (tmp_path / "dfr").read_bytes() == b"wrong source\n"
