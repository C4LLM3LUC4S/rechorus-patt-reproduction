import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from rankprobe.report import render_html, write_report


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


if __name__ == "__main__":
    unittest.main()
