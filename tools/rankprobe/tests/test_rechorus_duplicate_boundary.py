"""Local exporter/core controls; actual upstream execution belongs to optional CI."""

import csv
import importlib.util
import json
import math
from pathlib import Path

import numpy as np
import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_rechorus_workflow.py"
SPEC = importlib.util.spec_from_file_location("check_rechorus_duplicate_boundary", SCRIPT)
checker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checker)


def fixture_arrays():
    return np.array([[.5, .9, .9, .1]]), np.array([[1, 2, 2, 3]]), np.array(["event"])


def test_duplicate_export_actual_cli_and_separate_planted_oracle(tmp_path):
    arrays = fixture_arrays()
    snapshots = [value.copy() for value in arrays]
    result = checker._check_duplicate_export(tmp_path, np, *arrays, checker._load_exporter())
    assert result["source_item_ids"] == [[1, 2, 2, 3]]
    assert result["unknown_candidates"] == 2
    assert result["assumed_nonrelevant_candidates"] == 0
    directory = tmp_path / "sampled-duplicates"
    sparse = json.loads((directory / "report/report.json").read_text(encoding="utf-8"))
    oracle = json.loads((directory / "explicitly-judged-oracle/report.json").read_text("utf-8"))
    assert sparse["metrics"]["mrr@2"]["excluded_query_ids"] == ["event"]
    assert sparse["metrics"]["ndcg@2"]["value"] is None
    assert sparse["summary"]["duplicate_rows"] == 1
    assert oracle["metrics"]["ndcg@2"]["value"] == pytest.approx(1 / math.log2(3))
    assert oracle["duplicates"]["metric_sensitivity"]["raw_rows"]["ndcg@2"]["value"] == 0
    assert oracle["summary"]["unknown_candidates"] == 0
    with (directory / "predictions.csv").open(encoding="utf-8", newline="") as handle:
        assert [row["relevance"] for row in csv.DictReader(handle)] == ["1", "", "", ""]
    assert all(np.array_equal(value, snapshot) for value, snapshot in zip(arrays, snapshots))


def test_boundary_rejects_an_exporter_that_silently_removes_a_duplicate(tmp_path):
    exporter = checker._load_exporter()

    def dropping_export(source, destination, **kwargs):
        metadata = exporter(source, destination, **kwargs)
        lines = destination.read_text(encoding="utf-8").splitlines(keepends=True)
        destination.write_text("".join(lines[:3] + lines[4:]), encoding="utf-8")
        return metadata

    with pytest.raises(checker.GateError, match="repeated source IDs or score columns were lost"):
        checker._check_duplicate_export(tmp_path, np, *fixture_arrays(), dropping_export)
    assert not (tmp_path / "sampled-duplicates/report").exists()


def test_boundary_rejects_an_exporter_that_assumes_unknowns_are_zero(tmp_path):
    exporter = checker._load_exporter()

    def zero_filling_export(source, destination, **kwargs):
        return exporter(source, destination, **{**kwargs, "other_candidates": "nonrelevant"})

    with pytest.raises(checker.GateError, match="unknown export declaration changed"):
        checker._check_duplicate_export(tmp_path, np, *fixture_arrays(), zero_filling_export)
    assert not (tmp_path / "sampled-duplicates/report").exists()
