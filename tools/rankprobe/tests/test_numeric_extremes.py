"""High-precision oracles for gain ratios near floating-point boundaries."""

from decimal import Decimal, localcontext
import math

import pytest

from rankprobe import Protocol, Row, compare_runs, evaluate_metrics


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
