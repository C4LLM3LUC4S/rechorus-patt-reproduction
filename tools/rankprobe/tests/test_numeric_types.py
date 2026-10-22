"""Numeric inputs must remain usable through the documented report API."""

from fractions import Fraction
import json
import math
import re
import sys

import pytest

from rankprobe import Protocol, Row, audit_run
from rankprobe.report import write_report


def construct(field, value):
    if field == "score":
        return Row("q", "a", value, 1)
    if field == "relevance":
        return Row("q", "a", 1, value)
    return Protocol(cutoffs=(1,), relevance_threshold=value)


@pytest.mark.parametrize("field", ("score", "relevance", "relevance_threshold"))
def test_fraction_is_rejected_at_construction_with_conversion_hint(field):
    message = f"{field} must be a finite number (Python int or float)"
    with pytest.raises(ValueError, match=re.escape(message)):
        construct(field, Fraction(1, 2))


@pytest.mark.parametrize("field", ("score", "relevance", "relevance_threshold"))
@pytest.mark.parametrize("scalar_type", ("float32", "int64", "bool_"))
def test_numpy_scalars_outside_builtin_numeric_types_are_rejected_early(field, scalar_type):
    np = pytest.importorskip("numpy")
    value = getattr(np, scalar_type)(1)
    with pytest.raises(ValueError, match=re.escape(f"{field} must be a finite number")):
        construct(field, value)


@pytest.mark.parametrize("threshold", (.5, 2**53))
def test_builtin_threshold_reaches_both_report_outputs_without_losing_precision(tmp_path, threshold):
    grade = 1 if isinstance(threshold, float) else threshold + 1
    protocol = Protocol(cutoffs=(1,), relevance_threshold=threshold)
    report = audit_run([Row("q", "a", 2, grade)], protocol)
    json_path, html_path = write_report(report, tmp_path / "report")
    stored = json.loads(json_path.read_text(encoding="utf-8"))
    assert protocol.relevance_threshold is threshold
    assert stored["protocol"]["relevance_threshold"] == threshold
    assert type(stored["protocol"]["relevance_threshold"]) is type(threshold)
    assert stored["metrics"]["mrr@1"]["value"] == 1
    assert html_path.read_text(encoding="utf-8").startswith("<!doctype html>")


def test_serializable_numpy_float64_threshold_still_reaches_report(tmp_path):
    np = pytest.importorskip("numpy")
    value = np.float64(.5)
    if not isinstance(value, float):
        pytest.skip("This NumPy version does not make float64 a Python float subclass")
    protocol = Protocol(cutoffs=(1,), relevance_threshold=value)
    report = audit_run([Row("q", "a", np.float64(2), np.float64(1))], protocol)
    json_path, html_path = write_report(report, tmp_path / "report")
    assert protocol.relevance_threshold is value
    assert json.loads(json_path.read_text(encoding="utf-8"))["metrics"]["mrr@1"]["value"] == 1
    assert html_path.is_file()


class IntegerSubclass(int):
    pass


class FloatSubclass(float):
    pass


@pytest.mark.parametrize("scalar_type", (IntegerSubclass, FloatSubclass))
def test_builtin_numeric_subclasses_are_preserved_and_serializable(tmp_path, scalar_type):
    score, label, threshold = (scalar_type(value) for value in (2, 1, 0))
    row = Row("q", "a", score, label)
    protocol = Protocol(cutoffs=(1,), relevance_threshold=threshold)
    report = audit_run([row], protocol)
    json_path, html_path = write_report(report, tmp_path / "report")
    assert row.score is score
    assert row.relevance is label
    assert protocol.relevance_threshold is threshold
    assert json.loads(json_path.read_text(encoding="utf-8"))["metrics"]["mrr@1"]["value"] == 1
    assert html_path.is_file()


def test_finite_boundary_stays_exact_and_invalid_numbers_still_fail():
    largest = int(sys.float_info.max)
    row = Row("q", "a", largest, largest)
    protocol = Protocol(cutoffs=(1,), relevance_threshold=largest - 1)
    assert row.score == largest and type(row.score) is int
    assert row.relevance == largest and type(row.relevance) is int
    assert protocol.relevance_threshold == largest - 1
    assert audit_run([row], protocol)["metrics"]["mrr@1"]["value"] == 1
    for field in ("score", "relevance", "relevance_threshold"):
        for invalid in (True, float("nan"), float("inf"), -float("inf"), 10**400):
            with pytest.raises(ValueError, match="finite number"):
                construct(field, invalid)


def test_negative_zero_and_unknown_labels_are_not_normalized(tmp_path):
    row = Row("q", "a", -0.0)
    protocol = Protocol(cutoffs=(1,), relevance_threshold=-0.0)
    report = audit_run([row], protocol)
    json_path, _ = write_report(report, tmp_path / "report")
    stored = json.loads(json_path.read_text(encoding="utf-8"))
    assert math.copysign(1, row.score) == -1
    assert math.copysign(1, stored["protocol"]["relevance_threshold"]) == -1
    assert row.relevance is None
    assert stored["summary"]["unknown_candidates"] == 1
    assert stored["summary"]["assumed_nonrelevant_candidates"] == 0
    assert stored["metrics"]["mrr@1"]["value"] is None
