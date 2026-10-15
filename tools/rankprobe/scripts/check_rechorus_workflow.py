"""Check an actual sampled one-positive ReChorus prediction/export workflow.

Original synthetic fixtures exercise the pinned upstream Dataset and Runner.
No benchmark data is loaded, and no model is trained. Full-sort/test_all,
sequential models, CTR and list-wise reranking are outside this check's scope.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import importlib.metadata as metadata
import importlib.util
import json
import math
import os
from pathlib import Path
import platform
import subprocess
import sys
from types import SimpleNamespace


SOURCE_COMMIT = "c164ec4303cc20ddcfbd1b57de366a481811d1e5"
SOURCE_SHA256 = {
    "helpers.BaseRunner": "75e45a2c2afe7ac99176a32e84d80034be1b0583cefd6807d591cfe4a924a4f2",
    "models.BaseModel": "4f9c88ffd9392715485eff976fb9822cfb16ba61ec637801c6f85fadb9f3f8d4",
    "utils.utils": "5d90dc1a36dff898a71b4aad167bd90852b9c0ad84e7e7b185467b03e8461792",
    "helpers.BaseReader": "02f70f5d855b6af7f7f45fc186e67eb08d2041279afa68d00129b1ae49b4bcd9",
}


class GateError(ValueError):
    """A named check failed without exposing local paths."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise GateError(message)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def new_output_directory(out: Path) -> Path:
    out = Path(out).absolute()
    require(not out.exists() and not out.is_symlink(), "output: directory must be new")
    require(not any(parent.is_symlink() for parent in out.parents),
            "output: symbolic-link ancestors are not allowed")
    require(out.parent.is_dir(), "output: parent directory must already exist")
    return out


def validated_source(source: Path) -> tuple[Path, dict]:
    source = Path(source).absolute()
    require(source.is_dir() and not source.is_symlink(), "source: directory is unavailable")
    require(not any(parent.is_symlink() for parent in source.parents),
            "source: symbolic-link ancestors are not allowed")
    hashes = {}
    for name in SOURCE_SHA256:
        path = source / "src" / (name.replace(".", "/") + ".py")
        require(path.is_file() and not path.is_symlink(), "source: required upstream file missing")
        require(not any(parent.is_symlink() for parent in path.parents),
                "source: symbolic-link ancestors are not allowed")
        hashes[name] = digest(path)
    require(hashes == SOURCE_SHA256, "source: upstream files differ from pinned source")
    return source, hashes


def _upstream_modules(source: Path):
    original_path = list(sys.path)
    sys.path.insert(0, str(source / "src"))
    try:
        runner = importlib.import_module("helpers.BaseRunner")
        model = importlib.import_module("models.BaseModel")
    finally:
        sys.path[:] = original_path
    for name, module in (("helpers.BaseRunner", runner), ("models.BaseModel", model)):
        expected = source / "src" / (name.replace(".", "/") + ".py")
        require(Path(module.__file__).resolve() == expected.resolve(),
                "imports: upstream module was loaded from a different checkout")
        require(digest(Path(module.__file__)) == SOURCE_SHA256[name],
                "imports: upstream source bytes changed")
    for name in ("utils.utils", "helpers.BaseReader"):
        module = sys.modules.get(name)
        require(module is not None and Path(module.__file__).resolve()
                == (source / "src" / (name.replace(".", "/") + ".py")).resolve(),
                "imports: upstream dependency was loaded from a different checkout")
        require(digest(Path(module.__file__)) == SOURCE_SHA256[name],
                "imports: upstream dependency source bytes changed")
    return runner.BaseRunner, model.GeneralModel


def _load_exporter():
    spec = importlib.util.spec_from_file_location(
        "rankprobe_rechorus_exporter", Path(__file__).with_name("export_rechorus.py")
    )
    require(spec is not None and spec.loader is not None, "exporter: source missing")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.export_npz


def _fixtures(np, pd, torch, BaseRunner, GeneralModel):
    # Each row is an independent prediction context, despite the repeated user.
    corpus = SimpleNamespace(
        n_users=8, n_items=103,
        data_df={"test": pd.DataFrame({
            "user_id": [7, 7], "item_id": [101, 102],
            "neg_items": [np.array([*range(1, 101), 102]),
                          np.array([*range(1, 101), 101])],
        })},
    )
    model_args = SimpleNamespace(
        device=torch.device("cpu"), model_path="unused-synthetic.pt", buffer=0,
        num_neg=101, dropout=0, test_all=False,
    )

    class Model(GeneralModel):
        def __init__(self):
            super().__init__(model_args, corpus)
            table = torch.arange(103, dtype=torch.float64) / 1024
            table[101:] = .75
            self.register_buffer("score_table", table)

        def forward(self, feed_dict):
            return {"prediction": self.score_table[feed_dict["item_id"]].clone()}

    model = Model()
    dataset = GeneralModel.Dataset(model, corpus, "test")
    dataset.prepare()
    parser = BaseRunner.parse_runner_args(argparse.ArgumentParser())
    runner_args = parser.parse_args([])
    runner_args.train = 0
    runner_args.log_file = "synthetic.log"
    runner_args.eval_batch_size = 1
    runner_args.num_workers = 0
    runner_args.pin_memory = 0
    runner = BaseRunner(runner_args)
    return corpus, model, dataset, runner


def _run_cli(out: Path, arguments: list[str]) -> subprocess.CompletedProcess:
    allowed = (
        "PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "TMPDIR", "LANG",
        "LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH", "LC_ALL", "LC_CTYPE", "LC_MESSAGES",
    )
    environment = {name: os.environ[name] for name in allowed if name in os.environ}
    try:
        return subprocess.run(
            [sys.executable, "-I", "-m", "rankprobe", *arguments],
            cwd=out, env=environment, shell=False, check=False, capture_output=True,
            encoding="utf-8", errors="replace", timeout=120,
        )
    except subprocess.TimeoutExpired as exc:
        raise GateError("RankProbe CLI: exceeded 120 seconds") from exc
    except OSError as exc:
        raise GateError("RankProbe CLI: could not start subprocess") from exc


def run_audit(out: Path, predictions: Path) -> dict:
    report_directory = new_output_directory(out / "report")
    process = _run_cli(out, [
        "audit", str(predictions), "--name", "sampled", "--cutoffs", "1,2",
        "--fail-on", "never", "--out", str(report_directory),
    ])
    require(process.returncode == 0, "RankProbe CLI: nonzero exit status")
    html = report_directory / "report.html"
    require(html.is_file() and html.stat().st_size > 0, "RankProbe CLI: HTML missing or empty")
    try:
        return json.loads((report_directory / "report.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise GateError("RankProbe CLI: JSON missing or invalid") from exc


def check_workflow(out: Path, source: Path) -> dict:
    out = new_output_directory(out)
    source, source_hashes = validated_source(source)
    try:
        import numpy as np
        import pandas as pd
        import torch
        from rankprobe.io import read_predictions
        from rankprobe.metrics import evaluate_metrics
        from rankprobe.model import Protocol, Row
        BaseRunner, GeneralModel = _upstream_modules(source)
    except ImportError as exc:
        raise GateError("imports: install optional ReChorus helper dependencies and RankProbe first") from exc
    try:
        versions = {name: metadata.version(name) for name in (
            "torch", "numpy", "pandas", "tqdm", "rankprobe",
        )}
    except metadata.PackageNotFoundError as exc:
        raise GateError("versions: an integration dependency has no distribution metadata") from exc
    export_npz = _load_exporter()

    corpus, model, dataset, runner = _fixtures(np, pd, torch, BaseRunner, GeneralModel)
    candidates_before = np.stack([dataset[index]["item_id"] for index in range(len(dataset))])
    users_before = np.array(dataset.data["user_id"], copy=True)
    targets_before = np.array(dataset.data["item_id"], copy=True)
    negatives_before = np.stack(dataset.data["neg_items"]).copy()
    model_before = model.score_table.clone()
    predictions = runner.predict(dataset)
    predictions_before = predictions.copy()
    require(predictions.shape == (2, 102), "ReChorus prediction: full sampled candidate count differs")
    require(np.array_equal(predictions, model_before.numpy()[candidates_before]),
            "ReChorus prediction: scores or dataset row/column alignment changed")
    require(np.array_equal(candidates_before[:, 0], targets_before),
            "ReChorus Dataset: ground-truth target is not the first candidate")
    require(np.array_equal(users_before, [7, 7]), "ReChorus Dataset: repeated contexts differ")
    require(np.isfinite(predictions).all(), "ReChorus prediction: unexpected non-finite sampled scores")

    out.mkdir(exist_ok=False)
    archive = out / "full-sampled-predictions.npz"
    with archive.open("xb") as handle:
        np.savez(handle, scores=predictions, item_id=candidates_before, user_id=users_before)
    archive_hash = digest(archive)
    exported_csv = out / "predictions.csv"
    export_metadata = export_npz(archive, exported_csv, positive_index=0,
                                 other_candidates="unknown")
    require(export_metadata["source_sha256"] == archive_hash,
            "export: source NPZ hash differs")
    require(export_metadata["exported_rows"] == 204
            and export_metadata["candidates_per_query"] == 102,
            "export: candidates were truncated")
    require(export_metadata["positive_index"] == 0
            and export_metadata["other_candidates"] == "unknown"
            and export_metadata["qrels_complete"] is False,
            "export: positive-column or unknown-label declaration changed")
    require(export_metadata["user_ids_exported"] is False,
            "export: source user IDs were unexpectedly exported")
    metadata_path = exported_csv.with_suffix(".csv.metadata.json")
    require(json.loads(metadata_path.read_text(encoding="utf-8")) == export_metadata,
            "export: written metadata differs")
    rows = read_predictions(exported_csv)
    query_ids = ["query_000001", "query_000002"]
    require(sorted({row.query_id for row in rows}) == query_ids,
            "export: repeated-user contexts were merged")
    source_to_exported = {}
    for row_index, query_id in enumerate(query_ids):
        query_rows = [row for row in rows if row.query_id == query_id]
        require(len(query_rows) == 102, "export: per-context candidate count differs")
        require([row.score for row in query_rows] == predictions[row_index].tolist(),
                "export: original finite scores or source column order changed")
        require(query_rows[0].relevance == 1.0
                and all(row.relevance is None for row in query_rows[1:]),
                "export: undeclared nonpositive labels were invented")
        for source_item, row in zip(candidates_before[row_index], query_rows):
            source_item = int(source_item)
            require(source_to_exported.setdefault(source_item, row.item_id) == row.item_id,
                    "export: item mapping changed within this export")
    require(len(source_to_exported) == 102 and len(set(source_to_exported.values())) == 102,
            "export: item mapping is not one-to-one within this export")

    # A separate, explicitly fully judged original synthetic oracle isolates the
    # tie policy. These zeros are never supplied to the default unknown-label run.
    tie_rows = [Row(row.query_id, row.item_id, row.score,
                    1.0 if index == 0 else 0.0)
                for index, row in enumerate(rows[:102])]
    rankprobe_tie = evaluate_metrics(tie_rows, Protocol(cutoffs=(1, 2)))
    upstream_tie = BaseRunner.evaluate_method(predictions[:1], [1, 2], ["HR", "NDCG"])
    require(upstream_tie["HR@1"] == 0.0 and upstream_tie["NDCG@1"] == 0.0,
            "tie boundary: upstream pessimistic positive rank differs")
    require(upstream_tie["HR@2"] == 1.0
            and math.isclose(upstream_tie["NDCG@2"], 1 / math.log2(3)),
            "tie boundary: upstream second-place positive rank differs")
    require(rankprobe_tie["ndcg@1"]["value"] == 1.0
            and rankprobe_tie["mrr@1"]["value"] == 1.0,
            "tie boundary: RankProbe lexical positive rank differs")

    inputs = (archive, exported_csv, metadata_path)
    hashes_before = {path.name: digest(path) for path in inputs}
    report = run_audit(out, exported_csv)
    require(report["report_type"] == "audit", "audit: wrong report type")
    require(report["protocol"]["unjudged"] == "unknown"
            and report["protocol"]["qrels_complete"] is False,
            "audit: unknown/completeness policy changed")
    require(report["summary"]["unknown_candidates"] == 202,
            "audit: unknown sampled candidates were lost")
    require(report["metrics"]["mrr@1"]["eligible_query_ids"] == ["query_000001"]
            and report["metrics"]["mrr@1"]["excluded_query_ids"] == ["query_000002"],
            "audit: unknown top-ranked candidate eligibility differs")
    require(report["metrics"]["mrr@1"]["value"] == 1.0
            and report["metrics"]["mrr@2"]["value"] is None,
            "audit: missing labels were treated as zero")
    require(report["metrics"]["ndcg@1"]["value"] is None
            and report["metrics"]["recall@1"]["value"] is None,
            "audit: unsupported NDCG or Recall was invented")
    require("score_ties" in {finding["code"] for finding in report["findings"]},
            "audit: actual tied scores were not reported")
    sources = report["provenance"]["sources"]
    require(len(sources) == 1 and sources[0]["filename"] == exported_csv.name
            and sources[0]["sha256"] == hashes_before[exported_csv.name],
            "audit: input provenance hash differs")
    require({path.name: digest(path) for path in inputs} == hashes_before
            and digest(archive) == archive_hash, "integration: synthetic source files changed")
    require(np.array_equal(predictions, predictions_before)
            and torch.equal(model.score_table, model_before),
            "integration: original prediction or model score table changed")
    require(np.array_equal(np.stack([dataset[index]["item_id"]
                                    for index in range(len(dataset))]), candidates_before)
            and np.array_equal(dataset.data["user_id"], users_before)
            and np.array_equal(dataset.data["item_id"], targets_before)
            and np.array_equal(np.stack(dataset.data["neg_items"]), negatives_before),
            "integration: original dataset contexts or candidates changed")
    require(corpus.data_df["test"]["user_id"].tolist() == [7, 7],
            "integration: original corpus user rows changed")

    result = {
        "status": "passed", "python": platform.python_version(), "platform": sys.platform,
        "versions": versions, "rechorus_commit": SOURCE_COMMIT,
        "rechorus_source_sha256": source_hashes, "synthetic_input_sha256": hashes_before,
        "observations": {
            "prediction_contexts": 2, "distinct_source_users": 1,
            "candidates_per_context": 102, "exported_rows": 204,
            "unknown_candidates": 202, "declared_positive_column": 0,
            "explicit_synthetic_tie_oracle": {
                "upstream_hr_at_1": float(upstream_tie["HR@1"]),
                "upstream_ndcg_at_1": float(upstream_tie["NDCG@1"]),
                "rankprobe_ndcg_at_1": rankprobe_tie["ndcg@1"]["value"],
                "interpretation": "different declared tie policies; not numerical parity",
            },
        },
        "checks": {
            "actual_upstream_dataset_constructor_and_prepare_called": True,
            "actual_upstream_get_feed_dict_and_collate_called": True,
            "actual_upstream_runner_predict_called": True,
            "actual_upstream_evaluate_method_called": True,
            "loaded_modules_match_pinned_checkout": True,
            "ground_truth_first_column_verified": True,
            "full_sampled_candidates_preserved_before_truncation": True,
            "existing_npz_exporter_used": True,
            "repeated_source_user_contexts_kept_separate": True,
            "original_finite_scores_and_column_order_preserved": True,
            "within_export_item_mapping_consistent": True,
            "unknown_labels_preserved": True,
            "complete_qrels_not_assumed": True,
            "explicit_synthetic_tie_policy_difference_observed": True,
            "actual_rankprobe_cli_report": True,
            "source_hashes_and_inputs_unchanged": True,
        },
        "limitations": [
            "Original synthetic sampled one-positive fixtures only; no benchmark data was loaded or used.",
            "Actual GeneralModel Dataset and BaseRunner are used; no trained recommendation model is evaluated.",
            "Positive column zero is a checked fixture convention and a caller assertion for other inputs.",
            "Query IDs represent matrix rows; item pseudonyms are local to this export, not portable cross-run identities.",
            "The separate tie oracle supplies explicit synthetic zeros; the default exported run preserves unknown labels.",
            "No full-sort, sequential, CTR, reranking, universal metric parity, adoption or human time saved is established.",
        ],
    }
    with (out / "summary.json").open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(result, handle, indent=2, ensure_ascii=True, allow_nan=False)
        handle.write("\n")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path,
                        help="new directory with an existing, non-symlink parent")
    parser.add_argument("--source", required=True, type=Path,
                        help="checksum-verified pinned ReChorus checkout root containing src")
    arguments = parser.parse_args(argv)
    try:
        result = check_workflow(arguments.out, arguments.source)
    except (ValueError, OSError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        reason = str(exc) if isinstance(exc, GateError) else type(exc).__name__
        result = {"status": "failed", "reason": reason}
    print(json.dumps(result, indent=2, ensure_ascii=True, allow_nan=False))
    return int(result["status"] != "passed")


if __name__ == "__main__":
    raise SystemExit(main())
