"""Independent completion oracle and compatibility checks for a4 MRR."""

import copy
from itertools import product
import math
import unittest

from rankprobe.audit import audit_run
from rankprobe.metrics import evaluate_metrics, metric_deltas
from rankprobe.model import Protocol, Row


RULE = "known_first_relevant_prefix"


def direct_rr(labels, cutoff, threshold=0):
    """Definition of RR on fully specified labels, without package helpers."""
    for rank, label in enumerate(labels[:cutoff], 1):
        if label > threshold:
            return 1.0 / rank
    return 0.0


def completion_bounds(labels, cutoff):
    unknown = [index for index, label in enumerate(labels) if label is None]
    values = []
    for replacements in product((0, 1), repeat=len(unknown)):
        completed = list(labels)
        for index, replacement in zip(unknown, replacements):
            completed[index] = replacement
        values.append(direct_rr(completed, cutoff))
    return min(values), max(values)


class MrrIdentifiabilityTests(unittest.TestCase):
    def test_all_small_partial_labels_against_independent_completion_bounds(self):
        cases = 0
        cutoffs = tuple(range(1, 6))
        for length in range(1, 5):
            for labels in product((0, 1, None), repeat=length):
                rows = [
                    Row("q", f"item{index}", length - index, label)
                    for index, label in enumerate(labels)
                ]
                before = [(row.query_id, row.item_id, row.score, row.relevance) for row in rows]
                metrics = evaluate_metrics(rows, Protocol(cutoffs=cutoffs))
                for cutoff in cutoffs:
                    cases += 1
                    low, high = completion_bounds(labels, cutoff)
                    metric = metrics[f"mrr@{cutoff}"]
                    with self.subTest(labels=labels, cutoff=cutoff, bounds=(low, high)):
                        self.assertEqual(metric["eligibility_rule"], RULE)
                        self.assertEqual(metric["total_queries"], 1)
                        if low == high:
                            self.assertAlmostEqual(metric["value"], low, places=14)
                            self.assertEqual(metric["eligible_query_ids"], ["q"])
                            self.assertEqual(metric["excluded_query_ids"], [])
                            self.assertEqual(metric["evaluated_queries"], 1)
                            self.assertEqual(metric["excluded_queries"], 0)
                        else:
                            self.assertIsNone(metric["value"])
                            self.assertEqual(metric["status"], "not_checked")
                            self.assertEqual(metric["eligible_query_ids"], [])
                            self.assertEqual(metric["excluded_query_ids"], ["q"])
                            self.assertEqual(metric["evaluated_queries"], 0)
                            self.assertEqual(metric["excluded_queries"], 1)
                self.assertEqual(
                    [(row.query_id, row.item_id, row.score, row.relevance) for row in rows], before
                )
                self.assertEqual(tuple(row.relevance for row in rows), labels)
        self.assertEqual(cases, 600)

    def test_nonzero_threshold_uses_strictly_greater_labels(self):
        cases = (
            ((1, 2, None), 3, 0.5),
            ((1, None, 2), 3, None),
            ((1, 1), 5, 0.0),
            ((2, None), 2, 1.0),
            ((1, 2, None), 1, 0.0),
        )
        for labels, cutoff, expected in cases:
            with self.subTest(labels=labels, cutoff=cutoff):
                rows = [Row("q", str(i), len(labels) - i, label)
                        for i, label in enumerate(labels)]
                metric = evaluate_metrics(
                    rows, Protocol(cutoffs=(cutoff,), relevance_threshold=1)
                )[f"mrr@{cutoff}"]
                self.assertEqual(metric["eligibility_rule"], RULE)
                self.assertEqual(metric["value"], expected)
                self.assertEqual(metric["eligible_query_ids"], [] if expected is None else ["q"])
                self.assertEqual(tuple(row.relevance for row in rows), labels)

    def test_tie_policy_fixes_order_before_mrr_identifiability(self):
        rows = [Row("q", "z_unknown", 1), Row("q", "a_positive", 1, 1)]
        before = list(rows)
        for tie_policy, expected in (("item_id", 1.0), ("input", None)):
            with self.subTest(tie_policy=tie_policy):
                report = audit_run(rows, Protocol(cutoffs=(1, 2), tie_policy=tie_policy))
                for cutoff in (1, 2):
                    self.assertEqual(report["metrics"][f"mrr@{cutoff}"]["value"], expected)
                    self.assertEqual(report["metrics"][f"mrr@{cutoff}"]["eligibility_rule"], RULE)
                    bound = report["tie_analysis"]["metric_bounds"][f"mrr@{cutoff}"]
                    self.assertEqual(bound["status"], "not_checked")
                    self.assertIsNone(bound["min"])
                    self.assertIsNone(bound["max"])
                self.assertEqual(report["summary"]["unknown_candidates"], 1)
                self.assertEqual(report["summary"]["assumed_nonrelevant_candidates"], 0)
        reversed_metric = evaluate_metrics(
            list(reversed(rows)), Protocol(cutoffs=(2,), tie_policy="input")
        )["mrr@2"]
        self.assertEqual(reversed_metric["value"], 1.0)
        self.assertEqual(rows, before)
        self.assertIsNone(rows[0].relevance)

    def test_qrels_resolution_preserves_unknown_counts_and_other_metric_boundaries(self):
        rows = [Row("q", "positive", 3), Row("q", "explicit_unknown", 2),
                Row("q", "absent", 1)]
        qrels = {"q": {"positive": 1, "explicit_unknown": None, "unretrieved": 2}}
        before_rows, before_qrels = list(rows), copy.deepcopy(qrels)
        report = audit_run(rows, Protocol(cutoffs=(1, 3)), qrels)
        summary = report["summary"]
        self.assertEqual(summary["judged_candidates"], 1)
        self.assertEqual(summary["resolved_candidates"], 1)
        self.assertEqual(summary["unknown_candidates"], 2)
        self.assertEqual(summary["assumed_nonrelevant_candidates"], 0)
        self.assertEqual(summary["implicit_complete_qrels_zeros"], 0)
        self.assertEqual(summary["explicit_unjudged_qrels_candidates"], 1)
        self.assertFalse(report["protocol"]["qrels_complete"])
        for cutoff in (1, 3):
            self.assertEqual(report["metrics"][f"mrr@{cutoff}"]["value"], 1.0)
            self.assertEqual(report["metrics"][f"mrr@{cutoff}"]["eligibility_rule"], RULE)
            for prefix in ("ndcg", "recall"):
                metric = report["metrics"][f"{prefix}@{cutoff}"]
                self.assertIsNone(metric["value"])
                self.assertEqual(metric["status"], "not_checked")
                self.assertNotIn("eligibility_rule", metric)
            for bound in report["tie_analysis"]["metric_bounds"].values():
                self.assertEqual(bound["status"], "not_checked")
                self.assertIsNone(bound["min"])
                self.assertIsNone(bound["max"])

        assumed = audit_run(rows, Protocol(cutoffs=(1, 3), unjudged="nonrelevant"), qrels)
        self.assertEqual(assumed["summary"]["judged_candidates"], 1)
        self.assertEqual(assumed["summary"]["unknown_candidates"], 0)
        self.assertEqual(assumed["summary"]["assumed_nonrelevant_candidates"], 2)
        self.assertFalse(assumed["protocol"]["qrels_complete"])
        self.assertEqual(assumed["metrics"]["mrr@3"]["value"], 1.0)
        self.assertEqual(assumed["metrics"]["mrr@3"]["eligibility_rule"], RULE)
        self.assertEqual(assumed["metrics"]["mrr@3"]["status"], "partial")
        self.assertAlmostEqual(assumed["metrics"]["ndcg@1"]["value"], 0.5)
        self.assertAlmostEqual(
            assumed["metrics"]["ndcg@3"]["value"], 1 / (2 + 1 / math.log2(3))
        )
        self.assertEqual(assumed["metrics"]["ndcg@3"]["reference"], "known_qrels_pool")
        self.assertEqual(assumed["metrics"]["ndcg@3"]["status"], "partial")
        self.assertIsNone(assumed["metrics"]["recall@3"]["value"])
        self.assertEqual(rows, before_rows)
        self.assertTrue(all(row.relevance is None for row in rows))
        self.assertEqual(qrels, before_qrels)

    def test_source_unknown_does_not_erase_inline_positive_or_override_known_qrels(self):
        rows = [Row("q", "inline", 2, 2), Row("q", "unknown", 1)]
        qrels = {"q": {"inline": None, "unknown": None}}
        report = audit_run(rows, Protocol(cutoffs=(2,)), qrels)
        self.assertEqual(report["metrics"]["mrr@2"]["value"], 1.0)
        self.assertEqual(report["summary"]["judged_candidates"], 1)
        self.assertEqual(report["summary"]["unknown_candidates"], 1)
        self.assertEqual(report["summary"]["assumed_nonrelevant_candidates"], 0)
        self.assertEqual(report["summary"]["inline_labeled_unjudged_qrels_candidates"], 1)
        self.assertEqual(qrels, {"q": {"inline": None, "unknown": None}})
        with self.assertRaisesRegex(ValueError, "conflicts with qrels"):
            evaluate_metrics(rows, Protocol(cutoffs=(2,)), {"q": {"inline": 0}})

    def test_threshold_preserves_graded_ndcg_and_recall_denominator_contract(self):
        rows = [Row("q", "low", 2, 1), Row("q", "high", 1, 2)]
        qrels = {"q": {"low": 1, "high": 2, "unretrieved_high": 2}}
        metrics = evaluate_metrics(
            rows, Protocol(cutoffs=(2,), relevance_threshold=1, qrels_complete=True), qrels
        )
        self.assertEqual(metrics["mrr@2"]["value"], 0.5)
        self.assertAlmostEqual(
            metrics["ndcg@2"]["value"], (1 + 2 / math.log2(3)) / (2 + 2 / math.log2(3))
        )
        self.assertEqual(metrics["recall@2"]["value"], 0.5)
        self.assertEqual(metrics["ndcg@2"]["reference"], "complete_qrels")
        self.assertEqual(metrics["recall@2"]["reference"], "complete_qrels")
        self.assertNotIn("eligibility_rule", metrics["ndcg@2"])
        self.assertNotIn("eligibility_rule", metrics["recall@2"])

    def test_macro_averages_only_identifiable_submitted_queries(self):
        rows = [
            Row("identified", "positive", 2, 1), Row("identified", "unknown", 1),
            Row("ambiguous", "unknown", 2), Row("ambiguous", "positive", 1, 1),
            Row("zero", "negative1", 2, 0), Row("zero", "negative2", 1, 0),
        ]
        metric = evaluate_metrics(rows, Protocol(cutoffs=(2,)))["mrr@2"]
        self.assertEqual(metric["value"], 0.5)
        self.assertEqual(metric["eligible_query_ids"], ["identified", "zero"])
        self.assertEqual(metric["excluded_query_ids"], ["ambiguous"])
        self.assertEqual(metric["evaluated_queries"], 2)
        self.assertEqual(metric["total_queries"], 3)
        self.assertEqual(metric["status"], "partial")
        self.assertEqual(metric["eligibility_rule"], RULE)

    def test_empty_predictions_do_not_create_a_zero_for_a_qrels_only_query(self):
        metrics = evaluate_metrics([], Protocol(cutoffs=(1, 5)), {"qrels_only": {"a": 1}})
        for cutoff in (1, 5):
            metric = metrics[f"mrr@{cutoff}"]
            self.assertIsNone(metric["value"])
            self.assertEqual(metric["status"], "not_checked")
            self.assertEqual(metric["total_queries"], 0)
            self.assertEqual(metric["evaluated_queries"], 0)
            self.assertEqual(metric["eligible_query_ids"], [])
            self.assertEqual(metric["qrels_only_queries"], 1)
            self.assertEqual(metric["eligibility_rule"], RULE)

    def test_delta_rejects_changed_missing_or_empty_mrr_rule_even_with_same_values(self):
        current = evaluate_metrics(
            [Row("q", "a", 1, 1)], Protocol(cutoffs=(1,), qrels_complete=True),
            {"q": {"a": 1}},
        )
        self.assertEqual(current["mrr@1"]["eligibility_rule"], RULE)
        changed, legacy, empty = (copy.deepcopy(current) for _ in range(3))
        changed["mrr@1"]["eligibility_rule"] = "all_top_k_known"
        legacy["mrr@1"].pop("eligibility_rule")
        empty["mrr@1"]["eligibility_rule"] = ""
        pairs = [(current, changed), (changed, current), (current, legacy),
                 (legacy, current), (legacy, legacy), (empty, empty)]
        for rule in (1, True, [RULE], " "):
            invalid = copy.deepcopy(current)
            invalid["mrr@1"]["eligibility_rule"] = rule
            pairs.append((invalid, invalid))
        for index, (left, right) in enumerate(pairs):
            with self.subTest(pair=index):
                delta = metric_deltas(left, right)
                self.assertIsNone(delta["mrr@1"]["delta"])
                self.assertEqual(delta["mrr@1"]["status"], "not_checked")
                for prefix in ("ndcg", "recall"):
                    self.assertEqual(delta[f"{prefix}@1"]["delta"], 0.0)
                    self.assertEqual(delta[f"{prefix}@1"]["status"], "checked")

    def test_delta_allows_same_declared_rule_with_same_query_and_reference(self):
        left = evaluate_metrics(
            [Row("q", "positive", 2, 1), Row("q", "negative", 1, 0)],
            Protocol(cutoffs=(2,)),
        )
        right = evaluate_metrics(
            [Row("q", "positive", 1, 1), Row("q", "negative", 2, 0)],
            Protocol(cutoffs=(2,)),
        )
        self.assertEqual(left["mrr@2"]["eligibility_rule"], RULE)
        self.assertEqual(right["mrr@2"]["eligibility_rule"], RULE)
        delta = metric_deltas(left, right)["mrr@2"]
        self.assertEqual(delta["delta"], -0.5)
        self.assertEqual(delta["status"], "checked")


if __name__ == "__main__":
    unittest.main()
