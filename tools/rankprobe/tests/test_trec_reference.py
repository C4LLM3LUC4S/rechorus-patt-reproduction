import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_trec_eval.py"
SPEC = importlib.util.spec_from_file_location("check_trec_eval", SCRIPT)
checker = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = checker
SPEC.loader.exec_module(checker)


def test_reference_output_requires_unique_finite_three_column_values():
    assert checker.parse_output("recip_rank\tq1\t0.5000\n\nrecip_rank all 0.5000\n") == {
        ("recip_rank", "q1"): .5, ("recip_rank", "all"): .5,
    }


@pytest.mark.parametrize("output", [
    "", " \n", "recip_rank q1", "recip_rank q1 1 extra",
    "recip_rank q1 not-a-number", "recip_rank q1 NaN", "recip_rank q1 inf",
    "recip_rank q1 1e999", "recip_rank q1 1\nrecip_rank q1 0\n",
])
def test_malformed_or_ambiguous_reference_output_fails(output):
    with pytest.raises(checker.GateError):
        checker.parse_output(output)


def test_shared_cases_actually_satisfy_declared_protocol():
    cases = [*checker._fixed_cases(), *checker._seeded_cases()]
    assert len(cases) == 24
    for case in cases:
        assert set(case.qrels) == {row.query_id for row in case.rows}
        for query, labels in case.qrels.items():
            rows = [row for row in case.rows if row.query_id == query]
            assert len({row.item_id for row in rows}) == len(rows)
            assert len({row.score for row in rows}) == len(rows)
            assert all(row.item_id in labels and row.relevance is None for row in rows)
            assert all(type(grade) is int and grade >= 0 for grade in labels.values())
            assert any(grade > 0 for grade in labels.values())


def test_zero_returning_engine_with_valid_output_keys_fails_the_numerical_gate(tmp_path, monkeypatch):
    executable = tmp_path / "reference"
    executable.write_bytes(b"test placeholder; subprocess is replaced")

    def zero_engine(executable, arguments, root):
        if arguments == ["-v"]:
            return subprocess.CompletedProcess([], 0, "", "trec_eval version test\n")
        queries = sorted({line.split()[0] for line in Path(arguments[-2]).read_text().splitlines()})
        measures = [arguments[i + 1].replace(".", "_")
                    for i, argument in enumerate(arguments) if argument == "-m"]
        output = "".join(f"{measure} {query} 0.0000\n"
                         for measure in measures for query in [*queries, "all"])
        return subprocess.CompletedProcess([], 0, output, "")

    monkeypatch.setattr(checker, "_run", zero_engine)
    with pytest.raises(checker.GateError, match="numerical mismatch"):
        checker.check_reference(executable)


def test_existing_summary_is_refused_before_executing_reference(tmp_path, monkeypatch):
    summary = tmp_path / "keep.json"
    summary.write_bytes(b"original summary")
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "--trec-eval", "missing", "--summary", str(summary)])
    with pytest.raises(SystemExit) as caught:
        checker.main()
    assert caught.value.code == 2
    assert summary.read_bytes() == b"original summary"


def test_missing_executable_has_a_path_free_failure_summary(tmp_path, monkeypatch, capsys):
    missing, summary = tmp_path / "private-binary-name", tmp_path / "failure.json"
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "--trec-eval", str(missing), "--summary", str(summary)])
    assert checker.main() == 1
    output = capsys.readouterr().out
    assert "private-binary-name" not in output
    assert json.loads(summary.read_text())["status"] == "failed"
