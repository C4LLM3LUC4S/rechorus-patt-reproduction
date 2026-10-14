import json
import math
import unittest

from rankprobe.metrics import deduplicate_rows, evaluate_metrics, metric_deltas
from rankprobe.model import Protocol, Row


class MetricTests(unittest.TestCase):
    def test_hand_computed_linear_metrics_and_external_positives(self):
        rows = [Row("q", "a", 3, 0), Row("q", "b", 2, 2), Row("q", "c", 1, 1)]
        qrels = {"q": {"a": 0, "b": 2, "c": 1, "not_retrieved": 1}}
        result = evaluate_metrics(rows, Protocol(cutoffs=(1, 2, 3), qrels_complete=True), qrels)
        self.assertEqual(result["mrr@1"]["value"], 0)
        self.assertEqual(result["mrr@2"]["value"], 0.5)
        self.assertEqual(result["recall@2"]["value"], 1 / 3)
        expected = (2 / math.log2(3) + 1 / math.log2(4)) / (2 + 1 / math.log2(3) + 1 / math.log2(4))
        self.assertAlmostEqual(result["ndcg@3"]["value"], expected)
        self.assertEqual(result["ndcg@3"]["reference"], "complete_qrels")
        self.assertEqual(result["ndcg@3"]["status"], "ok")

    def test_hand_computed_exp2_gain(self):
        rows = [Row("q", "a", 2, 1), Row("q", "b", 1, 3)]
        result = evaluate_metrics(rows, Protocol(cutoffs=(2,), gain="exp2"))
        expected = (1 + 7 / math.log2(3)) / (7 + 1 / math.log2(3))
        self.assertAlmostEqual(result["ndcg@2"]["value"], expected)
        self.assertEqual(result["ndcg@2"]["reference"], "candidate_pool")
        self.assertEqual(result["ndcg@2"]["status"], "partial")

    def test_macro_averaging_and_missing_judgment_coverage(self):
        rows = [Row("known", "a", 2, 0), Row("known", "b", 1, 1), Row("unknown", "a", 1)]
        result = evaluate_metrics(rows, Protocol(cutoffs=(2,)))
        self.assertEqual(result["mrr@2"]["value"], 0.5)
        self.assertEqual(result["mrr@2"]["eligible_query_ids"], ["known"])
        self.assertEqual(result["mrr@2"]["evaluated_queries"], 1)
        self.assertEqual(result["mrr@2"]["excluded_queries"], 1)
        self.assertEqual(result["mrr@2"]["status"], "partial")

    def test_unknown_is_not_zero_and_cutoff_is_explicit(self):
        rows = [Row("q", "positive", 3, 1), Row("q", "unknown", 1)]
        result = evaluate_metrics(rows, Protocol(cutoffs=(1, 2)))
        self.assertEqual(result["mrr@1"]["value"], 1)
        self.assertIsNone(result["mrr@2"]["value"])
        self.assertIsNone(result["ndcg@1"]["value"])
        self.assertEqual(result["recall@1"]["status"], "not_checked")
        assumed = evaluate_metrics(rows, Protocol(cutoffs=(2,), unjudged="nonrelevant"))
        self.assertEqual(assumed["mrr@2"]["value"], 1)
        self.assertEqual(assumed["mrr@2"]["status"], "partial")

    def test_complete_qrels_resolves_absent_item_only_for_explicit_query(self):
        rows = [Row("listed", "unknown_item", 2), Row("absent", "a", 2, 1)]
        result = evaluate_metrics(
            rows, Protocol(cutoffs=(1,), qrels_complete=True), {"listed": {"positive": 1}}
        )
        self.assertEqual(result["mrr@1"]["value"], 0)
        self.assertEqual(result["mrr@1"]["eligible_query_ids"], ["listed"])
        self.assertEqual(result["recall@1"]["value"], 0)
        self.assertEqual(
            result["ndcg@1"]["exclusion_reasons"], {"query_missing_from_complete_qrels": 1}
        )

    def test_complete_qrels_requires_mapping(self):
        with self.assertRaisesRegex(ValueError, "requires"):
            evaluate_metrics([], Protocol(qrels_complete=True))

    def test_direct_api_rejects_wrong_row_and_protocol_types(self):
        for rows in (None, [None], [{"query_id": "q"}], ["q"]):
            with self.assertRaises(ValueError):
                evaluate_metrics(rows, Protocol())
        with self.assertRaises(ValueError):
            evaluate_metrics([], None)

    def test_known_qrels_pool_includes_nonretrieved_judgments(self):
        rows = [Row("q", "candidate", 1, 1)]
        result = evaluate_metrics(
            rows, Protocol(cutoffs=(1,)), {"q": {"candidate": 1, "missed": 3}}
        )
        self.assertAlmostEqual(result["ndcg@1"]["value"], 1 / 3)
        self.assertEqual(result["ndcg@1"]["reference"], "known_qrels_pool")
        self.assertIsNone(result["recall@1"]["value"])

    def test_qrels_authority_and_conflicting_duplicates(self):
        with self.assertRaisesRegex(ValueError, "conflicts with qrels"):
            evaluate_metrics([Row("q", "a", 1, 1)], Protocol(), {"q": {"a": 0}})
        with self.assertRaisesRegex(ValueError, "conflicting relevance"):
            evaluate_metrics([Row("q", "a", 2, 1), Row("q", "a", 1, 0)], Protocol())
        with self.assertRaisesRegex(ValueError, "absent from complete"):
            evaluate_metrics([Row("q", "a", 1, 1)], Protocol(qrels_complete=True), {"q": {}})
        result = evaluate_metrics([Row("q", "a", 2), Row("q", "a", 1, 1)], Protocol(cutoffs=(1,)))
        self.assertEqual(result["mrr@1"]["value"], 1)

    def test_deduplicate_max_score_with_first_occurrence_slot(self):
        rows = [Row("q", "b", 0, 1), Row("q", "a", 2, 0), Row("q", "b", 3, 1)]
        deduped = deduplicate_rows(rows)
        self.assertEqual([r.item_id for r in deduped], ["b", "a"])
        self.assertEqual(deduped[0].score, 3)
        self.assertEqual(evaluate_metrics(rows, Protocol(cutoffs=(1,)))["mrr@1"]["value"], 1)

    def test_tie_policies_are_lexical_or_stable_input(self):
        rows = [Row("q", "z", 0, 1), Row("q", "a", 0, 0)]
        self.assertEqual(evaluate_metrics(rows, Protocol(cutoffs=(1,)))["mrr@1"]["value"], 0)
        self.assertEqual(
            evaluate_metrics(rows, Protocol(cutoffs=(1,), tie_policy="input"))["mrr@1"]["value"], 1
        )

    def test_zero_ideal_gain_and_zero_recall_denominator(self):
        result = evaluate_metrics(
            [Row("q", "a", 1, 0)], Protocol(cutoffs=(1,), qrels_complete=True), {"q": {"a": 0}}
        )
        self.assertEqual(result["ndcg@1"]["value"], 0)
        self.assertEqual(result["mrr@1"]["value"], 0)
        self.assertIsNone(result["recall@1"]["value"])
        self.assertEqual(result["recall@1"]["exclusion_reasons"], {"no_relevant_items_in_qrels": 1})

    def test_threshold_only_affects_binary_metrics(self):
        rows = [Row("q", "a", 2, 1), Row("q", "b", 1, 2)]
        result = evaluate_metrics(
            rows,
            Protocol(cutoffs=(2,), relevance_threshold=1, qrels_complete=True),
            {"q": {"a": 1, "b": 2}},
        )
        self.assertEqual(result["mrr@2"]["value"], 0.5)
        self.assertEqual(result["recall@2"]["value"], 1)
        self.assertAlmostEqual(
            result["ndcg@2"]["value"], (1 + 2 / math.log2(3)) / (2 + 1 / math.log2(3))
        )

    def test_huge_and_tiny_finite_labels_do_not_overflow_or_cancel(self):
        for gain in ("linear", "exp2"):
            for relevance in (1e308, 1e-300):
                result = evaluate_metrics(
                    [Row("q", "a", 2, relevance), Row("q", "b", 1, 0)],
                    Protocol(cutoffs=(2,), gain=gain),
                )
                self.assertEqual(result["ndcg@2"]["value"], 1)
                json.dumps(result, allow_nan=False)

    def test_qrels_negative_nonfinite_or_bool_rejected(self):
        for value in (-1, float("nan"), float("inf"), True, 10**400):
            with self.assertRaises(ValueError):
                evaluate_metrics([], Protocol(), {"q": {"a": value}})

    def test_empty_returns_not_checked_and_no_nan(self):
        result = evaluate_metrics([], Protocol())
        self.assertTrue(
            all(m["status"] == "not_checked" and m["value"] is None for m in result.values())
        )
        json.dumps(result, allow_nan=False)

    def test_delta_requires_same_query_ids_not_merely_same_count(self):
        left = evaluate_metrics([Row("one", "a", 1, 1)], Protocol(cutoffs=(1,)))
        right = evaluate_metrics([Row("two", "a", 1, 1)], Protocol(cutoffs=(1,)))
        self.assertIsNone(metric_deltas(left, right)["mrr@1"]["delta"])


if __name__ == "__main__":
    unittest.main()
