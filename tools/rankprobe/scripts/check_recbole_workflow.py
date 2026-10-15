"""Exercise actual RecBole case-study helpers on original nonsequential fixtures.

This optional integration check trains no model and downloads no dataset. Its
dataset/model objects implement only the protocol used by the upstream helper;
they do not exercise RecBole's training or dataloader construction lifecycle.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.metadata as metadata
import importlib.util
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
from types import SimpleNamespace


SOURCE_SHA256 = {
    "recbole.utils.case_study": "a3690b50c6aee1570632c43db7ba02f5b9307f9e14585960d0815f62e44c0f68",
    "recbole.data.interaction": "4a72fbdb14b7be157336ee0c93f1b9596feb2f4065736cde2b15cf10e35ef801",
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


def _fixtures(np, torch):
    """Original fixtures, not trained models or instantiated framework datasets."""
    users = np.array(["[PAD]", "learner,甲", "reader B"])
    items = np.array(["[PAD]", "history one", "paper,α", "paper β", "unjudged", "negative"])

    class Dataset:
        uid_field = "user_id"
        iid_field = "item_id"
        user_num = 3
        item_num = 6

        def join(self, interaction):
            return interaction

        def id2token(self, field, ids):
            return (users if field == self.uid_field else items)[ids]

    histories = np.empty(3, dtype=object)
    histories[0] = torch.tensor([], dtype=torch.long)
    histories[1] = torch.tensor([1], dtype=torch.long)
    histories[2] = torch.tensor([2, 4, 5], dtype=torch.long)
    test_data = SimpleNamespace(
        dataset=Dataset(), is_sequential=False, uid2history_item=histories,
    )

    class Model(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.register_buffer("table", torch.tensor([
                [0, 0, 0, 0, 0, 0],
                [9, 8, .75, .625, .5, .25],
                [9, .75, 8, .625, 7, 6],
            ], dtype=torch.float64))

        def full_sort_predict(self, interaction):
            # The actual helper masks its returned tensor in place. A fresh
            # prediction keeps this fixture's original finite score table intact.
            return self.table[interaction[Dataset.uid_field]].clone()

    return [2, 1], Model(), test_data, users, items


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
            "colorlog", "colorama", "rankprobe",
        )}
    except metadata.PackageNotFoundError as exc:
        raise GateError("versions: an integration dependency has no distribution metadata") from exc
    sources = {}
    for name, module in (("recbole.utils.case_study", case_study),
                         ("recbole.data.interaction", interaction)):
        source = Path(module.__file__)
        require(source.suffix == ".py" and source.is_file(), "sources: Python source missing")
        sources[name] = digest(source)
    require(sources == SOURCE_SHA256, "sources: installed RecBole helper differs from pinned source")
    export_full_sort = _load_exporter()

    uid_series, model, test_data, users, items = _fixtures(np, torch)
    uid_snapshot = list(uid_series)
    model_snapshot = model.table.clone()
    history_snapshot = [history.clone() for history in test_data.uid2history_item]
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

    out.mkdir(exist_ok=False)
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
              expected_csv, judgments_csv)
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
    require(torch.equal(scores, scores_snapshot) and torch.equal(model.table, model_snapshot),
            "integration: original score tensors changed")
    require(uid_series == uid_snapshot and all(
        torch.equal(history, original)
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
        },
        "limitations": [
            "Original synthetic nonsequential helper fixtures only; no model training or dataset download.",
            "Actual case-study helpers and Interaction are used; dataloader construction is not exercised.",
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
