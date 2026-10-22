from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest

from rankprobe.cli import main


class CliTests(unittest.TestCase):
    def invoke(self, arguments):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(arguments)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_demo_produces_openable_html_and_json(self):
        with tempfile.TemporaryDirectory() as directory:
            code, output, error = self.invoke(["demo", "--out", directory, "--fail-on", "never"])
            self.assertEqual(code, 0, error)
            self.assertIn("HTML:", output)
            report = json.loads((Path(directory) / "report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["run_name"], "built-in-demo")
            self.assertIn("Synthetic", report["demo_note"])
            self.assertTrue((Path(directory) / "report.html").exists())

    def test_missing_input_is_concise(self):
        with tempfile.TemporaryDirectory() as directory:
            code, _, error = self.invoke(
                [
                    "audit",
                    str(Path(directory) / "missing.csv"),
                    "--out",
                    str(Path(directory) / "out"),
                ]
            )
            self.assertEqual(code, 2)
            self.assertIn("rankprobe:", error)
            self.assertNotIn("Traceback", error)

    def test_invalid_input_is_concise_and_no_report_is_written(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            source = folder / "bad.csv"
            source.write_text("query_id,item_id,score\nq,a,not-a-number\n", encoding="utf-8")
            code, _, error = self.invoke(["audit", str(source), "--out", str(folder / "out")])
            self.assertEqual(code, 2)
            self.assertNotIn("Traceback", error)
            self.assertFalse((folder / "out" / "report.html").exists())

    def test_audit_respects_protocol_options(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            source = folder / "run.csv"
            source.write_text(
                "query_id,item_id,score,relevance\nq,a,1,1\nq,b,0,0\n", encoding="utf-8"
            )
            judgments = folder / "qrels.csv"
            judgments.write_text("query_id,item_id,relevance\nq,a,1\nq,b,0\n", encoding="utf-8")
            code, _, error = self.invoke(
                [
                    "audit",
                    str(source),
                    "--qrels",
                    str(judgments),
                    "--out",
                    str(folder / "out"),
                    "--name",
                    "test run",
                    "--cutoffs",
                    "5,1,5",
                    "--gain",
                    "exp2",
                    "--tie-policy",
                    "input",
                    "--unjudged",
                    "nonrelevant",
                    "--qrels-complete",
                ]
            )
            self.assertEqual(code, 0, error)
            report = json.loads((folder / "out" / "report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["run_name"], "test run")
            self.assertEqual(report["protocol"]["cutoffs"], [1, 5])
            self.assertEqual(report["protocol"]["gain"], "exp2")
            self.assertTrue(report["protocol"]["qrels_complete"])
            self.assertEqual(len(report["provenance"]["sources"][0]["sha256"]), 64)
            self.assertNotIn(str(folder), json.dumps(report["provenance"]))

    def test_compare_duplicate_names_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            code, _, error = self.invoke(
                ["compare", "--run", "a=missing.csv", "--run", "a=missing2.csv", "--out", directory]
            )
            self.assertEqual(code, 2)
            self.assertIn("unique", error)

    def test_complete_qrels_declaration_requires_qrels(self):
        with tempfile.TemporaryDirectory() as directory:
            code, _, error = self.invoke(["demo", "--out", directory, "--qrels-complete"])
            self.assertEqual(code, 2)
            self.assertIn("qrels", error)
            self.assertFalse((Path(directory) / "report.json").exists())

    def test_compare_writes_pairwise_comparability_report(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            left, right = folder / "left.csv", folder / "right.jsonl"
            left.write_text(
                "query_id,item_id,score,relevance\nq,a,1,1\nq,b,0,0\n", encoding="utf-8"
            )
            right.write_text(
                "\n".join(
                    json.dumps(row)
                    for row in [
                        {"query_id": "q", "item_id": "a", "score": 0, "relevance": 1},
                        {"query_id": "q", "item_id": "b", "score": 1, "relevance": 0},
                    ]
                ),
                encoding="utf-8",
            )
            code, _, error = self.invoke(
                [
                    "compare",
                    "--run",
                    f"left={left}",
                    "--run",
                    f"right={right}",
                    "--out",
                    str(folder / "out"),
                ]
            )
            self.assertEqual(code, 0, error)
            report = json.loads((folder / "out" / "report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["pairs"][0]["status"], "comparable")
            html = (folder / "out" / "report.html").read_text(encoding="utf-8")
            self.assertIn("Comparison results", html)
            self.assertIn("Matched delta right minus left", html)

    def test_compare_requires_two_runs(self):
        with tempfile.TemporaryDirectory() as directory:
            code, _, error = self.invoke(["compare", "--run", "a=missing.csv", "--out", directory])
            self.assertEqual(code, 2)
            self.assertIn("at least two", error)

    def test_existing_report_needs_explicit_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            first = self.invoke(["demo", "--out", directory, "--fail-on", "never"])
            self.assertEqual(first[0], 0, first[2])
            second = self.invoke(["demo", "--out", directory])
            self.assertEqual(second[0], 2)
            self.assertIn("--overwrite", second[2])
            third = self.invoke(["demo", "--out", directory, "--overwrite", "--fail-on", "never"])
            self.assertEqual(third[0], 0, third[2])

    def test_output_path_shape_errors_do_not_suggest_an_unusable_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output_file = root / "out-file"
            output_file.write_bytes(b"keep this file")
            code, _, error = self.invoke(["demo", "--out", str(output_file)])
            self.assertEqual(code, 2)
            self.assertIn("--out must name a directory", error)
            self.assertNotIn("--overwrite", error)
            self.assertEqual(output_file.read_bytes(), b"keep this file")

            for name in ("report.json", "report.html"):
                with self.subTest(destination=name):
                    output = root / name
                    blocker = output / name
                    blocker.mkdir(parents=True)
                    for extra in ([], ["--overwrite"]):
                        code, _, error = self.invoke(
                            ["demo", "--out", str(output), *extra]
                        )
                        self.assertEqual(code, 2)
                        self.assertIn("A report destination is a directory", error)
                        self.assertNotIn("--overwrite", error)
                        self.assertTrue(blocker.is_dir())
                    self.assertFalse((output / ("report.html" if name == "report.json" else "report.json")).exists())

    def test_fail_on_warning_writes_report_before_failing(self):
        with tempfile.TemporaryDirectory() as directory:
            code, _, error = self.invoke(["demo", "--out", directory, "--fail-on", "warning"])
            self.assertEqual(code, 1, error)
            self.assertTrue((Path(directory) / "report.json").exists())


if __name__ == "__main__":
    unittest.main()
