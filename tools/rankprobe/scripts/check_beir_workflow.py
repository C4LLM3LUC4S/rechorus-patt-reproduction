"""Check a model-free BEIR export/evaluation workflow with original synthetic data.

BEIR and its export/evaluation dependencies are optional and imported only when
the check runs. This is an integration check, not a retrieval benchmark.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import importlib.metadata as metadata
import json
import math
import os
from pathlib import Path
import platform
import subprocess
import sys


class GateError(ValueError):
    """A named integration check failed without exposing local paths."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise GateError(message)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def new_output_directory(out: Path) -> Path:
    """Validate before optional imports; never reuse existing or linked output."""
    out = Path(out).absolute()
    require(not out.exists() and not out.is_symlink(), "output: directory must be new")
    require(
        not any(parent.is_symlink() for parent in out.parents),
        "output: symbolic-link ancestors are not allowed",
    )
    require(out.parent.is_dir(), "output: parent directory must already exist")
    return out


def new_file(path: Path) -> Path:
    require(not path.exists() and not path.is_symlink(), "output: file must be new")
    return path


def run_comparison(out: Path, original: Path, filtered: Path, qrels: Path) -> dict:
    allowed = (
        "PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "TMPDIR", "LANG",
        "LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH", "LC_ALL", "LC_CTYPE", "LC_MESSAGES",
    )
    environment = {name: os.environ[name] for name in allowed if name in os.environ}
    report_directory = new_file(out / "report")
    try:
        process = subprocess.run(
            [sys.executable, "-I", "-m", "rankprobe", "compare",
             "--run", f"original={original}", "--run", f"filtered={filtered}",
             "--qrels", str(qrels), "--cutoffs", "1,2", "--fail-on", "never",
             "--out", str(report_directory)],
            cwd=out, env=environment, shell=False, check=False, capture_output=True,
            encoding="utf-8", errors="replace", timeout=120,
        )
    except subprocess.TimeoutExpired as exc:
        raise GateError("comparison CLI: exceeded 120 seconds") from exc
    except OSError as exc:
        raise GateError("comparison CLI: could not start subprocess") from exc
    require(process.returncode == 0, "comparison CLI: nonzero exit status")
    # CLI logs contain local paths; retain only the parsed report and named gates.
    require((report_directory / "report.html").is_file(), "comparison CLI: HTML missing")
    require((report_directory / "report.html").stat().st_size > 0,
            "comparison CLI: HTML empty")
    try:
        return json.loads((report_directory / "report.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise GateError("comparison CLI: JSON missing or invalid") from exc


def check_workflow(out: Path) -> dict:
    out = new_output_directory(out)
    try:
        from beir import util
        from beir.retrieval import evaluation
        from rankprobe.io import InputError, read_predictions, read_qrels
    except ImportError as exc:
        raise GateError(
            "imports: install BEIR export/evaluation dependencies and RankProbe first"
        ) from exc
    try:
        versions = {
            name: metadata.version(name)
            for name in ("beir", "torch", "pytrec-eval-terrier", "requests", "tqdm", "numpy", "rankprobe")
        }
    except metadata.PackageNotFoundError as exc:
        raise GateError("versions: an integration dependency has no distribution metadata") from exc
    source_hashes = {}
    for name, module in (("beir.util", util), ("beir.retrieval.evaluation", evaluation)):
        source = Path(module.__file__)
        require(source.suffix == ".py" and source.is_file(), "sources: Python source missing")
        source_hashes[name] = digest(source)

    # The optional packages are already installed. Nothing in this check downloads
    # a dataset, loads a model, trains, or makes a network request.
    out.mkdir(exist_ok=False)
    original = {
        "q1": {"q1": 3.0, "d1": 2.0, "u": 1.0},
        "q2": {"d2": 4.0, "d3": 3.0},
    }
    original_snapshot = deepcopy(original)
    qrels = {"q1": {"q1": 0, "d1": 1}, "q2": {"d2": 1, "d3": 0}}
    qrels_snapshot = deepcopy(qrels)
    original_run = new_file(out / "original.run")
    util.save_runfile(str(original_run), original, run_name="original", top_k=3)

    working = deepcopy(original)
    evaluation.EvaluateRetrieval.evaluate(qrels, working, [1, 2], ignore_identical_ids=True)
    expected_filtered = {"q1": {"d1": 2.0, "u": 1.0}, "q2": {"d2": 4.0, "d3": 3.0}}
    require(working == expected_filtered, "BEIR evaluation: self-match removal differs")
    require(original == original_snapshot, "BEIR evaluation: original results changed")
    require(qrels == qrels_snapshot, "BEIR evaluation: judgments changed")
    filtered_run = new_file(out / "filtered.run")
    util.save_runfile(str(filtered_run), working, run_name="filtered", top_k=3)

    qrels_path = new_file(out / "judgments.qrels")
    with qrels_path.open("x", encoding="utf-8", newline="\n") as handle:
        for query_id, judgments in qrels.items():
            for item_id, relevance in judgments.items():
                handle.write(f"{query_id} 0 {item_id} {relevance}\n")
    native_qrels = new_file(out / "beir-native-qrels.tsv")
    util.write_to_tsv(str(native_qrels), qrels)
    require(
        native_qrels.read_text(encoding="utf-8").splitlines()[0]
        == "query-id\tcorpus-id\tscore",
        "BEIR qrels export: native header differs",
    )
    try:
        read_qrels(native_qrels, format="trec")
    except InputError as exc:
        require("expected exactly 4" in str(exc), "BEIR native TSV: unexpected rejection")
    else:
        raise GateError("BEIR native TSV: unexpectedly accepted as TREC qrels")

    loaded_qrels = read_qrels(qrels_path)
    require(loaded_qrels == qrels, "qrels bridge: actual judgments changed")
    require("u" not in loaded_qrels["q1"], "qrels bridge: missing label was invented")
    loaded_original = read_predictions(original_run)
    loaded_filtered = read_predictions(filtered_run)
    require(len(loaded_original) == 5 and len(loaded_filtered) == 4,
            "runfile bridge: candidate counts differ")
    for rows, expected in ((loaded_original, original), (loaded_filtered, working)):
        require(
            {(row.query_id, row.item_id): row.score for row in rows}
            == {(query_id, item_id): score for query_id, docs in expected.items()
                for item_id, score in docs.items()},
            "runfile bridge: original candidate IDs or scores changed",
        )
    for path in (original_run, filtered_run):
        require(all(line.split()[3] == "0" for line in path.read_text().splitlines()),
                "runfile bridge: expected BEIR zero declared ranks")

    deep_results = {"depth": {f"d{index:04d}": float(1002 - index) for index in range(1002)}}
    default_run = new_file(out / "default-depth.run")
    full_run = new_file(out / "full-depth.run")
    util.save_runfile(str(default_run), deep_results)
    util.save_runfile(str(full_run), deep_results, top_k=1002)
    require(len(read_predictions(default_run)) == 1000,
            "BEIR default export: expected 1000-candidate truncation")
    require(len(read_predictions(full_run)) == 1002,
            "BEIR explicit depth: candidates lost")
    precision_run = new_file(out / "precision.run")
    util.save_runfile(
        str(precision_run), {"precision": {"low": 1.0, "high": 1.0000000000000002}}, top_k=2
    )
    precision_scores = {row.item_id: row.score for row in read_predictions(precision_run)}
    require(precision_scores == {"low": 1.0, "high": 1.0000000000000002},
            "BEIR score export: adjacent floats changed")
    require(precision_scores["low"] != precision_scores["high"],
            "BEIR score export: distinct floats became tied")

    inputs = (original_run, filtered_run, qrels_path, native_qrels,
              default_run, full_run, precision_run)
    hashes_before = {path.name: digest(path) for path in inputs}
    report = run_comparison(out, original_run, filtered_run, qrels_path)
    require(report["report_type"] == "compare", "comparison: wrong report type")
    require(report["protocol"]["unjudged"] == "unknown", "comparison: unknown policy changed")
    require(report["protocol"]["qrels_complete"] is False,
            "comparison: complete judgments were asserted")
    for name, expected in (("original", 0.5), ("filtered", 1.0)):
        run = report["runs"][name]
        require(math.isclose(run["metrics"]["mrr@1"]["value"], expected,
                             rel_tol=0, abs_tol=1e-12),
                "comparison: submitted MRR differs")
        require(run["metrics"]["mrr@1"]["eligible_query_ids"] == ["q1", "q2"],
                "comparison: submitted MRR eligibility differs")
        require(run["audit"]["summary"]["unknown_candidates"] == 1,
                "comparison: unknown candidate lost")
        require(run["metrics"]["ndcg@1"]["excluded_query_ids"] == ["q1"],
                "comparison: unknown NDCG query was not excluded")
        require(run["metrics"]["recall@1"]["value"] is None,
                "comparison: Recall was invented")
    pair = report["pairs"][0]
    require(pair["status"] == "partially_comparable", "comparison: comparability differs")
    matched = pair["matched_pool_comparison"]
    require(matched["status"] == "checked" and matched["query_ids"] == ["q2"],
            "comparison: structurally matched query set differs")
    for side in ("left_metrics", "right_metrics"):
        require(matched[side]["mrr@1"]["value"] == 1.0,
                "comparison: matched MRR differs")
    require(matched["delta_right_minus_left"]["mrr@1"]["delta"] == 0.0,
            "comparison: matched MRR delta differs")
    require(
        {"candidate_set_mismatch", "unknown_judgments"}
        <= {finding["code"] for finding in report["findings"]},
        "comparison: required findings missing",
    )
    sources = {source["filename"]: source for source in report["provenance"]["sources"]}
    require(set(sources) == {original_run.name, filtered_run.name, qrels_path.name},
            "comparison: provenance inputs differ")
    for name, source in sources.items():
        require(source["sha256"] == hashes_before[name], "comparison: source hash differs")
        require(source["input_format"] == "trec", "comparison: input format differs")
    require(all(digest(path) == hashes_before[path.name] for path in inputs),
            "comparison: synthetic input changed")
    require(original == original_snapshot and qrels == qrels_snapshot,
            "integration: original dictionaries changed")

    result = {
        "status": "passed", "python": platform.python_version(), "platform": sys.platform,
        "versions": versions, "beir_source_sha256": source_hashes,
        "synthetic_input_sha256": hashes_before,
        "observations": {
            "original_mrr_at_1": 0.5, "filtered_mrr_at_1": 1.0,
            "structurally_matched_query_ids": ["q2"], "matched_mrr_at_1_delta": 0.0,
            "default_export_candidates": 1000, "explicit_export_candidates": 1002,
        },
        "checks": {
            "real_beir_helpers_called": True, "real_beir_evaluation_called": True,
            "self_match_removal_observed": True, "original_dicts_preserved": True,
            "native_qrels_tsv_explicitly_rejected": True, "zero_declared_rank_accepted": True,
            "unknown_labels_preserved": True, "complete_qrels_not_assumed": True,
            "default_export_truncation_observed": True, "adjacent_float_scores_preserved": True,
            "actual_rankprobe_cli_report": True, "submitted_mrr_change_observed": True,
            "matched_pool_delta_zero": True, "candidate_set_mismatch_reported": True,
            "source_hashes_match": True, "synthetic_inputs_unchanged": True,
        },
        "limitations": [
            "Original synthetic export/evaluation case only; no model or dataset was loaded.",
            "Observed self-match filtering is a declared policy, not evidence of leakage.",
            "Matched IDs and labels do not establish matching provenance or model quality.",
            "This check does not establish universal metric parity with BEIR or human time saved.",
        ],
    }
    with new_file(out / "summary.json").open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(result, handle, indent=2, ensure_ascii=True, allow_nan=False)
        handle.write("\n")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path,
                        help="new directory with an existing, non-symlink parent")
    arguments = parser.parse_args(argv)
    try:
        result = check_workflow(arguments.out)
    except (ValueError, OSError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        reason = str(exc) if isinstance(exc, GateError) else type(exc).__name__
        result = {"status": "failed", "reason": reason}
    print(json.dumps(result, indent=2, ensure_ascii=True, allow_nan=False))
    return int(result["status"] != "passed")


if __name__ == "__main__":
    raise SystemExit(main())
