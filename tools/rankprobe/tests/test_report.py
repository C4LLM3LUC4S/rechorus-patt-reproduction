from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import json
from html.parser import HTMLParser
import os
from pathlib import Path
import tempfile
from threading import Barrier
import unittest
from unittest.mock import patch

from rankprobe.audit import audit_run, compare_runs
from rankprobe.model import Protocol, Row
from rankprobe.report import render_html, write_report


class ReportTables(HTMLParser):
    """Read visible table cells without depending on the report's markup layout."""

    def __init__(self, source):
        super().__init__()
        self.tables = []
        self.ids = set()
        self.links = []
        self.rows = None
        self.row = None
        self.cell = None
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "id" in attrs:
            self.ids.add(attrs["id"])
        if tag == "a":
            self.links.append(attrs.get("href", ""))
        if tag == "table":
            self.rows = []
        elif tag == "tr":
            self.row = []
        elif tag in {"th", "td"}:
            self.cell = []

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if tag in {"th", "td"} and self.cell is not None:
            self.row.append("".join(self.cell))
            self.cell = None
        elif tag == "tr" and self.row is not None:
            self.rows.append(self.row)
            self.row = None
        elif tag == "table" and self.rows is not None:
            self.tables.append(self.rows)
            self.rows = None


def sample_report():
    return {
        "schema_version": "0.1",
        "report_type": "audit",
        "run_name": '<img src="https://bad.test/x" onerror="alert(1)">',
        "summary": {"queries": 2, "unknown_candidates": 1},
        "protocol": {"tie_policy": "item_id", "qrels_complete": False},
        "metrics": {
            "ndcg@5": {
                "value": 0.5,
                "status": "partial",
                "evaluated_queries": 1,
                "total_queries": 2,
                "excluded_queries": 1,
                "reference": "candidate_pool",
                "reason": "judgments are incomplete",
            }
        },
        "findings": [
            {
                "code": "ties",
                "severity": "warning",
                "title": "Tied scores",
                "message": '<script>alert("message")</script>',
                "evidence": [{"query_id": '<svg onload="alert(1)">', "item_id": "x&y"}],
            }
        ],
    }


class ReportTests(unittest.TestCase):
    def test_first_use_preview_separates_averages_and_eligible_queries(self):
        rows = [
            Row("q1", "a", 2, 0), Row("q1", "b", 1, 1),
            Row("q2", "c", 2, 0), Row("q2", "d", 1, 0),
            Row("q3", "e", 2), Row("q3", "f", 1, 1),
        ]
        report = compare_runs({"baseline": rows, "reordered": rows[:2] + rows[4:]}, Protocol(cutoffs=(1, 2)))
        before = json.dumps(report, sort_keys=True)
        result = render_html(report)
        preview = result.split('class="comparison-reader"', 1)[1].split('</aside>', 1)[0]
        self.assertIn("先核对比较范围", preview)
        self.assertIn("baseline: 3", preview)
        self.assertIn("reordered: 2", preview)
        self.assertIn("same candidate pools: 2", preview)
        self.assertIn("not the number eligible for every metric", preview)
        self.assertIn("Restore omitted predictions if accidental", preview)
        self.assertIn("mrr@2", preview)
        self.assertNotIn("mrr@1", preview)
        self.assertIn("0.25", preview)
        self.assertIn("+0", preview)
        self.assertIn("eligible queries: 1", preview)
        self.assertIn("supplied candidate pool / 当前候选池", preview)
        self.assertIn("范围有限", preview)
        self.assertIn("仅在上述查询及参考范围内有效", preview)
        self.assertIn("最大请求截断位置", preview)
        self.assertIn("MRR", preview)
        self.assertIn("NDCG", preview)
        self.assertLess(result.index('class="comparison-reader"'), result.index('Full metric table and coverage'))
        self.assertNotIn('<details open', result)
        self.assertEqual(json.dumps(report, sort_keys=True), before)

    def test_preview_does_not_invent_missing_metrics_or_call_unknown_zero(self):
        report = compare_runs(
            {"left": [Row("q", "a", 2), Row("q", "b", 1)],
             "right": [Row("q", "a", 3), Row("q", "b", 2)]},
            Protocol(cutoffs=(1, 2)),
        )
        result = render_html(report)
        preview = result.split('class="comparison-reader"', 1)[1].split('</aside>', 1)[0]
        self.assertIn("Not available", preview)
        self.assertIn("无法计算，不是零分", preview)
        self.assertIn("eligible queries: 0", preview)
        self.assertNotIn("Restore omitted predictions if accidental", preview)
        self.assertNotIn("improved", preview)
        self.assertNotIn("+0", preview)

    def test_preview_preserves_delta_sign_and_candidate_stage_action(self):
        runs = {
            '<img src=x onerror=alert(1)>': [Row("q", "a", 3, 0), Row("q", "b", 2, 1), Row("q", "c", 1, 0)],
            "better": [Row("q", "b", 3, 1), Row("q", "a", 2, 0), Row("q", "c", 1, 0)],
            "worse": [Row("q", "a", 3, 0), Row("q", "c", 2, 0), Row("q", "b", 1, 1)],
        }
        result = render_html(compare_runs(runs, Protocol(cutoffs=(2,))))
        self.assertIn("+0.5", result)
        self.assertIn("-0.5", result)
        self.assertNotIn("<img ", result)
        self.assertIn("&lt;img src=x onerror=alert(1)&gt;", result)
        changed = compare_runs(
            {"left": [Row("q", "a", 2, 1), Row("q", "b", 1, 0)],
             "right": [Row("q", "a", 2, 1), Row("q", "c", 1, 0)]},
            Protocol(cutoffs=(2,)),
        )
        preview = render_html(changed).split('class="comparison-reader"', 1)[1].split('</aside>', 1)[0]
        self.assertIn("actual candidate stage", preview)
        self.assertIn("Not available", preview)
        self.assertNotIn("+0", preview)

    def test_nested_candidate_evidence_identifies_query_before_expanding(self):
        query = 'q<script>alert(1)</script>&'
        runs = {
            "left": [Row(query, "a", 2, 1), Row(query, "b", 1, 0)],
            "right": [Row(query, "a", 2, 1), Row(query, "c", 1, 0)],
        }
        report = compare_runs(runs, Protocol(cutoffs=(1,)))
        before = json.dumps(report, sort_keys=True)
        result = render_html(report)
        self.assertIn(
            "<summary>Entry 1: query q&lt;script&gt;alert(1)&lt;/script&gt;&amp;</summary>",
            result,
        )
        self.assertNotIn("<script>", result)
        self.assertEqual(json.dumps(report, sort_keys=True), before)

    def test_actual_comparison_exposes_positive_and_negative_matched_deltas(self):
        runs = {
            "baseline": [Row("q1", "b", 3, 0), Row("q1", "a", 2, 1), Row("q1", "c", 1, 0)],
            "better": [Row("q1", "a", 3, 1), Row("q1", "b", 2, 0), Row("q1", "c", 1, 0)],
            "worse": [Row("q1", "b", 3, 0), Row("q1", "c", 2, 0), Row("q1", "a", 1, 1)],
        }
        report = compare_runs(runs, Protocol(cutoffs=(2,)))
        result = render_html(report)
        tables = [table for table in ReportTables(result).tables if "Submitted left" in table[0]]
        self.assertEqual(len(tables), 3)
        rows = [{row[0]: row for row in table[1:]} for table in tables]
        self.assertEqual(report["pairs"][0]["matched_pool_comparison"]["delta_right_minus_left"]["mrr@2"]["delta"], 0.5)
        self.assertTrue(rows[0]["mrr@2"][-1].startswith("+0.5\n"))
        self.assertTrue(rows[1]["mrr@2"][-1].startswith("-0.5\n"))
        self.assertIn("status: partial", rows[0]["ndcg@2"][1])
        self.assertIn("reference: candidate_pool", rows[0]["ndcg@2"][3])
        self.assertIn("metric-eligible queries: 1 / 1", rows[0]["mrr@2"][3])
        self.assertIn("not a full-run improvement", result)
        self.assertIn('href="#pairs">Comparison results</a>', result)
        self.assertLess(result.index('id="pairs"'), result.index('id="findings"'))

    def test_comparison_separates_submitted_and_metric_eligible_populations(self):
        rows = [
            Row("q1", "a", 2, 0), Row("q1", "b", 1, 1),
            Row("q2", "c", 2, 0), Row("q2", "d", 1, 0),
            Row("q3", "e", 2), Row("q3", "f", 1, 1),
        ]
        report = compare_runs({"baseline": rows, "subset": rows[:2] + rows[4:]}, Protocol(cutoffs=(2,)))
        result = render_html(report)
        table = next(table for table in ReportTables(result).tables if "Submitted left" in table[0])
        mrr = next(row for row in table[1:] if row[0] == "mrr@2")
        self.assertTrue(mrr[1].startswith("0.25\n"))
        self.assertTrue(mrr[2].startswith("0.5\n"))
        self.assertTrue(mrr[3].startswith("0.5\n"))
        self.assertTrue(mrr[4].startswith("0.5\n"))
        self.assertTrue(mrr[5].startswith("+0\n"))
        self.assertIn("Structurally matched queries: 2", result)
        self.assertIn("metric-eligible queries: 1 / 2", mrr[3])
        self.assertIn("Unknown top k judgment", result)
        self.assertIn("Eligible query ids", result)
        self.assertIn("pairs[0].matched_pool_comparison.left_metrics", result)
        self.assertIn("Restore omitted predictions", result)
        self.assertIn("JSON: findings[", result)

    def test_actual_duplicate_diagnostic_retains_delta_column(self):
        report = audit_run(
            [Row("q1", "a", 3, 0), Row("q1", "a", 2, 0), Row("q1", "b", 1, 1)],
            Protocol(cutoffs=(2,)),
        )
        self.assertEqual(report["duplicates"]["metric_sensitivity"]["delta_raw_minus_deduplicated"]["mrr@2"]["delta"], -0.5)
        tables = ReportTables(render_html(report)).tables
        visible_mrr_deltas = [
            row[table[0].index("Delta")]
            for table in tables if "Delta" in table[0]
            for row in table[1:] if row[0] == "mrr@2"
        ]
        self.assertIn("-0.5", visible_mrr_deltas)

    def test_coverage_details_are_bounded_and_run_names_escaped(self):
        rows = [Row(f"coverage-id-{index:03d}", "a", 1, 1) for index in range(65)]
        report = compare_runs({"<svg/onload=alert(1)>": rows, "other": rows}, Protocol(cutoffs=(1,)))
        result = render_html(report)
        self.assertNotIn("<svg", result)
        self.assertIn("&lt;svg/onload=alert(1)&gt;", result)
        self.assertIn("Showing 20 of 65 entries", result)
        self.assertIn("coverage-id-019", result)
        # Identifiers remain bounded even inside folded pair scope lists.
        self.assertNotIn("coverage-id-064", result)
        self.assertIn("overflow-wrap:anywhere", result)

    def test_partial_reports_and_finding_links_keep_working_without_optional_sections(self):
        reports = [
            audit_run([Row("q1", "a", 1, 1), Row("q1", "b", 1, 0)], Protocol(cutoffs=(1,))),
            {
                "report_type": "compare",
                "pairs": [{"left": "x", "right": "y", "custom_evidence": {"note": "retained detail"}}],
                "findings": [{"code": "unknown_judgments", "severity": "warning"}],
            },
        ]
        for report in reports:
            with self.subTest(report_type=report["report_type"]):
                result = render_html(report)
                parsed = ReportTables(result)
                for link in parsed.links:
                    if link.startswith("#"):
                        self.assertIn(link[1:], parsed.ids)
                self.assertIn("Next step:", result)
        self.assertIn("retained detail", render_html(reports[1]))

    def test_escapes_untrusted_identifiers_and_messages(self):
        result = render_html(sample_report())
        self.assertNotIn("<script>", result)
        self.assertNotIn("<svg ", result)
        self.assertNotIn("<img ", result)
        self.assertIn("&lt;script&gt;", result)
        self.assertIn("x&amp;y", result)
        self.assertIn("default-src 'none'", result)
        self.assertNotIn("<script src=", result)

    def test_unknown_and_metric_reference_remain_visible(self):
        result = render_html(sample_report())
        self.assertIn("Relevance coverage is incomplete", result)
        self.assertIn("candidate_pool", result)
        self.assertIn("partial", result)
        self.assertIn("A missing value is not zero", result)

    def test_tie_bounds_identify_partial_coverage_without_filling_unknown_labels(self):
        rows = [
            Row("known", "a", 1, 1), Row("known", "b", 1, 0),
            Row("unknown", "x", 1), Row("unknown", "y", 1),
        ]
        report = audit_run(rows, Protocol(cutoffs=(1,)))
        self.assertEqual(report["metrics"]["mrr@1"]["status"], "partial")
        bound = report["tie_analysis"]["metric_bounds"]["mrr@1"]
        self.assertEqual(bound["min"], 0)
        self.assertEqual(bound["max"], 1)
        self.assertEqual(bound["status"], "partial")
        self.assertEqual(bound["evaluated_queries"], 1)
        self.assertEqual(bound["total_queries"], 2)
        self.assertEqual(bound["excluded_query_ids"], ["unknown"])
        self.assertEqual(report["summary"]["unknown_candidates"], 2)

        table = next(
            table for table in ReportTables(render_html(report)).tables
            if "Min" in table[0] and "Max" in table[0]
        )
        row = next(row for row in table[1:] if row[0] == "mrr@1")
        self.assertEqual(row[table[0].index("Status")], "partial")
        self.assertEqual(row[table[0].index("Excluded queries")], "1")

        limited = audit_run(rows[:2], Protocol(cutoffs=(1,)))
        self.assertEqual(limited["tie_analysis"]["metric_bounds"]["mrr@1"]["status"], "checked")
        self.assertEqual(limited["tie_analysis"]["metric_bounds"]["ndcg@1"]["status"], "partial")
        complete = audit_run(
            rows[:2], Protocol(cutoffs=(1,), qrels_complete=True),
            {"known": {"a": 1, "b": 0}},
        )
        self.assertEqual(complete["tie_analysis"]["metric_bounds"]["ndcg@1"]["status"], "checked")

    def test_perfect_partial_metric_context_is_visible_only_in_main_metrics(self):
        rows = [
            Row("positive_first", "positive", 0.9, 1),
            Row("positive_first", "unjudged", 0.2),
            Row("unknown_first", "unjudged", 0.9),
            Row("unknown_first", "positive", 0.2, 1),
        ]
        report = audit_run(rows, Protocol(cutoffs=(1,)))
        before = json.dumps(report, sort_keys=True)
        result = render_html(report)
        context = "mrr@1 = 1 is the average over 1 eligible query out of 2 submitted queries."
        self.assertEqual(result.count(context), 1)
        self.assertIn("perfect results across all submitted queries", result)
        self.assertIn("See coverage details for exclusion reasons", result)
        self.assertLess(result.index('id="metrics"'), result.index(context))
        self.assertLess(result.index(context), result.index('id="tie_analysis"'))
        self.assertEqual(json.dumps(report, sort_keys=True), before)
        metrics = report["metrics"]
        self.assertEqual(metrics["mrr@1"]["excluded_query_ids"], ["unknown_first"])
        self.assertIsNone(metrics["ndcg@1"]["value"])
        self.assertIsNone(metrics["recall@1"]["value"])

    def test_partial_perfect_context_requires_partial_query_coverage_and_exact_one(self):
        full_coverage = audit_run(
            [Row("q", "positive", 2, 1), Row("q", "negative", 1, 0)],
            Protocol(cutoffs=(1,)),
        )
        self.assertEqual(full_coverage["metrics"]["ndcg@1"]["value"], 1)
        self.assertEqual(full_coverage["metrics"]["ndcg@1"]["status"], "partial")
        self.assertEqual(full_coverage["metrics"]["ndcg@1"]["reference"], "candidate_pool")
        nonperfect = audit_run(
            [Row("known", "negative", 2, 0), Row("known", "positive", 1, 1),
             Row("unknown", "unjudged", 1)],
            Protocol(cutoffs=(2,)),
        )
        self.assertEqual(nonperfect["metrics"]["mrr@2"]["value"], 0.5)
        self.assertEqual(nonperfect["metrics"]["mrr@2"]["status"], "partial")
        unavailable = audit_run([Row("q", "unjudged", 1)], Protocol(cutoffs=(1,)))
        self.assertIsNone(unavailable["metrics"]["mrr@1"]["value"])
        near_one = {
            "metrics": {
                "mrr@1": {
                    **nonperfect["metrics"]["mrr@2"],
                    "value": 0.9999999,
                }
            }
        }
        rendered_near_one = ReportTables(render_html(near_one)).tables[0]
        self.assertEqual(
            rendered_near_one[1][rendered_near_one[0].index("Value")], "0.9999999"
        )
        for name, report in (
            ("full coverage with candidate-pool partial", full_coverage),
            ("nonperfect", nonperfect),
            ("unavailable", unavailable),
            ("rounded to one", near_one),
        ):
            with self.subTest(case=name):
                self.assertNotIn("perfect results across all submitted queries", render_html(report))

    def test_real_near_perfect_ndcg_and_matched_delta_do_not_display_as_exact_one(self):
        protocol = Protocol(cutoffs=(1,), qrels_complete=True)
        qrels = {"q": {"zero": 0, "lower": 1.0, "higher": 1.0000001}}
        left = [Row("q", "zero", 3), Row("q", "lower", 2), Row("q", "higher", 1)]
        right = [Row("q", "lower", 3), Row("q", "zero", 2), Row("q", "higher", 1)]
        report = compare_runs({"baseline": left, "near_perfect": right}, protocol, qrels)
        expected = report["runs"]["near_perfect"]["metrics"]["ndcg@1"]["value"]
        self.assertLess(expected, 1)
        self.assertGreater(expected, 0.999999)
        self.assertIn(
            f"<td>ndcg@1</td><td>{expected}</td>",
            render_html(audit_run(right, protocol, qrels)),
        )

        html = render_html(report)
        comparison = next(table for table in ReportTables(html).tables if "Submitted left" in table[0])
        ndcg = next(row for row in comparison[1:] if row[0] == "ndcg@1")
        self.assertTrue(ndcg[2].startswith(f"{expected}\n"))
        self.assertTrue(ndcg[4].startswith(f"{expected}\n"))
        self.assertTrue(ndcg[5].startswith(f"+{expected}\n"))

    def test_bounded_evidence_and_native_keyboard_controls(self):
        report = sample_report()
        report["findings"][0]["evidence"] = [{"query_id": f"unique-query-{i}"} for i in range(40)]
        result = render_html(report)
        self.assertIn("unique-query-19", result)
        self.assertNotIn("unique-query-20", result)
        self.assertIn("Showing 20 of 40 rows", result)
        self.assertIn("<details>", result)
        self.assertIn("<summary>", result)
        self.assertIn('href="#main"', result)

    def test_empty_audit_does_not_claim_correctness(self):
        result = render_html({"findings": []})
        self.assertIn("No findings were reported", result)
        self.assertIn("does not establish data provenance", result)

    def test_writes_both_and_preserves_unrelated_files(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / "notes.txt").write_text("keep me", encoding="utf-8")
            json_file, html_file = write_report(sample_report(), folder)
            self.assertEqual(json.loads(json_file.read_text(encoding="utf-8")), sample_report())
            self.assertTrue(html_file.read_text(encoding="utf-8").startswith("<!doctype html>"))
            self.assertEqual((folder / "notes.txt").read_text(encoding="utf-8"), "keep me")
            original = json_file.read_bytes()
            with self.assertRaises(FileExistsError):
                write_report({"findings": []}, folder)
            self.assertEqual(json_file.read_bytes(), original)

    def test_overwrite_replaces_only_named_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            write_report(sample_report(), folder)
            (folder / "source.csv").write_text("keep", encoding="utf-8")
            write_report({"findings": []}, folder, overwrite=True)
            self.assertEqual(
                json.loads((folder / "report.json").read_text(encoding="utf-8")), {"findings": []}
            )
            self.assertEqual((folder / "source.csv").read_text(encoding="utf-8"), "keep")

    def test_nonfinite_json_is_rejected_before_touching_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            write_report(sample_report(), folder)
            original = (folder / "report.json").read_bytes()
            with self.assertRaises(ValueError):
                write_report({"value": float("nan")}, folder, overwrite=True)
            self.assertEqual((folder / "report.json").read_bytes(), original)

    def test_replacement_failure_rolls_back_existing_pair(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            write_report(sample_report(), folder)
            before = {name: (folder / name).read_bytes() for name in ("report.json", "report.html")}
            actual_replace = os.replace
            failed = False

            def fail_html_install(source, target):
                nonlocal failed
                if (
                    not failed
                    and Path(source).name == "report.html"
                    and Path(target).parent == folder
                ):
                    failed = True
                    raise OSError("simulated disk error")
                return actual_replace(source, target)

            with patch("rankprobe.report.os.replace", side_effect=fail_html_install):
                with self.assertRaises(OSError):
                    write_report({"findings": []}, folder, overwrite=True)
            for name, content in before.items():
                self.assertEqual((folder / name).read_bytes(), content)

    def test_no_overwrite_preserves_report_created_after_initial_check(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory) / "out"
            competing_json = b'{"run_name":"another writer"}\n'
            actual_directory = tempfile.TemporaryDirectory

            @contextmanager
            def competing_directory(*args, **kwargs):
                with actual_directory(*args, **kwargs) as temporary:
                    (folder / "report.json").write_bytes(competing_json)
                    yield temporary

            with patch("rankprobe.report.tempfile.TemporaryDirectory", competing_directory):
                with self.assertRaisesRegex(FileExistsError, "Report already exists"):
                    write_report(sample_report(), folder)
            self.assertEqual((folder / "report.json").read_bytes(), competing_json)
            self.assertFalse((folder / "report.html").exists())

    def test_no_overwrite_install_error_allows_clean_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory) / "out"
            actual_replace = os.replace

            def fail_html_install(source, target):
                if Path(target) == folder / "report.html":
                    raise OSError("simulated output failure")
                return actual_replace(source, target)

            with patch("rankprobe.report.os.replace", side_effect=fail_html_install):
                with self.assertRaisesRegex(OSError, "simulated output failure"):
                    write_report(sample_report(), folder)
            self.assertEqual(list(folder.iterdir()), [])
            json_file, html_file = write_report(sample_report(), folder)
            self.assertTrue(json_file.is_file() and html_file.is_file())

    def test_two_simultaneous_no_overwrite_writers_get_one_report_pair(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory) / "out"
            both_checked = Barrier(2)
            actual_directory = tempfile.TemporaryDirectory

            @contextmanager
            def synchronized_directory(*args, **kwargs):
                both_checked.wait(timeout=10)
                with actual_directory(*args, **kwargs) as temporary:
                    yield temporary

            def write_named(name):
                report = {"report_type": "audit", "run_name": name, "findings": []}
                try:
                    write_report(report, folder)
                    return name, "written"
                except FileExistsError:
                    return name, "refused"

            with patch("rankprobe.report.tempfile.TemporaryDirectory", synchronized_directory):
                with ThreadPoolExecutor(max_workers=2) as pool:
                    results = [future.result() for future in (
                        pool.submit(write_named, "first"), pool.submit(write_named, "second")
                    )]
            self.assertEqual(sorted(status for _, status in results), ["refused", "written"])
            winner = next(name for name, status in results if status == "written")
            report_json = json.loads((folder / "report.json").read_text(encoding="utf-8"))
            report_html = (folder / "report.html").read_text(encoding="utf-8")
            self.assertEqual(report_json["run_name"], winner)
            self.assertIn(f"Run: {winner}", report_html)


if __name__ == "__main__":
    unittest.main()
