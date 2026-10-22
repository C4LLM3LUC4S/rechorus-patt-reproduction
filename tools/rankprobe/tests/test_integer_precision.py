from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from rankprobe import Protocol, Row, audit_run, compare_runs, evaluate_metrics
from rankprobe.io import InputError, _float, read_predictions, read_qrels


class IntegerPrecisionTests(unittest.TestCase):
    def test_identical_large_inline_labels_deduplicate_without_conflict(self):
        threshold = 2**53
        grade = threshold + 1
        rows = [Row("q", "same", 2, grade), Row("q", "same", 1, grade)]
        metrics = evaluate_metrics(rows, Protocol(cutoffs=(1,), relevance_threshold=threshold))
        self.assertEqual(metrics["mrr@1"]["value"], 1)
        self.assertEqual(rows[0].relevance, grade)

    def test_adjacent_known_labels_still_conflict(self):
        grade = 2**53
        with self.assertRaisesRegex(ValueError, "conflicting relevance"):
            evaluate_metrics([Row("q", "a", 2, grade), Row("q", "a", 1, grade + 1)], Protocol())
        with self.assertRaisesRegex(ValueError, "conflicts with qrels"):
            evaluate_metrics([Row("q", "a", 2, grade)], Protocol(), {"q": {"a": grade + 1}})

    def test_exact_threshold_applies_to_inline_and_qrels_integer_labels(self):
        threshold = 2**53
        qrels = {"q": {"a": threshold + 1}}
        original = deepcopy(qrels)
        protocol = Protocol(cutoffs=(1,), relevance_threshold=threshold, qrels_complete=True)
        for inline in (None, threshold + 1):
            with self.subTest(inline=inline):
                result = evaluate_metrics([Row("q", "a", 1, inline)], protocol, qrels)
                self.assertEqual(result["mrr@1"]["value"], 1)
                self.assertEqual(result["recall@1"]["value"], 1)
                self.assertEqual(result["mrr@1"]["status"], "ok")
        self.assertEqual(qrels, original)
        self.assertEqual(protocol.relevance_threshold, threshold)

    def test_comparison_keeps_adjacent_integer_label_mismatch(self):
        grade = 2**53
        result = compare_runs({"left": [Row("q", "a", 1, grade)],
                               "right": [Row("q", "a", 1, grade + 1)]}, Protocol(cutoffs=(1,)))
        pair = result["pairs"][0]
        self.assertEqual(pair["status"], "not_comparable")
        self.assertEqual(pair["label_consistency"]["conflicts"], 1)
        self.assertIsNone(pair["matched_pool_comparison"]["delta_right_minus_left"]["mrr@1"]["delta"])

    def test_exp2_adjacent_integer_and_mixed_integral_float_gains(self):
        base = 2**53
        very_large_float = 1e100
        pairs = ((base, base + 1), (float(base), base + 1), (base + 1, float(base + 2)),
                 (int(very_large_float) - 1, very_large_float))
        for lower, higher in pairs:
            with self.subTest(lower_type=type(lower).__name__, higher_type=type(higher).__name__):
                result = evaluate_metrics([Row("q", "returned", 1, lower)],
                    Protocol(cutoffs=(1,), gain="exp2", qrels_complete=True),
                    {"q": {"returned": lower, "not-returned": higher}})
                self.assertEqual(result["ndcg@1"]["value"], 0.5)
        fractional = evaluate_metrics([Row("q", "returned", 1, 511.75)],
            Protocol(cutoffs=(1,), gain="exp2"),
            {"q": {"returned": 511.75, "not-returned": 512.5}})
        self.assertAlmostEqual(fractional["ndcg@1"]["value"], 2.0**(-0.75), places=14)

    def test_linear_mixed_integral_float_uses_exact_integer_ratio(self):
        base = 2**53
        rows = [Row("q", "returned", 1, float(base))]
        qrels = {"q": {"returned": float(base), "not-returned": base + 1}}
        original = deepcopy(qrels)
        result = evaluate_metrics(rows, Protocol(cutoffs=(1,), gain="linear"), qrels)
        self.assertEqual(result["ndcg@1"]["value"], base / (base + 1))
        self.assertLess(result["ndcg@1"]["value"], 1)
        self.assertIs(type(rows[0].relevance), float)
        self.assertIs(type(qrels["q"]["returned"]), float)
        self.assertEqual(qrels, original)

    def test_integer_scores_do_not_turn_into_ties_across_file_formats(self):
        lower, higher = 2**53, 2**53 + 1
        fixtures = {
            "scores.csv": f"query_id,item_id,score,relevance\nq,a,{lower},0\nq,z,{higher},1\n",
            "scores.jsonl": "\n".join(json.dumps(row) for row in (
                {"query_id": "q", "item_id": "a", "score": lower, "relevance": 0},
                {"query_id": "q", "item_id": "z", "score": higher, "relevance": 1})) + "\n",
            "scores.run": f"q Q0 a 1 {lower} tag\nq Q0 z 2 {higher} tag\n",
        }
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            for filename, contents in fixtures.items():
                with self.subTest(format=filename):
                    path = folder / filename
                    path.write_text(contents, encoding="utf-8")
                    rows = read_predictions(path)
                    self.assertEqual([row.score for row in rows], [lower, higher])
                    self.assertTrue(all(type(row.score) is int for row in rows))
                    report = audit_run(rows, Protocol(cutoffs=(1,)), {"q": {"a": 0, "z": 1}})
                    self.assertEqual(report["metrics"]["mrr@1"]["value"], 1)
                    self.assertEqual(report["metrics"]["ndcg@1"]["value"], 1)
                    self.assertEqual(report["tie_analysis"]["tie_groups"], 0)
                    self.assertEqual(path.read_text("utf-8"), contents)

    def test_qrels_integer_precision_and_explicit_unknown_are_preserved(self):
        grade = 2**53 + 1
        fixtures = {
            "judgments.csv": f"query_id,item_id,relevance\nq,a,{grade}\n",
            "judgments.jsonl": json.dumps({"query_id": "q", "item_id": "a", "relevance": grade}) + "\n",
            "judgments.qrels": f"q 0 a {grade}\nq 0 not-judged -1\n",
        }
        with tempfile.TemporaryDirectory() as temporary:
            for filename, contents in fixtures.items():
                path = Path(temporary) / filename
                path.write_text(contents, encoding="utf-8")
                qrels = read_qrels(path)
                self.assertEqual(qrels["q"]["a"], grade)
                self.assertIs(type(qrels["q"]["a"]), int)
                if filename.endswith(".qrels"):
                    self.assertIsNone(qrels["q"]["not-judged"])
                    with self.assertRaisesRegex(ValueError, "explicitly unjudged"):
                        evaluate_metrics([Row("q", "a", 1)], Protocol(qrels_complete=True), qrels)

    def test_converter_retains_integer_syntax_and_binary64_decimal_behavior(self):
        grade = 2**53 + 1
        for value in (grade, str(grade), "+" + str(grade), "  " + str(grade) + "  ", -grade, str(-grade)):
            parsed = _float(value, "score")
            self.assertIs(type(parsed), int)
            self.assertEqual(parsed, int(value))
        for value in (str(grade) + ".0", "9.007199254740993e15", float(grade)):
            parsed = _float(value, "score")
            self.assertIs(type(parsed), float)
            self.assertEqual(parsed, float(grade))
        self.assertIsNone(_float(None, "relevance", optional=True))
        self.assertIsNone(_float("", "relevance", optional=True))
        self.assertEqual(_float("0" * 5000 + "1", "score"), 1)
        for value in ("-0", "-00", "  -000  "):
            parsed = _float(value, "score")
            self.assertIs(type(parsed), float)
            self.assertEqual(parsed.hex(), "-0x0.0p+0")

    def test_integer_parser_keeps_invalid_number_and_negative_grade_rejections(self):
        for value in (True, False, None, float("nan"), float("inf"), -float("inf"), 10**400, str(10**400)):
            with self.subTest(value_type=type(value).__name__):
                with self.assertRaisesRegex(ValueError, "finite number"):
                    _float(value, "score")
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "negative.csv"
            path.write_text("query_id,item_id,relevance\nq,a,-1\n", encoding="utf-8")
            with self.assertRaisesRegex(InputError, "non-negative"):
                read_qrels(path)

    def test_cli_preserves_integer_threshold_and_report_evidence(self):
        threshold = 2**53 + 1
        grade = threshold + 1
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            source = folder / "scores.csv"
            source.write_text(f"query_id,item_id,score,relevance\nq,a,{grade},{grade}\n", encoding="utf-8")
            qrels = folder / "judgments.csv"
            qrels.write_text(f"query_id,item_id,relevance\nq,a,{grade}\n", encoding="utf-8")
            output = folder / "report"
            process = subprocess.run(
                [sys.executable, "-m", "rankprobe", "audit", str(source),
                 "--qrels", str(qrels), "--qrels-complete", "--cutoffs", "1",
                 "--relevance-threshold", str(threshold), "--out", str(output)],
                capture_output=True, text=True, encoding="utf-8",
            )
            self.assertEqual(process.returncode, 0, process.stderr)
            report = json.loads((output / "report.json").read_text("utf-8"))
            self.assertIs(type(report["protocol"]["relevance_threshold"]), int)
            self.assertEqual(report["protocol"]["relevance_threshold"], threshold)
            self.assertEqual(report["metrics"]["mrr@1"]["value"], 1)
            self.assertEqual(report["metrics"]["recall@1"]["value"], 1)
            self.assertIn(str(threshold), (output / "report.html").read_text("utf-8"))
            self.assertEqual(read_predictions(source)[0].relevance, grade)

    def test_maximum_finite_integer_neighbor_gain_and_duplicate_score(self):
        largest = int(sys.float_info.max)
        result = evaluate_metrics(
            [Row("q", "a", 1, largest - 1)],
            Protocol(cutoffs=(1,), gain="exp2"),
            {"q": {"a": largest - 1, "b": largest}},
        )
        self.assertEqual(result["ndcg@1"]["value"], 0.5)
        self.assertEqual(_float(largest, "score"), largest)
        lower, higher = 2**53, 2**53 + 1
        result = evaluate_metrics(
            [Row("q", "a", lower, 1), Row("q", "a", higher, 1), Row("q", "z", lower, 0)],
            Protocol(cutoffs=(1,)),
        )
        self.assertEqual(result["mrr@1"]["value"], 1)


if __name__ == "__main__":
    unittest.main()
