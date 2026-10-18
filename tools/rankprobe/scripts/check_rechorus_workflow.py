"""Check actual sampled and native full-sort ReChorus prediction/export workflows.

Original synthetic fixtures exercise the pinned upstream Dataset and Runner.
No benchmark data is loaded, and no model is trained. A separate full-sort
reader/runner probe checks a mask-aware export for the pinned native contract.
Sequential models, CTR and list-wise reranking are outside this check's scope.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
import csv
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


def _load_full_sort_exporter():
    spec = importlib.util.spec_from_file_location(
        "rankprobe_rechorus_full_sort_exporter",
        Path(__file__).with_name("export_rechorus_full_sort.py"),
    )
    require(spec is not None and spec.loader is not None, "full-sort exporter: source missing")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.export_full_sort


def _model_arguments(GeneralModel, torch, *, test_all: int, num_neg: int):
    parser = GeneralModel.parse_model_args(argparse.ArgumentParser())
    arguments = parser.parse_args([])
    require(arguments.buffer == 1 and arguments.test_all == 0,
            "upstream model parser: expected default buffer=1 and test_all=0")
    arguments.device = torch.device("cpu")
    arguments.model_path = "unused-synthetic.pt"
    arguments.test_all, arguments.num_neg = test_all, num_neg
    return arguments


def _cache_snapshot(dataset, np) -> dict:
    require(isinstance(dataset.buffer_dict, dict)
            and set(dataset.buffer_dict) == set(range(len(dataset))),
            "upstream prepared cache: expected one native cached feed per context")
    return {index: {field: np.asarray(value).copy() for field, value in feed.items()}
            for index, feed in dataset.buffer_dict.items()}


def _cache_unchanged(dataset, snapshot: dict, np) -> bool:
    if set(dataset.buffer_dict) != set(snapshot):
        return False
    for index, expected in snapshot.items():
        actual = dataset.buffer_dict[index]
        if set(actual) != set(expected):
            return False
        for field, value in expected.items():
            actual_value = np.asarray(actual[field])
            if actual_value.dtype != value.dtype or not np.array_equal(actual_value, value):
                return False
    return True


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
    model_args = _model_arguments(GeneralModel, torch, test_all=0, num_neg=101)

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


def run_audit(out: Path, predictions: Path, *, name: str = "sampled") -> dict:
    report_directory = new_output_directory(out / "report")
    process = _run_cli(out, [
        "audit", str(predictions), "--name", name, "--cutoffs", "1,2",
        "--fail-on", "never", "--out", str(report_directory),
    ])
    require(process.returncode == 0, "RankProbe CLI: nonzero exit status")
    html = report_directory / "report.html"
    require(html.is_file() and html.stat().st_size > 0, "RankProbe CLI: HTML missing or empty")
    try:
        return json.loads((report_directory / "report.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise GateError("RankProbe CLI: JSON missing or invalid") from exc


def _check_duplicate_export(out: Path, np, scores, candidates, event_ids, export_npz) -> dict:
    """Keep the sparse export separate from an explicitly judged synthetic oracle."""
    from rankprobe.audit import audit_run
    from rankprobe.io import read_predictions
    from rankprobe.model import Protocol, Row
    from rankprobe.report import write_report

    directory = new_output_directory(out / "sampled-duplicates")
    directory.mkdir(exist_ok=False)
    snapshots = [value.copy() for value in (scores, candidates, event_ids)]
    archive = directory / "duplicate-scores.npz"
    with archive.open("xb") as handle:
        np.savez(handle, scores=scores, item_id=candidates, query_id=event_ids)
    archive_hash = digest(archive)
    destination = directory / "predictions.csv"
    metadata = export_npz(archive, destination, positive_index=0,
                          other_candidates="unknown", identity="source")
    sidecar = destination.with_suffix(".csv.metadata.json")
    require(metadata["source_sha256"] == archive_hash
            and metadata["identity_mode"] == "source"
            and metadata["other_candidates"] == "unknown"
            and metadata["qrels_complete"] is False,
            "sampled duplicates: source identity or unknown export declaration changed")
    rows = read_predictions(destination)
    require(len(rows) == 4 and [row.item_id for row in rows] == ["1", "2", "2", "3"]
            and [row.query_id for row in rows] == [str(event_ids[0])] * 4
            and [row.score for row in rows] == scores[0].tolist(),
            "sampled duplicates: repeated source IDs or score columns were lost")
    require([row.relevance for row in rows] == [1, None, None, None],
            "sampled duplicates: exported unknown labels were filled")
    require(json.loads(sidecar.read_text(encoding="utf-8")) == metadata,
            "sampled duplicates: written sidecar differs")
    inputs = (archive, destination, sidecar)
    hashes = {path.name: digest(path) for path in inputs}
    report = run_audit(directory, destination, name="synthetic-sampled-duplicates")
    require(report["summary"]["rows"] == 4
            and report["summary"]["unique_candidates"] == 3
            and report["summary"]["duplicate_rows"] == 1
            and report["summary"]["judged_candidates"] == 1
            and report["summary"]["unknown_candidates"] == 2
            and report["summary"]["assumed_nonrelevant_candidates"] == 0
            and report["protocol"]["unjudged"] == "unknown"
            and report["protocol"]["qrels_complete"] is False,
            "sampled duplicates: CLI changed candidate or judgment counts")
    require(report["metrics"]["mrr@2"]["value"] is None
            and report["metrics"]["ndcg@2"]["value"] is None
            and "duplicate_candidates" in {finding["code"] for finding in report["findings"]},
            "sampled duplicates: CLI invented sparse metrics or missed repetitions")

    # These planted labels belong only to this invented oracle, never the CSV.
    oracle_rows = [Row(row.query_id, row.item_id, row.score, int(index == 0))
                   for index, row in enumerate(rows)]
    oracle = audit_run(oracle_rows, Protocol(cutoffs=(2,)),
                       run_name="explicitly-judged-synthetic-duplicate-oracle")
    unique = oracle["metrics"]["ndcg@2"]["value"]
    raw = oracle["duplicates"]["metric_sensitivity"]["raw_rows"]["ndcg@2"]["value"]
    require(math.isclose(unique, 1 / math.log2(3), rel_tol=0, abs_tol=1e-14)
            and raw == 0,
            "sampled duplicates: planted-label unique and raw-row ranks differ from oracle")
    write_report(oracle, directory / "explicitly-judged-oracle")
    require({path.name: digest(path) for path in inputs} == hashes
            and all(np.array_equal(value, snapshot) for value, snapshot
                    in zip((scores, candidates, event_ids), snapshots)),
            "sampled duplicates: original arrays or exported source files changed")
    return {
        "event_ids": event_ids.tolist(), "source_item_ids": candidates.tolist(),
        "scores": scores.tolist(), "exported_rows": 4, "unique_candidates": 3,
        "duplicate_rows": 1, "known_candidates": 1, "unknown_candidates": 2,
        "assumed_nonrelevant_candidates": 0, "qrels_complete": False,
        "sparse_mrr_at_2": None, "sparse_ndcg_at_2": None,
        "explicit_synthetic_oracle_unique_ndcg_at_2": unique,
        "explicit_synthetic_oracle_raw_row_ndcg_at_2": raw,
        "source_files_sha256": hashes,
    }


def _check_sampled_duplicate_workflow(out: Path, np, pd, torch,
                                      BaseRunner, GeneralModel, export_npz) -> dict:
    """Exercise repeated supplied negatives through the genuine prepared runner."""
    corpus = SimpleNamespace(n_users=8, n_items=4, data_df={"test": pd.DataFrame({
        "user_id": [7], "item_id": [1], "neg_items": [np.array([2, 2, 3])],
    })})
    model_args = _model_arguments(GeneralModel, torch, test_all=0, num_neg=3)

    class Model(GeneralModel):
        def __init__(self):
            super().__init__(model_args, corpus)
            self.register_buffer("score_table", torch.tensor([0, .5, .9, .1], dtype=torch.float64))

        def forward(self, feed_dict):
            return {"prediction": self.score_table[feed_dict["item_id"]].clone()}

    model = Model()
    dataset = GeneralModel.Dataset(model, corpus, "test")
    dataset.prepare()
    cached_feeds = _cache_snapshot(dataset, np)
    candidates = np.stack([dataset[0]["item_id"]])
    users_before = np.array(dataset.data["user_id"], copy=True)
    targets_before = np.array(dataset.data["item_id"], copy=True)
    negatives_before = np.stack(dataset.data["neg_items"]).copy()
    table_before, training_before = model.score_table.clone(), model.training
    parser = BaseRunner.parse_runner_args(argparse.ArgumentParser())
    arguments = parser.parse_args([])
    arguments.train, arguments.log_file, arguments.eval_batch_size = 0, "synthetic.log", 1
    arguments.num_workers, arguments.pin_memory = 0, 0
    runner = BaseRunner(arguments)
    try:
        scores = runner.predict(dataset)
    finally:
        model.train(training_before)
    scores_before = scores.copy()
    require(np.array_equal(candidates, [[1, 2, 2, 3]])
            and np.array_equal(scores, [[.5, .9, .9, .1]])
            and np.all(scores[:, 1:] != scores[:, :1]),
            "sampled duplicates: native fixture layout or positive no-tie condition differs")
    native = BaseRunner.evaluate_method(scores, [2], ["NDCG"])
    require(native["NDCG@2"] == 0,
            "sampled duplicates: native column-count NDCG differs from rank-three oracle")
    observations = _check_duplicate_export(
        out, np, scores, candidates, np.array(["synthetic-duplicate-event"]), export_npz,
    )
    require(model.buffer == 1 and model.test_all == 0 and model.training == training_before
            and torch.equal(model.score_table, table_before)
            and np.array_equal(scores, scores_before)
            and np.array_equal(dataset[0]["item_id"], candidates[0])
            and np.array_equal(dataset.data["user_id"], users_before)
            and np.array_equal(dataset.data["item_id"], targets_before)
            and np.array_equal(np.stack(dataset.data["neg_items"]), negatives_before)
            and _cache_unchanged(dataset, cached_feeds, np)
            and corpus.data_df["test"]["neg_items"][0].tolist() == [2, 2, 3],
            "sampled duplicates: source fixture, prepared cache or model state changed")
    observations.update({
        "native_column_rank": 3, "native_ndcg_at_2": float(native["NDCG@2"]),
        "prepared_cached_feed_rows": len(cached_feeds), "positive_score_tie": False,
        "interpretation": "Repeated negative columns versus unique-item ranking, not metric parity or a benchmark correction.",
    })
    return observations


def _check_full_sort_workflow(out: Path, np, torch, BaseRunner, GeneralModel, export_npz) -> dict:
    """Check the exact native full-sort contract; retain the raw NPZ rejection."""
    from rankprobe.io import read_predictions

    export_full_sort = _load_full_sort_exporter()
    input_root = out / "full-sort-inputs"
    input_directory = input_root / "synthetic"
    input_root.mkdir(exist_ok=False)
    input_directory.mkdir(exist_ok=False)
    source_records = {
        "train": [(7, 1, 1)],
        "dev": [(7, 4, 2), (8, 6, 2)],
        # Deliberately reversed: the actual reader sorts these contexts by time.
        "test": [(7, 5, 4), (7, 3, 3)],
    }
    source_paths = []
    for split, records in source_records.items():
        path = input_directory / f"{split}.csv"
        with path.open("x", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle, lineterminator="\n")
            writer.writerow(("user_id", "item_id", "time"))
            writer.writerows(records)
        source_paths.append(path)
    input_hashes = {path.name: digest(path) for path in source_paths}
    # BaseReader was normally imported and its origin/hash verified together
    # with BaseModel. Only the three new original synthetic CSVs are read.
    BaseReader = sys.modules["helpers.BaseReader"].BaseReader
    corpus = BaseReader(SimpleNamespace(path=str(input_root), dataset="synthetic", sep=","))
    require(corpus.n_items == 7 and corpus.n_users == 9,
            "full-sort reader: synthetic catalog dimensions differ")
    require(corpus.train_clicked_set[7] == {1}
            and corpus.residual_clicked_set[7] == {3, 4, 5},
            "full-sort reader: train/residual clicked sets differ")
    require(corpus.data_df["test"]["item_id"].tolist() == [3, 5],
            "full-sort reader: actual context time sorting differs")
    train_clicked_snapshot = {user: set(items) for user, items in corpus.train_clicked_set.items()}
    residual_clicked_snapshot = {user: set(items) for user, items in corpus.residual_clicked_set.items()}
    model_args = _model_arguments(GeneralModel, torch, test_all=1, num_neg=1)

    class Model(GeneralModel):
        def __init__(self):
            super().__init__(model_args, corpus)
            self.register_buffer("score_table", torch.tensor(
                [0, 9, .5, .9, .8, .75, .25], dtype=torch.float64,
            ))

        def forward(self, feed_dict):
            return {"prediction": self.score_table[feed_dict["item_id"]].clone()}

    model = Model()
    model_before = model.score_table.clone()
    original_training, original_test_all = model.training, model.test_all
    dataset = GeneralModel.Dataset(model, corpus, "test")
    dataset.prepare()
    cached_feeds = _cache_snapshot(dataset, np)
    parser = BaseRunner.parse_runner_args(argparse.ArgumentParser())
    args = parser.parse_args([])
    args.train, args.log_file = 0, "synthetic-full-sort.log"
    args.eval_batch_size, args.num_workers, args.pin_memory = 1, 0, 0
    runner = BaseRunner(args)
    try:
        candidate_matrix = np.stack([dataset[index]["item_id"] for index in range(len(dataset))])
        candidate_snapshot = candidate_matrix.copy()
        targets = np.array(dataset.data["item_id"], copy=True)
        users = np.array(dataset.data["user_id"], copy=True)
        require(np.array_equal(candidate_matrix, [
            [3, 1, 2, 3, 4, 5, 6], [5, 1, 2, 3, 4, 5, 6],
        ]), "full-sort Dataset: positive/catalog column layout differs")
        predictions = runner.predict(dataset)
        prediction_snapshot = predictions.copy()
        expected_mask = np.zeros((2, 7), dtype=bool)
        expected_mask[:, [1, 3, 4, 5]] = True
        require(predictions.shape == (2, 7)
                and np.array_equal(np.isneginf(predictions), expected_mask),
                "full-sort prediction: train/residual catalog masking differs")
        require(np.array_equal(candidate_matrix[:, 0], targets)
                and np.all(candidate_matrix[:, 0] > 0)
                and np.isfinite(predictions[:, 0]).all(),
                "full-sort prediction: column zero must retain the observed positive, not padding")
        require(np.isfinite(predictions[~expected_mask]).all()
                and np.array_equal(predictions[~expected_mask],
                                   model_before.numpy()[candidate_matrix][~expected_mask]),
                "full-sort prediction: original eligible scores changed")
        require(all(candidate_matrix[index, int(target)] == target
                    and np.isneginf(predictions[index, int(target)])
                    for index, target in enumerate(targets)),
                "full-sort prediction: catalog duplicate of the current target was not masked")
        native = BaseRunner.evaluate_method(predictions, [1], ["HR", "NDCG"])
        require(native["HR@1"] == 1.0 and native["NDCG@1"] == 1.0,
                "full-sort evaluation: masked target duplicate changed native positive rank")

        archive = out / "unsupported-full-sort.npz"
        with archive.open("xb") as handle:
            np.savez(handle, scores=predictions, item_id=candidate_matrix, user_id=users)
        archive_hash = digest(archive)
        destination = out / "rejected-full-sort.csv"
        try:
            export_npz(archive, destination, positive_index=0, other_candidates="unknown")
        except ValueError as exc:
            require("finite" in str(exc), "full-sort export: unexpected rejection reason")
        else:
            raise GateError("full-sort export: unsupported raw masked matrix unexpectedly accepted")
        require(not destination.exists() and not destination.with_suffix(".csv.metadata.json").exists(),
                "full-sort export: rejected input created export output")
        query_ids = ["event-0003", "event-0005"]
        query_ids_snapshot = list(query_ids)
        exported_directory = out / "full-sort-export"
        exclusions = export_full_sort(predictions, dataset, query_ids, exported_directory)
        exported_csv = exported_directory / "predictions.csv"
        require(exclusions["exported_rows"] == 6 and exclusions["observed_positive_rows"] == 2
                and exclusions["unknown_rows"] == 4 and exclusions["excluded_rows"] == 8,
                "full-sort safe export: positive/unknown/exclusion counts differ")
        require(exclusions["exclusions_by_reason"] == {
            "train_clicked": 2, "residual_clicked": 6, "own_target_catalog_duplicate": 2,
        }, "full-sort safe export: overlapping exclusion reason counts differ")
        require(exclusions["qrels_complete"] is False
                and exclusions["declared_positive_column"] == 0
                and exclusions["other_candidates"] == "unknown"
                and exclusions["predictions_sha256"] == digest(exported_csv),
                "full-sort safe export: positive/unknown contract or prediction hash differs")
        require([query["query_id"] for query in exclusions["queries"]] == query_ids,
                "full-sort safe export: caller-declared event IDs changed")
        for index, query in enumerate(exclusions["queries"]):
            require(query["observed_target_item_id"] == str(targets[index])
                    and query["row_index"] == index and query["exported_rows"] == 3,
                    "full-sort safe export: observed target or event row metadata differs")
            expected_exclusions = {}
            for column in (1, 3, 4, 5):
                reasons = ["train_clicked"] if column == 1 else ["residual_clicked"]
                if column == int(targets[index]):
                    reasons.append("own_target_catalog_duplicate")
                expected_exclusions[column] = (str(column), set(reasons))
            require({entry["column_index"]: (entry["item_id"], set(entry["reasons"]))
                     for entry in query["exclusions"]} == expected_exclusions,
                    "full-sort safe export: excluded columns, item IDs or reasons differ")
        require(json.loads((exported_directory / "exclusions.json").read_text(encoding="utf-8"))
                == exclusions, "full-sort safe export: written exclusion metadata differs")
        expected_rows = [
            ("event-0003", "3", float(predictions[0, 0]), 1.0),
            ("event-0003", "2", .5, None), ("event-0003", "6", .25, None),
            ("event-0005", "5", float(predictions[1, 0]), 1.0),
            ("event-0005", "2", .5, None), ("event-0005", "6", .25, None),
        ]
        require([(row.query_id, row.item_id, row.score, row.relevance)
                 for row in read_predictions(exported_csv)] == expected_rows,
                "full-sort safe export: original IDs/scores/positive and unknown labels changed")
        rejected_eligible = []
        for name, value in (("nan", float("nan")), ("positive-infinity", float("inf")),
                            ("unexpected-negative-infinity", float("-inf"))):
            invalid_scores = predictions.copy()
            invalid_scores[0, 2] = value
            rejected_directory = out / f"rejected-full-sort-{name}"
            try:
                export_full_sort(invalid_scores, dataset, query_ids, rejected_directory)
            except ValueError:
                require(not rejected_directory.exists(),
                        "full-sort invalid eligible score: output was created before rejection")
                rejected_eligible.append(name)
            else:
                raise GateError("full-sort invalid eligible score: non-finite candidate was silently removed")
        safe_input_hashes = {path.name: digest(path) for path in (
            exported_csv, exported_directory / "exclusions.json",
        )}
        safe_report = run_audit(exported_directory, exported_csv, name="full-sort")
        require(safe_report["report_type"] == "audit" and safe_report["run_name"] == "full-sort",
                "full-sort audit: report type or name differs")
        require(safe_report["summary"]["rows"] == 6
                and safe_report["summary"]["queries"] == 2
                and safe_report["summary"]["unknown_candidates"] == 4,
                "full-sort audit: event/candidate/unknown counts differ")
        require(safe_report["protocol"]["unjudged"] == "unknown"
                and safe_report["protocol"]["qrels_complete"] is False,
                "full-sort audit: unknown/completeness policy changed")
        require(safe_report["metrics"]["mrr@1"]["value"] == 1.0
                and safe_report["metrics"]["mrr@1"]["eligible_query_ids"] == query_ids,
                "full-sort audit: finite observed positives or event IDs were lost")
        require(safe_report["metrics"]["mrr@2"]["value"] == 1.0
                and safe_report["metrics"]["mrr@2"]["eligible_query_ids"] == query_ids
                and safe_report["summary"]["assumed_nonrelevant_candidates"] == 0
                and safe_report["metrics"]["ndcg@1"]["value"] is None
                and safe_report["metrics"]["recall@1"]["value"] is None,
                "full-sort audit: known-prefix MRR or unknown catalog scope differs")
        safe_sources = safe_report["provenance"]["sources"]
        require(len(safe_sources) == 1 and safe_sources[0]["filename"] == exported_csv.name
                and safe_sources[0]["sha256"] == safe_input_hashes[exported_csv.name],
                "full-sort audit: safe prediction provenance hash differs")
        require({path.name: digest(path) for path in (
            exported_csv, exported_directory / "exclusions.json",
        )} == safe_input_hashes, "full-sort audit: safe export files changed")
        require(digest(archive) == archive_hash
                and np.array_equal(predictions, prediction_snapshot)
                and np.array_equal(candidate_matrix, candidate_snapshot)
                and torch.equal(model.score_table, model_before),
                "full-sort barrier: source scores, candidates or model changed")
        require(np.array_equal(np.stack([dataset[index]["item_id"]
                                        for index in range(len(dataset))]), candidate_snapshot)
                and np.array_equal(dataset.data["user_id"], users)
                and np.array_equal(dataset.data["item_id"], targets),
                "full-sort barrier: original context rows or candidates changed")
        require({path.name: digest(path) for path in source_paths} == input_hashes,
                "full-sort barrier: original synthetic input CSVs changed")
        require(corpus.train_clicked_set == train_clicked_snapshot
                and corpus.residual_clicked_set == residual_clicked_snapshot
                and query_ids == query_ids_snapshot
                and _cache_unchanged(dataset, cached_feeds, np),
                "full-sort workflow: clicked sets or caller-declared event IDs changed")
        observations = {
            "scope": "pinned native GeneralModel.Dataset full-sort mask-aware export",
            "prediction_contexts": 2, "candidates_per_context": 7,
            "column_zero_role": "observed positive target, not padding",
            "positive_first_columns_retained": 2, "masked_catalog_positions": 8,
            "masked_current_target_catalog_duplicates": 2,
            "train_clicked_items": [1], "residual_clicked_items": [3, 4, 5],
            "residual_source_splits": ["dev", "test"],
            "native_hr_at_1": float(native["HR@1"]),
            "raw_npz_export_status": "rejected before CSV or metadata creation",
            "raw_npz_sha256": archive_hash, "synthetic_source_csv_sha256": input_hashes,
            "safe_export_rows": 6, "safe_export_positive_rows": 2, "safe_export_unknown_rows": 4,
            "safe_export_excluded_rows": 8,
            "safe_export_exclusions_by_reason": exclusions["exclusions_by_reason"],
            "safe_export_query_ids": query_ids,
            "safe_export_input_sha256": safe_input_hashes,
            "safe_export_rejected_eligible_nonfinite_scores": rejected_eligible,
            "safe_export_mrr_at_1": 1.0,
            "safe_export_ndcg_at_1": None, "safe_export_recall_at_1": None,
            "official_test_all_argument": model_args.test_all,
            "official_default_buffer": model_args.buffer,
            "prepared_native_cached_feed_rows": len(cached_feeds),
        }
    finally:
        model.test_all = original_test_all
        model.train(original_training)
    require(model.test_all == original_test_all and model.training == original_training
            and torch.equal(model.score_table, model_before),
            "full-sort barrier: fresh fixture model state was not restored")
    return observations


def _check_stale_prepared_cache(out: Path, np, torch, BaseRunner, GeneralModel) -> dict:
    """Observe caller mutation of a prepared sampled protocol, then reject it."""
    input_root = out / "stale-cache-inputs"
    input_directory = input_root / "synthetic"
    input_root.mkdir(exist_ok=False)
    input_directory.mkdir(exist_ok=False)
    records = {
        "train": [(7, 1, 1)],
        "dev": [(7, 4, 2), (8, 6, 2)],
        "test": [(7, 5, 4, "[6,2,1,4,3]"), (7, 3, 3, "[6,2,1,4,5]")],
    }
    source_paths = []
    for split, rows in records.items():
        path = input_directory / f"{split}.csv"
        with path.open("x", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle, lineterminator="\n")
            writer.writerow(("user_id", "item_id", "time", "neg_items")
                            if split == "test" else ("user_id", "item_id", "time"))
            writer.writerows(rows)
        source_paths.append(path)
    input_hashes = {path.name: digest(path) for path in source_paths}
    BaseReader = sys.modules["helpers.BaseReader"].BaseReader
    corpus = BaseReader(SimpleNamespace(path=str(input_root), dataset="synthetic", sep=","))
    args = _model_arguments(GeneralModel, torch, test_all=0, num_neg=5)

    class Model(GeneralModel):
        def __init__(self):
            super().__init__(args, corpus)
            self.register_buffer("score_table", torch.tensor(
                [0, 9, .5, .9, .8, .75, .25], dtype=torch.float64,
            ))

        def forward(self, feed_dict):
            return {"prediction": self.score_table[feed_dict["item_id"]].clone()}

    model = Model()
    original_training, original_test_all, original_buffer = model.training, model.test_all, model.buffer
    score_table_before = model.score_table.clone()
    dataset = GeneralModel.Dataset(model, corpus, "test")
    dataset.prepare()
    cached_feeds = _cache_snapshot(dataset, np)
    original_cache = deepcopy(dataset.buffer_dict)
    original_data = deepcopy(dataset.data)
    train_clicked = deepcopy(corpus.train_clicked_set)
    residual_clicked = deepcopy(corpus.residual_clicked_set)
    parser = BaseRunner.parse_runner_args(argparse.ArgumentParser())
    runner_args = parser.parse_args([])
    runner_args.train, runner_args.log_file = 0, "synthetic-stale-cache.log"
    runner_args.eval_batch_size, runner_args.num_workers, runner_args.pin_memory = 1, 0, 0
    runner = BaseRunner(runner_args)
    export_full_sort = _load_full_sort_exporter()
    try:
        cached_candidates = np.stack([dataset[index]["item_id"] for index in range(len(dataset))])
        require(np.array_equal(cached_candidates, [
            [3, 6, 2, 1, 4, 5], [5, 6, 2, 1, 4, 3],
        ]), "stale cache: original sampled feed candidates differ")
        require(original_buffer == 1 and original_test_all == 0,
                "stale cache: fixture did not use official parser defaults")
        # This deliberately mutates the protocol after native prepare(). A new
        # Dataset or another prepare() is needed before using the new protocol.
        model.test_all = 1
        require(np.array_equal(np.stack([dataset[index]["item_id"]
                                        for index in range(len(dataset))]), cached_candidates)
                and len(dataset._get_feed_dict(0)["item_id"]) == corpus.n_items,
                "stale cache: cached sampled feeds did not differ from fresh full-sort feeds")
        predictions = runner.predict(dataset)
        prediction_snapshot = predictions.copy()
        expected = np.array([
            [.9, -np.inf, .5, -np.inf, -np.inf, -np.inf],
            [.75, -np.inf, .5, -np.inf, -np.inf, -np.inf],
        ])
        require(predictions.shape == (2, 6) and corpus.n_items == 7
                and np.array_equal(predictions, expected),
                "stale cache: actual runner did not use cached sampled columns with changed mask protocol")
        require(np.all(cached_candidates[:, 1] == 6)
                and np.isfinite(score_table_before[6].item())
                and np.isneginf(predictions[:, 1]).all(),
                "stale cache: cached item six was not masked by the changed column-one assumption")
        archive = out / "stale-cache-predictions.npz"
        with archive.open("xb") as handle:
            np.savez(handle, scores=predictions, item_id=cached_candidates,
                     user_id=np.array(dataset.data["user_id"]))
        archive_hash = digest(archive)
        rejected = out / "rejected-stale-cache-export"
        try:
            export_full_sort(predictions, dataset, ["event-0003", "event-0005"], rejected)
        except ValueError as exc:
            require("shape" in str(exc), "stale cache: unexpected exporter rejection reason")
        else:
            raise GateError("stale cache: incompatible cached sampled scores were accepted as full-sort")
        require(not rejected.exists(), "stale cache: exporter created output before rejection")
        require(digest(archive) == archive_hash
                and np.array_equal(predictions, prediction_snapshot)
                and _cache_unchanged(dataset, cached_feeds, np)
                and torch.equal(model.score_table, score_table_before),
                "stale cache: prediction source, cached fields or model scores changed")
        require(all(np.array_equal(np.asarray(dataset.data[field]), np.asarray(values))
                    for field, values in original_data.items())
                and corpus.train_clicked_set == train_clicked
                and corpus.residual_clicked_set == residual_clicked,
                "stale cache: original dataset rows or clicked sets changed")
        observations = {
            "scope": "deliberate caller protocol mutation after native prepare; not a normal default failure",
            "official_default_buffer": args.buffer,
            "prepared_test_all": original_test_all, "changed_test_all": 1,
            "cached_candidate_ids": cached_candidates.tolist(),
            "actual_prediction_shape": list(predictions.shape),
            "required_full_sort_columns": int(corpus.n_items),
            "finite_item_six_at_cached_column_one_was_masked": True,
            "export_status": "shape rejected before output directory creation",
            "source_npz_sha256": archive_hash, "synthetic_source_csv_sha256": input_hashes,
        }
    finally:
        model.test_all, model.buffer = original_test_all, original_buffer
        model.train(original_training)
        with torch.no_grad():
            model.score_table.copy_(score_table_before)
        dataset.data, dataset.buffer_dict = deepcopy(original_data), deepcopy(original_cache)
    require(model.test_all == original_test_all and model.buffer == original_buffer
            and model.training == original_training
            and torch.equal(model.score_table, score_table_before)
            and _cache_unchanged(dataset, cached_feeds, np),
            "stale cache: fresh model flags, score table or cache were not restored")
    require({path.name: digest(path) for path in source_paths} == input_hashes,
            "stale cache: original synthetic CSVs changed")
    try:
        json.dumps(observations, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise GateError("stale cache: observations must be finite JSON values") from exc
    return observations


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
    cached_feeds = _cache_snapshot(dataset, np)
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

    full_sort_workflow = _check_full_sort_workflow(
        out, np, torch, BaseRunner, GeneralModel, export_npz,
    )
    stale_cache = _check_stale_prepared_cache(out, np, torch, BaseRunner, GeneralModel)
    sampled_duplicates = _check_sampled_duplicate_workflow(
        out, np, pd, torch, BaseRunner, GeneralModel, export_npz,
    )
    inputs = (archive, exported_csv, metadata_path, out / "unsupported-full-sort.npz",
              out / "full-sort-export" / "predictions.csv",
              out / "full-sort-export" / "exclusions.json",
              *sorted((out / "full-sort-inputs" / "synthetic").glob("*.csv")),
              out / "stale-cache-predictions.npz",
              *sorted((out / "stale-cache-inputs" / "synthetic").glob("*.csv")))
    inputs += tuple(out / "sampled-duplicates" / name
                    for name in sampled_duplicates["source_files_sha256"])
    hashes_before = {str(path.relative_to(out)): digest(path) for path in inputs}
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
            and report["metrics"]["mrr@2"]["value"] == 1.0
            and report["metrics"]["mrr@2"]["eligible_query_ids"] == ["query_000001"]
            and report["metrics"]["mrr@2"]["excluded_query_ids"] == ["query_000002"]
            and report["summary"]["assumed_nonrelevant_candidates"] == 0,
            "audit: known-prefix MRR or unknown-first exclusion differs")
    require(report["metrics"]["ndcg@1"]["value"] is None
            and report["metrics"]["recall@1"]["value"] is None,
            "audit: unsupported NDCG or Recall was invented")
    require("score_ties" in {finding["code"] for finding in report["findings"]},
            "audit: actual tied scores were not reported")
    sources = report["provenance"]["sources"]
    require(len(sources) == 1 and sources[0]["filename"] == exported_csv.name
            and sources[0]["sha256"] == hashes_before[exported_csv.name],
            "audit: input provenance hash differs")
    require({str(path.relative_to(out)): digest(path) for path in inputs} == hashes_before
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
    require(model.buffer == 1 and _cache_unchanged(dataset, cached_feeds, np),
            "integration: official default buffered sampled feeds changed")
    require({name: digest(source / "src" / (name.replace(".", "/") + ".py"))
             for name in source_hashes} == source_hashes,
            "integration: pinned upstream source files changed")

    result = {
        "status": "passed", "python": platform.python_version(), "platform": sys.platform,
        "versions": versions, "rechorus_commit": SOURCE_COMMIT,
        "rechorus_source_sha256": source_hashes, "synthetic_input_sha256": hashes_before,
        "observations": {
            "prediction_contexts": 2, "distinct_source_users": 1,
            "candidates_per_context": 102, "exported_rows": 204,
            "unknown_candidates": 202, "declared_positive_column": 0,
            "full_sort_workflow": full_sort_workflow,
            "official_default_buffer": model.buffer,
            "prepared_sampled_cached_feed_rows": len(cached_feeds),
            "stale_prepared_cache": stale_cache,
            "sampled_duplicate_workflow": sampled_duplicates,
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
            "actual_full_sort_reader_dataset_and_runner_called": True,
            "full_sort_clicked_catalog_and_own_target_duplicate_masks_observed": True,
            "full_sort_column_zero_is_positive_not_recbole_padding": True,
            "unsupported_raw_full_sort_export_rejected_without_output": True,
            "full_sort_synthetic_inputs_and_fresh_model_state_preserved": True,
            "full_sort_exact_native_layout_safely_exported": True,
            "full_sort_explicit_event_and_native_item_ids_preserved": True,
            "full_sort_known_mask_exclusions_have_overlapping_reasons": True,
            "full_sort_eligible_nonfinite_scores_rejected_without_output": True,
            "full_sort_actual_cli_preserves_unknown_labels_and_positive_rows": True,
            "actual_upstream_default_buffer_one_prepare_path_exercised": True,
            "sampled_and_full_sort_native_cached_feed_rows_preserved": True,
            "actual_stale_cache_after_test_all_protocol_change_observed": True,
            "stale_cache_full_sort_export_rejected_before_output": True,
            "stale_cache_inputs_and_fresh_model_state_restored": True,
            "actual_sampled_duplicate_dataset_and_runner_called": True,
            "sampled_duplicate_ids_scores_and_unknowns_preserved": True,
            "sampled_duplicate_native_column_rank_differs_from_unique_item_oracle": True,
            "sampled_duplicate_fixture_inputs_cache_and_model_state_preserved": True,
        },
        "limitations": [
            "Original synthetic fixtures only; no benchmark data was loaded or used.",
            "Actual GeneralModel Dataset and BaseRunner are used; no trained recommendation model is evaluated.",
            "Positive column zero is a checked fixture convention and a caller assertion for other inputs.",
            "The sampled NPZ example uses export-local row/item pseudonyms; full-sort event/item IDs are preserved with caller-owned alignment.",
            "The separate tie oracle supplies explicit synthetic zeros; the default exported run preserves unknown labels.",
            "The duplicate boundary uses supplied original synthetic negatives, not an executed public sampler; its separate planted-label oracle does not fill the normal export's unknown judgments.",
            "Full-sort export covers only the pinned native GeneralModel.Dataset layout and declared event row alignment; arbitrary overridden full-sort models are unsupported.",
            "Residual clicked sets include validation/test interactions; this is an upstream candidate policy, not causal history or a leakage certificate.",
            "The stale-cache counterexample deliberately changes test_all after prepare without rebuilding; it is a mutable caller workflow risk, not evidence that the normal default is broken.",
            "No sequential, CTR, reranking, universal metric parity, adoption or human time saved is established.",
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
