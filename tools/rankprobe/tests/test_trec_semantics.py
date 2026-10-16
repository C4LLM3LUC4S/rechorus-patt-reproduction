"""The TREC -1 sentinel must remain an explicit absence of judgment."""

import copy
import json
import unittest

from rankprobe.audit import audit_run, compare_runs
from rankprobe.metrics import evaluate_metrics, resolve_rows, validate_inputs
from rankprobe.model import Protocol, Row


class ExplicitUnjudgedQrelsTests(unittest.TestCase):
    def test_none_only_query_excludes_metrics_instead_of_scoring_zero(self):
        rows = [Row("q", "a", 1)]
        report = audit_run(rows, Protocol(cutoffs=(1,)), {"q": {"a": None}})
        for metric in report["metrics"].values():
            self.assertIsNone(metric["value"])
            self.assertEqual(metric["status"], "not_checked")
        self.assertEqual(report["summary"]["judged_candidates"], 0)
        self.assertEqual(report["summary"]["resolved_candidates"], 0)
        self.assertEqual(report["summary"]["unknown_candidates"], 1)
        self.assertEqual(report["summary"]["explicit_unjudged_qrels"], 1)
        self.assertEqual(report["summary"]["assumed_nonrelevant_candidates"], 0)
        self.assertIn("unknown_judgments", {f["code"] for f in report["findings"]})
        json.dumps(report, allow_nan=False)

    def test_complete_declaration_rejects_every_explicit_unknown(self):
        # Completeness contradicts the source even when the unjudged item is
        # not retrieved, is in another query, or has an inline label.
        cases = [
            ([], {"q": {"a": None}}),
            ([Row("q", "a", 1, 1)], {"q": {"a": None}}),
            ([Row("q", "a", 1, 1)], {"q": {"a": 1, "unretrieved": None}}),
            ([Row("q", "a", 1, 1)], {"q": {"a": 1}, "other": {"b": None}}),
        ]
        for rows, qrels in cases:
            for policy in ("unknown", "nonrelevant"):
                with self.subTest(rows=rows, qrels=qrels, policy=policy):
                    with self.assertRaisesRegex(ValueError, "contradicts explicitly unjudged"):
                        evaluate_metrics(rows, Protocol(qrels_complete=True, unjudged=policy), qrels)

    def test_partial_coverage_and_known_reference_pool_ignore_none(self):
        rows = [
            Row("partial", "positive", 2),
            Row("partial", "unknown", 1),
            Row("known", "positive", 1),
        ]
        qrels = {
            "partial": {"positive": 1, "unknown": None},
            "known": {"positive": 1, "unretrieved_positive": 3, "unjudged": None},
        }
        result = evaluate_metrics(rows, Protocol(cutoffs=(1, 2)), qrels)
        self.assertEqual(result["mrr@1"]["value"], 1)
        self.assertEqual(result["mrr@2"]["eligible_query_ids"], ["known", "partial"])
        self.assertEqual(result["mrr@2"]["value"], 1)
        self.assertEqual(result["mrr@2"]["excluded_queries"], 0)
        self.assertEqual(result["mrr@2"]["status"], "ok")
        self.assertEqual(result["ndcg@1"]["eligible_query_ids"], ["known"])
        self.assertAlmostEqual(result["ndcg@1"]["value"], 1 / 3)
        self.assertEqual(result["ndcg@1"]["reference"], "known_qrels_pool")
        self.assertEqual(result["ndcg@1"]["status"], "partial")
        self.assertIsNone(result["recall@2"]["value"])
        self.assertEqual(
            result["recall@2"]["exclusion_reasons"], {"complete_qrels_not_declared": 2}
        )

    def test_known_inline_label_survives_source_unjudged_marker(self):
        for label in (0, 3):
            with self.subTest(label=label):
                rows = [Row("q", "a", 1, label)]
                qrels = {"q": {"a": None}}
                report = audit_run(rows, Protocol(cutoffs=(1,)), qrels)
                self.assertEqual(report["metrics"]["mrr@1"]["value"], int(label > 0))
                self.assertEqual(report["summary"]["judged_candidates"], 1)
                self.assertEqual(report["summary"]["unknown_candidates"], 0)
                self.assertEqual(report["summary"]["assumed_nonrelevant_candidates"], 0)
                self.assertEqual(report["summary"]["inline_labeled_unjudged_qrels_candidates"], 1)
                finding = next(
                    f for f in report["findings"] if f["code"] == "explicit_unjudged_qrels"
                )
                self.assertEqual(finding["evidence"]["known_inline_labels"], 1)
                self.assertIn("Known inline labels are retained", finding["message"])

    def test_known_qrels_still_reject_conflicting_inline_label(self):
        with self.assertRaisesRegex(ValueError, "conflicts with qrels"):
            validate_inputs([Row("q", "a", 1, 1)], Protocol(), {"q": {"a": 0, "b": None}})

    def test_nonrelevant_is_explicit_assumption_and_never_complete_recall(self):
        rows = [Row("q", "unknown", 3), Row("q", "positive", 2), Row("q", "absent", 1)]
        qrels = {"q": {"unknown": None, "positive": 1}}
        report = audit_run(rows, Protocol(cutoffs=(3,), unjudged="nonrelevant"), qrels)
        summary = report["summary"]
        self.assertEqual(summary["judged_candidates"], 1)
        self.assertEqual(summary["resolved_candidates"], 3)
        self.assertEqual(summary["assumed_nonrelevant_candidates"], 2)
        self.assertEqual(summary["unknown_candidates"], 0)
        self.assertEqual(report["metrics"]["mrr@3"]["value"], 0.5)
        self.assertEqual(report["metrics"]["mrr@3"]["status"], "partial")
        self.assertEqual(report["metrics"]["ndcg@3"]["status"], "partial")
        self.assertIsNone(report["metrics"]["recall@3"]["value"])
        finding = next(f for f in report["findings"] if f["code"] == "explicit_unjudged_qrels")
        self.assertEqual(finding["evidence"]["assumed_nonrelevant_candidates"], 1)
        self.assertIn("unjudged='nonrelevant'", finding["message"])

    def test_assumption_count_uses_unique_candidates_and_known_inline_labels(self):
        rows = [
            Row("q", "unknown", 3),
            Row("q", "unknown", 2),
            Row("q", "inline", 1, 1),
            Row("q", "inline", 0),
        ]
        qrels = {"q": {"unknown": None, "inline": None}}
        report = audit_run(rows, Protocol(cutoffs=(2,), unjudged="nonrelevant"), qrels)
        self.assertEqual(report["summary"]["unique_candidates"], 2)
        self.assertEqual(report["summary"]["judged_candidates"], 1)
        self.assertEqual(report["summary"]["assumed_nonrelevant_candidates"], 1)
        self.assertEqual(report["summary"]["inline_labeled_unjudged_qrels_candidates"], 1)
        self.assertEqual(report["metrics"]["mrr@2"]["value"], 0.5)

    def test_qrels_only_none_query_is_preserved_in_evaluation_universe(self):
        qrels = {"submitted": {"a": 1}, "unsubmitted": {"b": None}}
        report = audit_run([Row("submitted", "a", 1)], Protocol(cutoffs=(1,)), qrels)
        self.assertEqual(report["summary"]["qrels_queries"], 2)
        self.assertEqual(report["summary"]["qrels_queries_without_predictions"], 1)
        self.assertEqual(report["summary"]["explicit_unjudged_qrels"], 1)
        self.assertEqual(report["summary"]["explicit_unjudged_qrels_candidates"], 0)
        self.assertEqual(report["metrics"]["mrr@1"]["status"], "partial")
        self.assertEqual(report["metrics"]["mrr@1"]["qrels_only_queries"], 1)
        finding = next(
            f for f in report["findings"] if f["code"] == "qrels_queries_without_predictions"
        )
        self.assertEqual(finding["evidence"]["query_ids"], ["unsubmitted"])

    def test_unknown_tie_bound_is_not_an_oracle_zero(self):
        rows = [Row("q", "a", 0), Row("q", "b", 0)]
        report = audit_run(rows, Protocol(cutoffs=(1,)), {"q": {"a": None, "b": 1}})
        for bound in report["tie_analysis"]["metric_bounds"].values():
            self.assertIsNone(bound["min"])
            self.assertIsNone(bound["max"])
            self.assertEqual(bound["status"], "not_checked")

    def test_compare_same_pool_preserves_unknown_and_eligibility(self):
        runs = {
            "known_first": [Row("q", "a", 2), Row("q", "b", 1)],
            "unknown_first": [Row("q", "a", 1), Row("q", "b", 2)],
        }
        report = compare_runs(runs, Protocol(cutoffs=(1,)), {"q": {"a": 1, "b": None}})
        pair = report["pairs"][0]
        self.assertEqual(pair["status"], "comparable")
        self.assertEqual(pair["label_consistency"]["conflicts"], 0)
        matched = pair["matched_pool_comparison"]
        self.assertEqual(matched["left_metrics"]["mrr@1"]["value"], 1)
        self.assertIsNone(matched["right_metrics"]["mrr@1"]["value"])
        self.assertIsNone(matched["delta_right_minus_left"]["mrr@1"]["delta"])
        self.assertEqual(
            {f["run_name"] for f in report["findings"] if f["code"] == "explicit_unjudged_qrels"},
            {"known_first", "unknown_first"},
        )

    def test_compare_inline_label_disagreement_is_not_hidden_by_none_qrels(self):
        report = compare_runs(
            {"a": [Row("q", "item", 1, 1)], "b": [Row("q", "item", 1, 0)]},
            Protocol(cutoffs=(1,)),
            {"q": {"item": None}},
        )
        self.assertEqual(report["pairs"][0]["status"], "not_comparable")
        self.assertEqual(report["pairs"][0]["label_consistency"]["conflicts"], 1)

    def test_source_rows_and_qrels_are_never_mutated(self):
        rows = [Row("q", "a", 2), Row("q", "b", 1, 1)]
        qrels = {"q": {"a": None, "b": None, "unretrieved": 3}}
        original_rows, original_qrels = list(rows), copy.deepcopy(qrels)
        protocol = Protocol(cutoffs=(2,), unjudged="nonrelevant")
        resolved = resolve_rows(validate_inputs(rows, protocol, qrels), protocol, qrels)
        self.assertEqual([row.relevance for row in resolved], [0, 1])
        audit_run(rows, protocol, qrels)
        self.assertEqual(rows, original_rows)
        self.assertEqual(qrels, original_qrels)


if __name__ == "__main__":
    unittest.main()
