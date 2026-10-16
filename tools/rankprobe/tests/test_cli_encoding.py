import json
import os
import subprocess
import sys

import pytest

from rankprobe.cli import _console


def run_cli(arguments, cwd, encoding, *, strict_stderr=False):
    environment = os.environ.copy()
    environment["PYTHONIOENCODING"] = encoding
    if strict_stderr:
        script = (
            "import io,sys; from rankprobe.cli import main; "
            "sys.stderr=io.TextIOWrapper(sys.stderr.buffer,encoding='ascii',errors='strict'); "
            "raise SystemExit(main(sys.argv[1:]))"
        )
        command = [sys.executable, "-c", script, *arguments]
    else:
        command = [sys.executable, "-m", "rankprobe", *arguments]
    return subprocess.run(command, cwd=cwd, env=environment, capture_output=True,
                          timeout=30, check=False)


def predictions(folder, *, unknown=False):
    source = folder / "original scores \U0001f9ea.csv"
    source.write_text(
        "query_id,item_id,score,relevance\nq1,positive,2,1\nq1,other,1,"
        + ("" if unknown else "0") + "\n",
        encoding="utf-8",
    )
    return source


def assert_report_pair(out):
    assert (out / "report.html").is_file()
    return json.loads((out / "report.json").read_text(encoding="utf-8"))


def test_ascii_audit_keeps_success_exit_and_unicode_report_paths(tmp_path):
    source = predictions(tmp_path)
    before = source.read_bytes()
    out = tmp_path / "audit output \U0001f9ea"
    result = run_cli(["audit", str(source), "--out", str(out)], tmp_path, "ascii")
    assert result.returncode == 0
    assert not result.stderr
    stdout = result.stdout.decode("ascii")
    assert r"\U0001f9ea" in stdout
    assert "HTML:" in stdout and "JSON:" in stdout
    assert_report_pair(out)
    assert source.read_bytes() == before


def test_ascii_compare_retains_warning_exit_with_complete_reports(tmp_path):
    source = predictions(tmp_path, unknown=True)
    before = source.read_bytes()
    out = tmp_path / "comparison output \U0001f9ea"
    result = run_cli(["compare", "--run", f"baseline={source}", "--run", f"candidate={source}",
                      "--fail-on", "warning", "--out", str(out)], tmp_path, "ascii")
    assert result.returncode == 1
    assert not result.stderr
    assert r"\U0001f9ea" in result.stdout.decode("ascii")
    report = assert_report_pair(out)
    assert any(finding["severity"] == "warning" for finding in report["findings"])
    assert source.read_bytes() == before


def test_utf8_console_preserves_full_unicode_paths(tmp_path):
    source = predictions(tmp_path)
    out = tmp_path / "UTF8 output \U0001f9ea"
    result = run_cli(["audit", str(source), "--out", str(out)], tmp_path, "utf-8")
    assert result.returncode == 0
    assert not result.stderr
    stdout = result.stdout.decode("utf-8")
    assert str((out / "report.html").resolve()) in stdout
    assert str((out / "report.json").resolve()) in stdout
    assert r"\U0001f9ea" not in stdout
    assert_report_pair(out)


def test_unicode_input_error_on_strict_ascii_stderr_retains_exit_two(tmp_path):
    source = tmp_path / "invalid scores \U0001f9ea.csv"
    source.write_text("query_id,item_id,score\nq1,item,not-a-number\n", encoding="utf-8")
    before = source.read_bytes()
    out = tmp_path / "no report \U0001f9ea"
    result = run_cli(["audit", str(source), "--out", str(out)], tmp_path,
                     "ascii", strict_stderr=True)
    assert result.returncode == 2
    stderr = result.stderr.decode("ascii")
    assert r"\U0001f9ea" in stderr
    assert "score must be a finite number" in stderr
    assert "Traceback" not in stderr
    assert not result.stdout
    assert not out.exists()
    assert source.read_bytes() == before


@pytest.mark.parametrize("error_type", [BrokenPipeError, PermissionError])
def test_console_does_not_swallow_output_io_errors(error_type):
    class FailingStream:
        def write(self, message):
            raise error_type("output unavailable")

    with pytest.raises(error_type, match="output unavailable"):
        _console("status", file=FailingStream())
