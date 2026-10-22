"""Exercise a real RecBole evaluation loader and scoring/export handoff.

Original tiny split files construct the official dataset, samplers and loader.
Scores come from a deterministic untrained provider; no dataset is downloaded.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib
import importlib.metadata as metadata
import importlib.util
import json
import os
from pathlib import Path
import platform
import subprocess
import sys


SOURCE_SHA256 = {
    "recbole.utils.case_study": "a3690b50c6aee1570632c43db7ba02f5b9307f9e14585960d0815f62e44c0f68",
    "recbole.data.interaction": "4a72fbdb14b7be157336ee0c93f1b9596feb2f4065736cde2b15cf10e35ef801",
    "recbole.config.configurator": "fa9bc256b8bed0c364ab5a9939465f905695d194cdf1c195beb195b47f392618",
    "recbole.data.utils": "df3d4c9bd47be8490303df5e228cdfa4ccc3a08dac6efd6804a017fd677ba7de",
    "recbole.data.dataset.dataset": "0e8c17f6e33d3a8dc775121d7523af18264f385357f5c3fd571e70f0b560a6dd",
    "recbole.data.dataloader.general_dataloader": "961853fb35415f54d5f5f015773260dab7225ee6339454de89c9b52d2ec82321",
    "recbole.data.dataloader.abstract_dataloader": "4d91db0e3555b47afa2ddba4938fa1f9203d14e58b04937259447203376a1a70",
    "recbole.sampler.sampler": "8b165ae70393e8cc75aa81de7b2863b96822828206ebd7b468fdb1a741f197a0",
}


class GateError(ValueError):
    """A named integration check failed without exposing local paths."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise GateError(message)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def new_output_directory(out: Path) -> Path:
    """Reject unsafe output before optional dependencies are imported."""
    out = Path(out).absolute()
    require(not out.exists() and not out.is_symlink(), "output: directory must be new")
    require(not any(parent.is_symlink() for parent in out.parents),
            "output: symbolic-link ancestors are not allowed")
    require(out.parent.is_dir(), "output: parent directory must already exist")
    return out


def write_csv(path: Path, fields: list[str], records: list[tuple]) -> None:
    require(not path.exists() and not path.is_symlink(), "output: file must be new")
    with path.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(fields)
        writer.writerows(records)


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


def _read_cli_report(process: subprocess.CompletedProcess, report_directory: Path) -> dict:
    require(process.returncode == 0, "RankProbe CLI: nonzero exit status")
    html = report_directory / "report.html"
    require(html.is_file() and html.stat().st_size > 0, "RankProbe CLI: HTML missing or empty")
    try:
        return json.loads((report_directory / "report.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise GateError("RankProbe CLI: JSON missing or invalid") from exc


def run_comparison(out: Path, expected: Path, exported: Path, qrels: Path) -> dict:
    report_directory = new_output_directory(out / "report")
    process = _run_cli(out, [
        "compare", "--run", f"expected={expected}", "--run", f"exported={exported}",
        "--qrels", str(qrels), "--cutoffs", "1,2", "--fail-on", "never",
        "--out", str(report_directory),
    ])
    return _read_cli_report(process, report_directory)


def select_requested_users(evaluation_uids: list[int], requested: list[int]) -> list[int]:
    """Check the declared requested population; never silently intersect it."""
    require(bool(requested), "population: requested user list is empty")
    require(len(set(requested)) == len(requested), "population: duplicate requested users")
    require(all(uid in evaluation_uids for uid in requested),
            "population: requested users are absent from this evaluation loader")
    return list(requested)


def _write_loader_inputs(out: Path) -> list[Path]:
    folder = out / "loader-inputs" / "rankprobe_original"
    folder.mkdir(parents=True, exist_ok=False)
    splits = {
        "train": [("learner,甲", "history one"), ("reader B", "paper,α"),
                  ("dataset only", "paper β"), ("reader B", "unjudged"),
                  ("reader B", "negative")],
        "valid": [("dataset only", "paper,α")],
        "test": [("learner,甲", "paper,α"), ("reader B", "paper β")],
    }
    paths = []
    for split, rows in splits.items():
        path = folder / f"rankprobe_original.{split}.inter"
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write("user_id:token\titem_id:token\n")
            handle.writelines(f"{user}\t{item}\n" for user, item in rows)
        paths.append(path)
    return paths


def _fixtures(np, torch, out: Path):
    from recbole.config import Config
    from recbole.data.dataloader import FullSortEvalDataLoader
    from recbole.data.utils import create_dataset, data_preparation

    inputs = _write_loader_inputs(out)
    originals = {str(path.relative_to(out)): digest(path) for path in inputs}
    cache_paths = [out / "unused-dataset.pth", out / "unused-loaders.pth"]
    require(not any(path.exists() for path in cache_paths), "loader: cache paths must be absent")
    config = Config(model="BPR", dataset="rankprobe_original", config_dict={
        "data_path": str(out / "loader-inputs"),
        "benchmark_filename": ["train", "valid", "test"],
        "load_col": {"inter": ["user_id", "item_id"]},
        "gpu_id": "", "use_gpu": False, "worker": 0,
        "train_batch_size": 4, "eval_batch_size": 12,
        "eval_args": {"split": {"RS": [0.8, 0.1, 0.1]}, "group_by": "user",
                      "order": "RO", "mode": "full"},
        "save_dataset": False, "save_dataloaders": False,
        "dataset_save_path": str(cache_paths[0]),
        "dataloaders_save_path": str(cache_paths[1]),
        "checkpoint_dir": str(out / "unused-checkpoints"),
        "show_progress": False,
    })
    dataset = create_dataset(config)
    train_data, valid_data, test_data = data_preparation(config, dataset)
    require(isinstance(test_data, FullSortEvalDataLoader), "loader: official full-sort loader required")
    require(not test_data.is_sequential, "loader: expected nonsequential evaluation")
    users = dataset.id2token(dataset.uid_field, np.arange(dataset.user_num))
    items = dataset.id2token(dataset.iid_field, np.arange(dataset.item_num))
    require(users.tolist() == ["[PAD]", "learner,甲", "reader B", "dataset only"],
            "loader: original user token mapping differs")
    require(items.tolist() == ["[PAD]", "history one", "paper,α", "paper β", "unjudged", "negative"],
            "loader: original item token mapping differs")
    evaluation_uids = test_data.uid_list.detach().cpu().tolist()
    require(evaluation_uids == [1, 2] and dataset.user_num == 4,
            "loader: dataset and evaluation user populations differ from original case")
    validation_uids = valid_data.uid_list.detach().cpu().tolist()
    require(validation_uids == [3], "loader: validation population differs from original case")
    require(test_data.uid2history_item[3] is None and test_data.uid2positive_item[3] is None,
            "loader: absent user's history and positives should be absent")
    require([len(part.dataset) for part in (train_data, valid_data, test_data)] == [5, 1, 2],
            "loader: explicit benchmark split sizes changed")
    batch, history_index, positive_u, positive_i = next(iter(test_data))
    batch_uids = batch[dataset.uid_field].tolist()
    observed_history = {(batch_uids[row], item) for row, item in
                        zip(history_index[0].tolist(), history_index[1].tolist())}
    require(observed_history == {(1, 1), (2, 2), (2, 4), (2, 5)},
            "loader: actual batch history masks differ")
    positives = {(batch_uids[row], item) for row, item in
                 zip(positive_u.tolist(), positive_i.tolist())}
    require(positives == {(1, 2), (2, 3)}, "loader: actual batch test positives differ")
    selected_prefix = evaluation_uids[:2]
    requested = list(reversed(selected_prefix))
    uids = select_requested_users(evaluation_uids, requested)
    try:
        select_requested_users(evaluation_uids, [3, selected_prefix[0]])
    except GateError:
        missing_request_rejected = True
    else:
        raise GateError("population: absent request was silently accepted")
    require(not any(path.exists() for path in cache_paths), "loader: unexpected cache serialization")
    require({str(path.relative_to(out)): digest(path) for path in inputs} == originals,
            "loader: original split inputs changed")
    population = {"dataset_nonpadding_uids": [1, 2, 3], "evaluation_uids": evaluation_uids,
                  "validation_uids": validation_uids,
                  "documented_first_two_uids": selected_prefix, "requested_scoring_uids": requested,
                  "absent_requested_uids": [3], "absent_request_rejected": missing_request_rejected,
                  "actual_batch_uids": batch_uids, "test_positive_pairs": sorted(positives),
                  "history_pairs": sorted(observed_history), "split_interactions": [5, 1, 2],
                  "cache_files_absent": True}

    class Model(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.register_buffer("table", torch.tensor([
                [0, 0, 0, 0, 0, 0],
                [9, 8, .75, .625, .5, .25],
                [9, .75, 8, .625, 7, 6],
                [0, 0, 0, 0, 0, 0],
            ], dtype=torch.float64))

        def full_sort_predict(self, interaction):
            # The actual helper masks its returned tensor in place. A fresh
            # prediction keeps this fixture's original finite score table intact.
            return self.table[interaction[dataset.uid_field]].clone()

    return uids, Model(), test_data, users, items, inputs, originals, population


def _load_exporter():
    spec = importlib.util.spec_from_file_location(
        "rankprobe_recbole_exporter", Path(__file__).with_name("export_recbole.py")
    )
    require(spec is not None and spec.loader is not None, "exporter: source missing")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.export_full_sort


def check_workflow(out: Path) -> dict:
    out = new_output_directory(out)
    try:
        import numpy as np
        import torch
        from recbole.data import interaction
        from recbole.utils import case_study
        from rankprobe.io import InputError, read_predictions, read_qrels
    except ImportError as exc:
        raise GateError("imports: install optional RecBole helper dependencies and RankProbe first") from exc
    try:
        versions = {name: metadata.version(name) for name in (
            "recbole", "torch", "numpy", "pandas", "tensorboard", "texttable",
            "colorlog", "colorama", "rankprobe", "PyYAML", "scipy", "scikit-learn", "tqdm",
        )}
    except metadata.PackageNotFoundError as exc:
        raise GateError("versions: an integration dependency has no distribution metadata") from exc
    sources = {}
    for name in SOURCE_SHA256:
        try:
            module = importlib.import_module(name)
        except ImportError as exc:
            raise GateError("imports: optional RecBole loader dependencies are unavailable") from exc
        source = Path(module.__file__)
        require(source.suffix == ".py" and source.is_file(), "sources: Python source missing")
        sources[name] = digest(source)
    require(sources == SOURCE_SHA256, "sources: installed RecBole helper differs from pinned source")
    export_full_sort = _load_exporter()

    out.mkdir(exist_ok=False)
    uid_series, model, test_data, users, items, loader_inputs, loader_hashes, population = _fixtures(np, torch, out)
    uid_snapshot = list(uid_series)
    model_snapshot = model.table.clone()
    history_snapshot = [None if history is None else history.clone()
                        for history in test_data.uid2history_item]
    scores = case_study.full_sort_scores(uid_series, model, test_data)
    scores_snapshot = scores.clone()
    expected_scores = np.array([
        [-np.inf, .75, -np.inf, .625, -np.inf, -np.inf],
        [-np.inf, -np.inf, .75, .625, .5, .25],
    ])
    require(np.array_equal(scores.cpu().numpy(), expected_scores),
            "RecBole helper: padding/history masking or user order differs")
    require(isinstance(interaction.Interaction({"user_id": torch.tensor(uid_series)}),
                       interaction.Interaction), "RecBole Interaction: actual object unavailable")
    top_scores, top_ids = case_study.full_sort_topk(uid_series, model, test_data, k=4)
    masked_topk = torch.isneginf(top_scores)
    require(masked_topk.sum().item() == 2 and masked_topk[0].sum().item() == 2,
            "RecBole topk: expected over-requested masked candidates were not returned")
    require(set(top_ids[0][masked_topk[0]].tolist()) <= {0, 2, 4, 5},
            "RecBole topk: unexpected non-finite candidate")
    require(torch.equal(model.table, model_snapshot), "fixture: original model score table changed")

    unsafe_csv = out / "naive-full-sort.csv"
    write_csv(unsafe_csv, ["query_id", "item_id", "score"], [
        (users[uid], items[item], float(scores[row, item]))
        for row, uid in enumerate(uid_series) for item in range(test_data.dataset.item_num)
    ])
    try:
        read_predictions(unsafe_csv)
    except InputError as exc:
        require("finite" in str(exc), "naive export: unexpected parser rejection")
    else:
        raise GateError("naive export: masked non-finite scores unexpectedly accepted")
    unsafe_report = new_output_directory(out / "naive-report")
    unsafe_process = _run_cli(out, [
        "audit", str(unsafe_csv), "--fail-on", "never", "--out", str(unsafe_report),
    ])
    require(unsafe_process.returncode == 2 and "finite" in unsafe_process.stderr,
            "naive export: actual CLI did not reject masked scores")
    require(not unsafe_report.exists(), "naive export: failed CLI created a report")

    exported_directory = out / "safe-export"
    exclusions = export_full_sort(scores, uid_series, test_data, exported_directory)
    exported_csv = exported_directory / "predictions.csv"
    require(exclusions["exclusions_by_reason"] == {"padding": 2, "history": 4},
            "safe export: exclusion reasons differ")
    require(exclusions["exported_rows"] == 6 and exclusions["excluded_rows"] == 6,
            "safe export: candidate counts differ")
    require([query["query_id"] for query in exclusions["queries"]]
            == ["reader B", "learner,甲"], "safe export: external user alignment differs")
    for query, uid in zip(exclusions["queries"], uid_series):
        expected_excluded = {0: "padding"}
        expected_excluded.update({int(item): "history" for item in history_snapshot[uid]})
        require({entry["internal_item_id"]: entry["reason"] for entry in query["exclusions"]}
                == expected_excluded, "safe export: excluded positions or reasons differ")
        require(all(entry["item_id"] == items[entry["internal_item_id"]]
                    for entry in query["exclusions"]),
                "safe export: excluded external item alignment differs")
    require(exclusions["labels"] == "not_exported" and exclusions["qrels_complete"] is False,
            "safe export: label completeness was invented")
    require(json.loads((exported_directory / "exclusions.json").read_text(encoding="utf-8"))
            == exclusions, "safe export: written metadata differs")
    require(exclusions["predictions_sha256"] == digest(exported_csv),
            "safe export: prediction hash differs")
    expected_csv = out / "expected-eligible.csv"
    expected_rows = [
        ("reader B", "history one", .75), ("reader B", "paper β", .625),
        ("learner,甲", "paper,α", .75), ("learner,甲", "paper β", .625),
        ("learner,甲", "unjudged", .5), ("learner,甲", "negative", .25),
    ]
    write_csv(expected_csv, ["query_id", "item_id", "score"], expected_rows)
    loaded = read_predictions(exported_csv)
    require([(row.query_id, row.item_id, row.score) for row in loaded] == expected_rows,
            "safe export: original external IDs, finite scores or row alignment changed")
    require(all(row.relevance is None for row in loaded), "safe export: a relevance label was invented")
    judgments_csv = out / "judgments.csv"
    write_csv(judgments_csv, ["query_id", "item_id", "relevance"], [
        ("reader B", "history one", 0), ("reader B", "paper β", 1),
        ("learner,甲", "paper,α", 1), ("learner,甲", "paper β", 0),
        ("learner,甲", "negative", 0),
    ])
    qrels = read_qrels(judgments_csv)
    require("unjudged" not in qrels["learner,甲"], "judgments: unknown candidate was labeled")

    rejected = []
    for name, invalid in (("nan", float("nan")), ("positive-infinity", float("inf")),
                          ("unexpected-negative-infinity", float("-inf"))):
        bad_scores = scores.clone()
        bad_scores[0, 1] = invalid
        bad_output = out / f"rejected-{name}"
        try:
            export_full_sort(bad_scores, uid_series, test_data, bad_output)
        except ValueError:
            require(not bad_output.exists(), "invalid score: exporter created output before rejection")
            rejected.append(name)
        else:
            raise GateError("invalid score: eligible non-finite value was silently removed")

    inputs = (unsafe_csv, exported_csv, exported_directory / "exclusions.json",
              expected_csv, judgments_csv, *loader_inputs)
    hashes_before = {str(path.relative_to(out)): digest(path) for path in inputs}
    report = run_comparison(out, expected_csv, exported_csv, judgments_csv)
    require(report["report_type"] == "compare", "comparison: wrong report type")
    require(report["protocol"]["unjudged"] == "unknown"
            and report["protocol"]["qrels_complete"] is False,
            "comparison: unknown/completeness policy changed")
    for name in ("expected", "exported"):
        run = report["runs"][name]
        require(run["metrics"]["mrr@1"]["value"] == .5
                and run["metrics"]["mrr@2"]["value"] == .75,
                "comparison: known synthetic MRR differs")
        require(run["audit"]["summary"]["unknown_candidates"] == 1,
                "comparison: unknown candidate was lost")
        require(run["metrics"]["ndcg@1"]["excluded_query_ids"] == ["learner,甲"],
                "comparison: unknown-label NDCG query was not excluded")
        require(run["metrics"]["recall@1"]["value"] is None,
                "comparison: Recall was invented")
    matched = report["pairs"][0]["matched_pool_comparison"]
    require(matched["query_count"] == 2 and matched["status"] == "checked",
            "comparison: structurally matched candidate pools differ")
    require(matched["delta_right_minus_left"]["mrr@1"]["delta"] == 0.0,
            "comparison: safe export changed ranking")
    provenance = {source["filename"]: source for source in report["provenance"]["sources"]}
    require(set(provenance) == {expected_csv.name, exported_csv.name, judgments_csv.name},
            "comparison: provenance sources differ")
    for path in (expected_csv, exported_csv, judgments_csv):
        require(provenance[path.name]["sha256"] == digest(path),
                "comparison: input provenance hash differs")
    require({str(path.relative_to(out)): digest(path) for path in inputs} == hashes_before,
            "integration: synthetic input files changed")
    require(all(digest(out / name) == value for name, value in loader_hashes.items()),
            "loader: original split files changed after scoring/export")
    require(torch.equal(scores, scores_snapshot) and torch.equal(model.table, model_snapshot),
            "integration: original score tensors changed")
    require(uid_series == uid_snapshot and all(
        (history is None and original is None)
        or (history is not None and original is not None and torch.equal(history, original))
        for history, original in zip(test_data.uid2history_item, history_snapshot)
    ), "integration: original user IDs or history masks changed")

    result = {
        "status": "passed", "python": platform.python_version(), "platform": sys.platform,
        "versions": versions, "recbole_source_sha256": sources,
        "synthetic_input_sha256": hashes_before,
        "observations": {
            "requested_top_k": 4, "eligible_candidates_per_requested_user": [2, 4],
            "masked_candidates_returned_by_topk": 2, "exported_rows": 6,
            "exclusions_by_reason": {"padding": 2, "history": 4},
            "unknown_candidates": 1, "mrr_at_1": .5, "mrr_at_2": .75,
            "rejected_eligible_nonfinite_scores": rejected,
            "official_loader_population": population,
        },
        "checks": {
            "actual_recbole_full_sort_scores_called": True,
            "actual_recbole_full_sort_topk_called": True,
            "actual_recbole_interaction_used": True,
            "installed_sources_match_pin": True,
            "padding_and_history_masking_observed": True,
            "overrequested_topk_contains_masked_candidates": True,
            "naive_masked_csv_rejected_by_actual_cli": True,
            "only_documented_mask_positions_excluded": True,
            "external_token_and_reversed_user_alignment_preserved": True,
            "eligible_nonfinite_scores_rejected_without_output": True,
            "actual_rankprobe_cli_report": True,
            "original_finite_scores_and_ranking_preserved": True,
            "unknown_labels_preserved": True,
            "complete_qrels_not_assumed": True,
            "input_provenance_hashes_match": True,
            "original_tensors_and_synthetic_files_unchanged": True,
            "official_dataset_and_full_sort_loader_constructed": True,
            "actual_loader_batch_masks_and_positives_verified": True,
            "evaluation_user_selection_preserves_requested_order": True,
            "absent_dataset_user_rejected_without_silent_drop": True,
            "original_split_files_and_absent_cache_paths_verified": True,
        },
        "limitations": [
            "Original eight-interaction nonsequential split files only; no training or dataset download.",
            "Official Config, dataset preparation, full-sort loader and scoring helpers are used; "
            "scores come from an untrained deterministic provider, not a fitted recommender.",
            "Padding/history exclusions implement an explicit upstream policy, not a leakage certificate.",
            "No sequential/repeated-user contexts, universal metric parity, adoption or human time saved is established.",
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
