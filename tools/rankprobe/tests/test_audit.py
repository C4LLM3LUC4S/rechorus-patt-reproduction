import itertools
import json
import math
import unittest

from rankprobe.audit import audit_run, compare_runs
from rankprobe.model import Protocol, Row


def independent_metrics(order, cutoff, exp2=False):
    """Small direct oracle, deliberately independent from package helpers."""
    reciprocal = next(
        (1 / rank for rank, relevance in enumerate(order[:cutoff], 1) if relevance > 0), 0
    )
    gain = (lambda r: 2**r - 1) if exp2 else (lambda r: r)
    dcg = sum(gain(r) / math.log2(i + 2) for i, r in enumerate(order[:cutoff]))
    idcg = sum(
        gain(r) / math.log2(i + 2) for i, r in enumerate(sorted(order, reverse=True)[:cutoff])
    )
    return reciprocal, dcg / idcg if idcg else 0


class AuditTests(unittest.TestCase):
    def test_exact_tie_bounds_against_exhaustive_independent_oracle(self):
        # Two distinct score groups, a tie crossing k, graded judgments, and
        # a relevant item outside the first score group cover common mistakes.
        for exp2 in (False, True):
            rows = [
                Row("q", "a", 2, 0),
                Row("q", "b", 2, 2),
                Row("q", "c", 2, 1),
                Row("q", "d", 1, 3),
                Row("q", "e", 1, 0),
            ]
            report = audit_run(
                rows, Protocol(cutoffs=(1, 2, 3, 4, 5), gain="exp2" if exp2 else "linear")
            )
            permutations = [
                a + b
                for a in itertools.permutations((0, 2, 1))
                for b in itertools.permutations((3, 0))
            ]
            for cutoff in range(1, 6):
                expected = [independent_metrics(order, cutoff, exp2) for order in permutations]
                for index, prefix in enumerate(("mrr", "ndcg")):
                    bound = report["tie_analysis"]["metric_bounds"][f"{prefix}@{cutoff}"]
                    self.assertAlmostEqual(bound["min"], min(pair[index] for pair in expected))
                    self.assertAlmostEqual(bound["max"], max(pair[index] for pair in expected))

    def test_mrr_tie_at_cutoff_can_range_from_zero_to_one(self):
        rows = [Row("q", "a", 0, 0), Row("q", "b", 0, 1)]
        report = audit_run(rows, Protocol(cutoffs=(1, 2)))
        self.assertEqual(report["tie_analysis"]["metric_bounds"]["mrr@1"]["min"], 0)
        self.assertEqual(report["tie_analysis"]["metric_bounds"]["mrr@1"]["max"], 1)
        self.assertEqual(report["tie_analysis"]["metric_bounds"]["mrr@2"]["min"], 0.5)
        self.assertEqual(
            report["tie_analysis"]["input_order_probe"]["delta_reversed_minus_original"]["mrr@1"][
                "delta"
            ],
            1,
        )

    def test_tie_bounds_do_not_pretend_unknown_labels_are_zero(self):
        report = audit_run([Row("q", "a", 0), Row("q", "b", 0, 1)], Protocol(cutoffs=(1,)))
        bound = report["tie_analysis"]["metric_bounds"]["mrr@1"]
        self.assertIsNone(bound["min"])
        self.assertEqual(bound["status"], "not_checked")
        self.assertEqual(bound["evaluated_queries"], 0)

    def test_exact_recall_bounds_and_macro_averages(self):
        rows = [Row("q", "a", 0, 0), Row("q", "b", 0, 1), Row("other", "c", 1, 1)]
        qrels = {"q": {"a": 0, "b": 1, "missing": 1}, "other": {"c": 1}}
        report = audit_run(rows, Protocol(cutoffs=(1,), qrels_complete=True), qrels)
        bounds = report["tie_analysis"]["metric_bounds"]["recall@1"]
        self.assertEqual(bounds["min"], 0.5)
        self.assertEqual(bounds["max"], 0.75)

    def test_duplicate_counterfactual_is_labeled_invalid_and_uses_max_score(self):
        rows = [Row("q", "b", 3, 1), Row("q", "b", 2, 1), Row("q", "a", 1, 0)]
        report = audit_run(rows, Protocol(cutoffs=(2,)))
        self.assertEqual(report["summary"]["unique_candidates"], 2)
        self.assertEqual(report["duplicates"]["conflicting_scores"], 1)
        self.assertEqual(report["duplicates"]["examples"][0]["selected_score"], 3)
        sensitivity = report["duplicates"]["metric_sensitivity"]
        self.assertGreater(sensitivity["raw_rows"]["ndcg@2"]["value"], 1)
        self.assertIn("not a valid ranking", sensitivity["reason"])

    def test_constant_score_negative_control_and_no_input_mutation(self):
        rows = [Row("q", "b", 3, 1), Row("q", "a", 1, 0)]
        before = list(rows)
        report = audit_run(rows, Protocol(cutoffs=(1,)))
        negative = report["negative_controls"]["constant_scores"]
        self.assertEqual(negative["metrics"]["mrr@1"]["value"], 0)
        self.assertEqual(negative["input_order_metrics"]["mrr@1"]["value"], 1)
        self.assertEqual(rows, before)
        self.assertIn("not model performance", negative["reason"])

    def test_missing_qrels_query_is_explicit(self):
        report = audit_run(
            [Row("absent", "a", 1, 1)],
            Protocol(cutoffs=(1,), qrels_complete=True),
            {"present": {"a": 1}},
        )
        self.assertTrue(all(metric["value"] is None for metric in report["metrics"].values()))
        self.assertIn("missing_qrels_queries", [f["code"] for f in report["findings"]])

    def test_findings_do_not_assert_ties_are_bugs(self):
        report = audit_run([Row("q", "a", 1, 1), Row("q", "b", 1, 1)], Protocol(cutoffs=(1,)))
        self.assertIn("score_ties", [f["code"] for f in report["findings"]])
        self.assertEqual(report["tie_analysis"]["metric_bounds"]["mrr@1"]["width"], 0)

    def test_compare_identical_candidate_pools_and_delta(self):
        runs = {
            "bad": [Row("q", "a", 2, 0), Row("q", "b", 1, 1)],
            "good": [Row("q", "a", 1, 0), Row("q", "b", 2, 1)],
        }
        report = compare_runs(runs, Protocol(cutoffs=(1,)))
        pair = report["pairs"][0]
        self.assertEqual(pair["status"], "comparable")
        self.assertEqual(
            pair["matched_pool_comparison"]["delta_right_minus_left"]["mrr@1"]["delta"], 1
        )

    def test_compare_includes_each_runs_tie_and_duplicate_warnings(self):
        rows = [Row("q", "a", 0, 0), Row("q", "b", 0, 1), Row("q", "b", 0, 1)]
        report = compare_runs({"a": rows, "b": list(rows)}, Protocol(cutoffs=(1,)))
        self.assertEqual(report["pairs"][0]["status"], "comparable")
        self.assertIn("tie_analysis", report["runs"]["a"]["audit"])
        warnings = [f for f in report["findings"] if f["severity"] == "warning"]
        self.assertEqual({f["run_name"] for f in warnings}, {"a", "b"})
        self.assertIn("score_ties", {f["code"] for f in warnings})
        self.assertIn("duplicate_candidates", {f["code"] for f in warnings})

    def test_compare_different_query_and_candidate_pools_is_restricted(self):
        runs = {
            "a": [Row("same", "x", 1, 1), Row("diff", "x", 1, 1), Row("only_a", "x", 1, 1)],
            "b": [Row("same", "x", 1, 1), Row("diff", "y", 1, 1)],
        }
        report = compare_runs(runs, Protocol(cutoffs=(1,)))
        pair = report["pairs"][0]
        self.assertEqual(pair["status"], "partially_comparable")
        self.assertEqual(pair["matched_pool_comparison"]["query_ids"], ["same"])
        self.assertEqual(pair["candidate_sets"]["differing_queries"], 1)
        self.assertEqual(pair["query_coverage"]["left_only"], ["only_a"])

    def test_compare_labels_and_unknown_availability_are_not_interchangeable(self):
        for relevance in (0, None):
            report = compare_runs(
                {"a": [Row("q", "x", 1, 1)], "b": [Row("q", "x", 1, relevance)]},
                Protocol(cutoffs=(1,)),
            )
            self.assertEqual(report["pairs"][0]["status"], "not_comparable")
            self.assertEqual(report["pairs"][0]["label_consistency"]["conflicts"], 1)
            self.assertIn("cross_run_label_mismatch", [f["code"] for f in report["findings"]])

    def test_compare_requires_at_least_two_runs(self):
        with self.assertRaises(ValueError):
            compare_runs({"one": []}, Protocol())

    def test_empty_and_huge_tie_reports_are_finite_json(self):
        json.dumps(audit_run([], Protocol()), allow_nan=False)
        # A large group would be impossible to enumerate, but analytical bounds
        # need only sorting. This also checks bounded evidence examples.
        rows = [Row("q", str(i), 0, i % 4) for i in range(1500)]
        report = audit_run(rows, Protocol(cutoffs=(10,)))
        self.assertEqual(report["tie_analysis"]["tie_groups"], 1)
        self.assertLessEqual(len(report["tie_analysis"]["examples"][0]["item_ids"]), 10)
        json.dumps(report, allow_nan=False)


if __name__ == "__main__":
    unittest.main()
