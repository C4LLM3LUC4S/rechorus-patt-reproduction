"""Execute the read-only qrels preflight from the public BEIR guide."""

import ast
import hashlib
from pathlib import Path
import subprocess
import sys

import pytest


DOC = Path(__file__).resolve().parents[1] / "docs/beir-workflow.md"
HEADER = "query-id\tcorpus-id\tscore\n"
PLACEHOLDER = 'Path("/absolute/path/to/permitted-dataset/qrels/test.tsv")'


def invoke(tmp_path, body):
    folder = tmp_path / "source files with spaces"
    folder.mkdir()
    source = folder / "原始 judgments.tsv"
    source.write_text(body, encoding="utf-8")
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    section = DOC.read_text(encoding="utf-8").split(
        "## Check ordinary qrels rows before loading\n", 1
    )[1].split("\n## Keep split loading independent", 1)[0]
    block = section.split("```python\n", 1)[1].split("\n```", 1)[0]
    assert block.count(PLACEHOLDER) == 1
    ast.parse(block)
    code = block.replace(PLACEHOLDER, f"Path({str(source)!r})")
    cwd = tmp_path / "different working directory"
    cwd.mkdir()
    result = subprocess.run(
        [sys.executable, "-X", "utf8", "-c", code], cwd=cwd, shell=False, check=False,
        capture_output=True, text=True, encoding="utf-8", errors="strict", timeout=30,
    )
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before
    assert list(folder.iterdir()) == [source]
    assert list(cwd.iterdir()) == []
    return result


@pytest.mark.parametrize(
    "body, message",
    [
        (HEADER + "qA\tdA\t1\nqA\tdA\t0\n", "repeated query-document pair"),
        (HEADER + "qA\tdA\t0\nqA\tdA\t1\n", "repeated query-document pair"),
        (HEADER + "qA\tdA\t1\nqA\tdA\t1\n", "repeated query-document pair"),
        ("query-id\tcorpus-id\trelevance\nqA\tdA\t1\n", "expected query-id"),
        (HEADER + "qA\tdA\n", "expected three fields"),
        (HEADER + "qA\tdA\t1\textra\n", "expected three fields"),
        (HEADER + "\tdA\t1\n", "nonblank IDs"),
        (HEADER + "qA\t \t1\n", "nonblank IDs"),
        ("", "expected query-id"),
    ],
)
def test_preflight_rejects_repeated_or_malformed_rows_without_writing(tmp_path, body, message):
    result = invoke(tmp_path, body)
    assert result.returncode != 0
    assert result.stdout == ""
    assert message in result.stderr


def test_preflight_leaves_supplied_grade_strings_and_source_unchanged(tmp_path):
    result = invoke(tmp_path, HEADER + "qA\td1\t1\nqA\td0\t0\nqA\tdu\t-1\n")
    assert result.returncode == 0, result.stderr
    assert result.stdout == result.stderr == ""


def test_preflight_accepts_bom_without_rewriting_grade_strings_or_source(tmp_path):
    result = invoke(tmp_path, "\ufeff" + HEADER + "qA\td1\t1\nqA\td0\t0\nqA\tdu\t-1\n")
    assert result.returncode == 0, result.stderr
    assert result.stdout == result.stderr == ""


def test_preflight_still_rejects_conflicting_pairs_after_bom_header(tmp_path):
    result = invoke(tmp_path, "\ufeff" + HEADER + "qA\tdA\t1\nqA\tdA\t0\n")
    assert result.returncode != 0
    assert result.stdout == ""
    assert "repeated query-document pair" in result.stderr
    assert "expected query-id" not in result.stderr
