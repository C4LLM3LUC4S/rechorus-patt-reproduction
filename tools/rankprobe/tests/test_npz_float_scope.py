"""Accepted NPZ scores must reach the core unchanged or be rejected before output."""

import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

from rankprobe import Protocol, audit_run
from rankprobe.io import read_predictions

np = pytest.importorskip("numpy")
SCRIPT = Path(__file__).resolve().parents[1] / "scripts/export_rechorus.py"
SPEC = importlib.util.spec_from_file_location("float_scope_exporter", SCRIPT)
exporter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(exporter)


@pytest.mark.parametrize("case", ["binary64-adjacent", "extended-adjacent", "extended-range"])
def test_npz_float_scores_are_faithful_or_rejected_before_output(tmp_path, capsys, case):
    dtype = np.float64 if case == "binary64-adjacent" else np.longdouble
    info = np.finfo(dtype)
    if case.startswith("extended") and info.nmant <= np.finfo(np.float64).nmant:
        pytest.skip("This platform's longdouble has no precision beyond binary64")
    if case == "extended-range":
        if info.max <= np.longdouble(np.finfo(np.float64).max):
            pytest.skip("This platform's longdouble has no range beyond binary64")
        first = np.longdouble(np.finfo(np.float64).max) * np.longdouble(2)
    else:
        first = np.nextafter(dtype(1), dtype(2))
    values = np.array([[first, dtype(1)]], dtype=dtype)
    assert np.isfinite(values).all() and values[0, 0] > values[0, 1]
    source = tmp_path / "original-float-capture.npz"
    np.savez(source, scores=values, item_id=np.array([["z-positive", "a-other"]]),
             query_id=np.array(["event-1"]))
    original = source.read_bytes()

    def inspect(path):
        try:
            rows = read_predictions(path)
        except ValueError as exc:
            return {"faithful": False, "readable": False, "error": type(exc).__name__}
        assert [(row.query_id, row.item_id, row.relevance) for row in rows] == [
            ("event-1", "z-positive", 1), ("event-1", "a-other", None),
        ]
        report = audit_run(rows, protocol=Protocol(cutoffs=(1,)))
        assert report["summary"]["unknown_candidates"] == 1
        assert report["summary"]["assumed_nonrelevant_candidates"] == 0
        return {
            "faithful": all(np.longdouble(row.score) == expected
                            for row, expected in zip(rows, values[0])),
            "readable": True, "parsed_scores": [row.score for row in rows],
            "tie_groups": report["tie_analysis"]["tie_groups"],
            "mrr_at_1": report["metrics"]["mrr@1"]["value"],
        }

    api_out = tmp_path / "api-export" / "scores.csv"
    try:
        metadata = exporter.export_npz(source, api_out, positive_index=0, identity="source")
    except ValueError as exc:
        assert case.startswith("extended") and "64 bits" in str(exc)
        assert not api_out.parent.exists()
        api = {"rejected_before_output": True}
    else:
        assert metadata["other_candidates"] == "unknown" and not metadata["qrels_complete"]
        api = inspect(api_out)
    cli_out = tmp_path / "cli-export" / "scores.csv"
    process = subprocess.run(
        [sys.executable, str(SCRIPT), str(source), "--out", str(cli_out),
         "--positive-index", "0", "--identity", "source"],
        capture_output=True, text=True, encoding="utf-8", timeout=30,
    )
    if process.returncode == 2:
        assert case.startswith("extended") and "64 bits" in process.stderr
        assert "Traceback" not in process.stderr and not cli_out.parent.exists()
        cli = {"rejected_before_output": True}
    else:
        assert process.returncode == 0, process.stderr
        cli = inspect(cli_out)
    assert source.read_bytes() == original
    evidence = {
        "case": case, "numpy": np.__version__, "dtype": str(values.dtype),
        "storage_bytes": values.dtype.itemsize, "precision_bits": info.nmant + 1,
        "source_scores": [str(value) for value in values[0]],
        "source_finite_and_distinct": True, "source_unchanged": True,
        "api": api, "cli": cli, "scope": "original synthetic NPZ; no framework run",
    }
    with capsys.disabled():
        print("NPZ_FLOAT_FIDELITY " + json.dumps(evidence, allow_nan=False))
    assert all(result.get("rejected_before_output") or result.get("faithful")
               for result in (api, cli)), evidence
