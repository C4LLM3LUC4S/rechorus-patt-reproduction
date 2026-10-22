"""High-precision oracles for gain ratios near floating-point boundaries."""

from decimal import Decimal, localcontext
from fractions import Fraction
import math
import sys

import pytest

from rankprobe import Protocol, Row, audit_run, compare_runs, evaluate_metrics


MIN_SUBNORMAL = float.fromhex("0x0.0000000000001p-1022")


def decimal_ndcg(relevances, cutoff):
    # More than 324 decimal places are needed to subtract 1 after evaluating
    # exp(r * ln(2)) for the smallest positive binary64 relevance.
    with localcontext() as context:
        context.prec = 420
        log_two = Decimal(2).ln()

        def dcg(values):
            return sum(
                ((Decimal.from_float(value) * log_two).exp() - 1)
                / (Decimal(rank + 2).ln() / log_two)
                for rank, value in enumerate(values[:cutoff])
            )

        denominator = dcg(sorted(relevances, reverse=True))
        return float(dcg(relevances) / denominator) if denominator else 0.0


def test_subnormal_grades_do_not_erase_matched_pool_improvement():
    small, large = MIN_SUBNORMAL, 2 * MIN_SUBNORMAL
    report = compare_runs(
        {
            "small_first": [Row("q", "small", 2, small), Row("q", "large", 1, large)],
            "large_first": [Row("q", "small", 1, small), Row("q", "large", 2, large)],
        },
        Protocol(cutoffs=(1,), gain="exp2"),
    )
    matched = report["pairs"][0]["matched_pool_comparison"]
    expected = decimal_ndcg([small, large], 1)
    assert expected == 0.5
    assert matched["left_metrics"]["ndcg@1"]["value"] == expected
    assert matched["right_metrics"]["ndcg@1"]["value"] == 1.0
    assert matched["delta_right_minus_left"]["ndcg@1"]["delta"] == 1.0 - expected


@pytest.mark.parametrize(
    "small,large",
    [
        (MIN_SUBNORMAL, 4 * MIN_SUBNORMAL),
        (1e-300, 2e-300),
        (1e-12, 2e-12),
        (1.0, 3.0),
        (500.0, 511.999),
        (1e-160, 511.999),
    ],
)
def test_scaled_exp2_ndcg_agrees_with_decimal_across_gain_range(small, large):
    relevances = [0.0, small, large]
    result = evaluate_metrics(
        [Row("q", str(index), 3 - index, relevance) for index, relevance in enumerate(relevances)],
        Protocol(cutoffs=(1, 2, 3), gain="exp2"),
    )
    for cutoff in (1, 2, 3):
        expected = decimal_ndcg(relevances, cutoff)
        actual = result[f"ndcg@{cutoff}"]["value"]
        assert math.isclose(actual, expected, rel_tol=5e-14, abs_tol=4 * math.ulp(expected))


@pytest.mark.parametrize(
    "small,large",
    [
        (2.0**-46, 511.0),
        (2.0**-46, math.nextafter(512.0, 0.0)),
        (2.0**-46, 512.0),
        (2.0**-46, math.nextafter(512.0, math.inf)),
        (2.0**-46, 513.0),
        (2.0**-46, 1022.0),
        (2.0**-46, 1022.5),
        (2.0**-46, 1023.0),
        (0.5, 512.0),
        (0.5, 1022.0),
        (math.nextafter(1.0, 0.0), 1074.5),
        (math.nextafter(1.0, 0.0), 1075.0),
        (2.0**-52, 1022.0),
        (2.0**-53, 1022.0),
        (0.5, 1075.5),
    ],
)
def test_small_exp2_grades_match_definition_across_scaling_and_underflow(small, large):
    rows = [Row("q", "small", 2), Row("q", "large", 1)]
    qrels = {"q": {"small": small, "large": large}}
    original_rows, original_judgments = list(rows), dict(qrels["q"])
    result = evaluate_metrics(
        rows, Protocol(cutoffs=(1,), gain="exp2", qrels_complete=True), qrels,
    )["ndcg@1"]
    expected = decimal_ndcg([small, large], 1)
    actual = result["value"]
    assert result["status"] == "ok"
    if expected:
        assert actual > 0
    else:
        assert actual == 0
    # At .5/1022 the result differs from the definition by one subnormal ulp;
    # the calculation does not promise correct rounding for every input.
    assert math.isclose(actual, expected, rel_tol=5e-14, abs_tol=math.ulp(expected))
    assert rows == original_rows and qrels["q"] == original_judgments
    assert all(row.relevance is None for row in rows)


@pytest.mark.parametrize("largest", (int(sys.float_info.max), sys.float_info.max))
def test_small_grade_maximum_finite_reference_has_true_final_underflow(largest):
    result = evaluate_metrics(
        [Row("q", "returned", 1, 0.5)],
        Protocol(cutoffs=(1,), gain="exp2", qrels_complete=True),
        {"q": {"returned": 0.5, "unretrieved": largest}},
    )["ndcg@1"]
    # The numerator is below one and this denominator exceeds 2**1075,
    # so the ratio is below half the smallest positive binary64 value.
    assert result["value"] == 0
    assert result["status"] == "ok"


@pytest.mark.parametrize("largest", (1074, 1075, 1076))
def test_integer_exp2_grade_preserves_exact_subnormal_rounding_control(largest):
    result = evaluate_metrics(
        [Row("q", "returned", 1, 1)],
        Protocol(cutoffs=(1,), gain="exp2", qrels_complete=True),
        {"q": {"returned": 1, "unretrieved": largest}},
    )["ndcg@1"]
    assert result["value"] == float(Fraction(1, 2**largest - 1))


def test_small_positive_grades_keep_nonzero_matched_pool_delta():
    small = 2.0**-46
    runs = {
        "smaller_first": [Row("q", "a", 2), Row("q", "b", 1)],
        "larger_first": [Row("q", "a", 1), Row("q", "b", 2)],
    }
    qrels = {"q": {"a": small, "b": 2 * small, "unretrieved": 512.0}}
    result = compare_runs(
        runs, Protocol(cutoffs=(1,), gain="exp2", qrels_complete=True), qrels,
    )
    matched = result["pairs"][0]["matched_pool_comparison"]
    expected_left = decimal_ndcg([small, 512.0], 1)
    expected_right = decimal_ndcg([2 * small, 512.0], 1)
    expected_delta = expected_right - expected_left
    delta = matched["delta_right_minus_left"]["ndcg@1"]
    assert result["pairs"][0]["status"] == "comparable"
    assert matched["query_ids"] == ["q"]
    assert delta["status"] == "checked" and delta["delta"] > 0
    assert math.isclose(delta["delta"], expected_delta, rel_tol=5e-14)
    assert all(row.relevance is None for rows in runs.values() for row in rows)


def test_small_gain_fix_does_not_resolve_unknown_candidate_judgments():
    rows = [Row("q", "known", 2), Row("q", "unknown", 1)]
    qrels = {"q": {"known": 2.0**-46, "unknown": None, "unretrieved": 512.0}}
    result = audit_run(rows, Protocol(cutoffs=(1,), gain="exp2"), qrels)
    assert result["metrics"]["ndcg@1"]["value"] is None
    assert result["metrics"]["ndcg@1"]["excluded_query_ids"] == ["q"]
    assert result["summary"]["unknown_candidates"] == 1
    assert result["summary"]["assumed_nonrelevant_candidates"] == 0
    assert result["protocol"]["qrels_complete"] is False
    assert qrels["q"]["unknown"] is None
    assert all(row.relevance is None for row in rows)
