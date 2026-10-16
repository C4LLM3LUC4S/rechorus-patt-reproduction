"""Check native MTEB capture and the documented CSV bridge on original tiny text."""

from __future__ import annotations

import argparse
import ast
from contextlib import contextmanager
from copy import deepcopy
import csv
import hashlib
import importlib
import importlib.metadata as metadata
import json
import math
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tempfile


SOURCE_SHA256 = {
    "mteb.abstasks.abstask": "062ba8dca07de93fafb85d72003d4e989e217fa9f3d412bb59effda81c1fb4c0",
    "mteb.abstasks.retrieval": "c3cfe12420c22ebd8e67e44ee00d42f3a6b33c9fea4fe7c5f49590d5f0c1258d",
    "mteb.mocks.mock_tasks.retrieval": "f86bf7ed6e332671fdea3fd459dc13860bc6355e300b8b0c3837136696d544df",
    "mteb.models.model_implementations.random_baseline": "353275b890ddf78565e7aa3b2c876e51897d5ffc86d89ff026db9fc2f730d76a",
    "mteb.models.model_meta": "1270d11e0f8009522ef2498a47e0e90181accc520e23c654ba42877089bd6e97",
    "mteb.models.search_wrappers": "c68b6c43ddebe40ace0412d83f97605e7860ea9f8553e1c984e9a516e404432b",
    "mteb._evaluators.retrieval_evaluator": "1a23a0f753b5d99bbca516a8660fbac63a2245f9feffd160398b8c9b90d82b0e",
    "mteb._evaluators.retrieval_metrics": "b1db2261db0a601a0420d561a67bc763c084b985d4aa0ea3343fa1badbdda338",
    "mteb.evaluate": "90ee8d22cf5522f4cf45484fcbe75677c9884a687bc12b54b923f496cf952699",
}


class GateError(ValueError):
    """A bounded check failure without local paths or private input."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise GateError(message)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def new_output_directory(out: Path) -> Path:
    out = Path(out).absolute()

    def linked(path):
        return path.is_symlink() or getattr(path, "is_junction", lambda: False)()
    require(not out.exists() and not linked(out), "output: directory must be new")
    require(not any(linked(p) for p in out.parents), "output: linked ancestors forbidden")
    require(out.parent.is_dir(), "output: parent directory must already exist")
    return out


def read_recipe(recipe: Path) -> str:
    try:
        blocks = re.findall(r"```python\s*\n(.*?)\n```", recipe.read_text(encoding="utf-8"), re.S)
        candidates = [block for block in blocks if any(
            isinstance(node, ast.ImportFrom) and node.module == "rankprobe.model"
            and any(alias.name == "Row" for alias in node.names)
            for node in ast.walk(ast.parse(block)))]
        require(len(candidates) == 1, "recipe: expected one Row-based CSV bridge")
        names = [node.targets[0].id for node in ast.parse(candidates[0]).body
                 if isinstance(node, ast.Assign) and len(node.targets) == 1
                 and isinstance(node.targets[0], ast.Name)]
        require(all(names.count(name) == 1 for name in
                    ("source", "destination", "subset", "split")),
                "recipe: expected four unique configuration assignments")
        return candidates[0]
    except (OSError, UnicodeError, SyntaxError) as exc:
        raise GateError("recipe: readable Python bridge required") from exc


@contextmanager
def network_guard():
    state = {"active": True, "attempts": 0}

    def audit(event, args):
        if state["active"] and event in {
            "socket.connect", "socket.getaddrinfo", "socket.gethostbyname",
            "socket.gethostbyaddr", "socket.sendto", "socket.sendmsg",
        }:
            state["attempts"] += 1
            raise GateError("network: runtime connection attempt forbidden")

    sys.addaudithook(audit)
    try:
        yield state
    finally:
        state["active"] = False


def run_core(arguments: list[str], cwd: Path, *, expected_success: bool = True) -> None:
    allowed = ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "TMPDIR", "LANG",
               "LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH", "LC_ALL", "LC_CTYPE")
    environment = {key: os.environ[key] for key in allowed if key in os.environ}
    try:
        process = subprocess.run([sys.executable, "-I", *arguments], cwd=cwd,
                                 env=environment, shell=False, capture_output=True,
                                 encoding="utf-8", errors="replace", timeout=120)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GateError("core subprocess: failed or exceeded 120 seconds") from exc
    require((process.returncode == 0) == expected_success, "core subprocess: unexpected exit status")


def check_workflow(out: Path, recipe: Path | None = None) -> dict:
    out = new_output_directory(out)
    recipe = Path(recipe) if recipe is not None else Path(__file__).resolve().parents[1] / "docs/mteb-workflow.md"
    bridge, recipe_hash = read_recipe(recipe), digest(recipe)
    require(sys.version_info >= (3, 11), "Python: native MTEB requires 3.11 or newer")
    require(not any(name.split(".")[0] in {"mteb", "huggingface_hub", "datasets", "transformers"}
                    for name in sys.modules), "imports: use a fresh standalone process")
    with tempfile.TemporaryDirectory(prefix="rankprobe-mteb-", dir=out.parent) as temporary:
        stage = Path(temporary)
        result_dir = stage / "result"
        result_dir.mkdir()
        safe_keys = ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "TMPDIR", "LANG",
                     "LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH", "LC_ALL", "LC_CTYPE")
        safe_environment = {key: os.environ[key] for key in safe_keys if key in os.environ}
        os.environ.clear()
        os.environ.update(safe_environment)
        for key in ("MTEB_CACHE", "HF_HOME", "HF_TOKEN_PATH", "HF_HUB_CACHE", "HF_ASSETS_CACHE",
                    "HF_DATASETS_CACHE", "TRANSFORMERS_CACHE"):
            os.environ[key] = str(stage / key.lower())
        for key in ("HF_HUB_OFFLINE", "HF_DATASETS_OFFLINE", "TRANSFORMERS_OFFLINE",
                    "HF_HUB_DISABLE_TELEMETRY", "DO_NOT_TRACK", "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
            os.environ[key] = "1"
        os.environ["MTEB_AUTO_INSTALL_EXTRAS"] = "0"
        os.environ["TOKENIZERS_PARALLELISM"] = "false"
        with network_guard() as network:
            try:
                import mteb
                import torch
                from datasets import Dataset
                from mteb.mocks.mock_tasks.retrieval import MockRetrievalTask
                from mteb.models.model_implementations.random_baseline import random_encoder_baseline
                from rankprobe.io import read_predictions
                versions = {name: metadata.version(name) for name in (
                    "mteb", "rankprobe", "datasets", "numpy", "requests", "scikit-learn", "scipy",
                    "sentence-transformers", "transformers", "typing-extensions", "torch", "tqdm",
                    "rich", "pytrec-eval-terrier", "pydantic", "polars")}
            except (ImportError, metadata.PackageNotFoundError) as exc:
                raise GateError("imports: install MTEB 2.26.1 full dependencies and RankProbe first") from exc
            require(versions["mteb"] == "2.26.1", "versions: MTEB 2.26.1 required")
            source_hashes = {name: digest(Path(importlib.import_module(name).__file__))
                             for name in SOURCE_SHA256}
            require(source_hashes == SOURCE_SHA256, "sources: installed MTEB differs from fixed release")
            torch.set_num_threads(1)
            labels = {"q1": {"doc_a": 1}, "q2": {"doc_z": 1}}
            task = MockRetrievalTask().filter_eval_splits(["test"])
            task.dataset = {"default": {"test": {
                "queries": Dataset.from_list([{"id": q, "text": f"Original parcel query {q}."}
                                              for q in labels]),
                "corpus": Dataset.from_list([{"id": d, "text": "An original synthetic blue parcel."}
                                             for d in ("doc_a", "doc_m", "doc_z")]),
                "relevant_docs": deepcopy(labels), "top_ranked": None,
            }}}
            task.data_loaded = True
            model = random_encoder_baseline.load_model(device="cpu")
            native = mteb.evaluate(model, tasks=[task], cache=None, prediction_folder=result_dir,
                                   co2_tracker=False, num_proc=1, encode_kwargs={"batch_size": 2},
                                   show_progress_bar=False, raise_error=True)
            require(not native.exceptions and len(native.task_results) == 1,
                    "native evaluation: one successful task required")
            require(task.dataset["default"]["test"]["relevant_docs"] == labels,
                    "native evaluation: supplied judgments changed")
        require(network["attempts"] == 0, "network: runtime connection attempted")
        predictions = result_dir / "MockRetrievalTask_predictions.json"
        payload = json.loads(predictions.read_text(encoding="utf-8"))
        require(set(payload) == {"mteb_model_meta", "default"} and set(payload["default"]) == {"test"},
                "native predictions: unexpected scope")
        require(payload["mteb_model_meta"] == {"model_name": "mteb/baseline-random-encoder", "revision": "2"},
                "native predictions: metadata differs")
        scores = payload["default"]["test"]
        require(set(scores) == {"q1", "q2"} and all(
            set(docs) == {"doc_a", "doc_m", "doc_z"} and len(set(docs.values())) == 1
            and all(isinstance(s, (int, float)) and not isinstance(s, bool) and math.isfinite(s)
                    for s in docs.values()) for docs in scores.values()),
            "native predictions: original candidates or exact ties differ")
        before = digest(predictions)
        tree = ast.parse(bridge)
        values = {"source": ast.parse(f"Path({predictions.name!r})", mode="eval").body,
                  "destination": ast.parse("Path('selected-scores.csv')", mode="eval").body,
                  "subset": ast.Constant("default"), "split": ast.Constant("test")}
        for node in tree.body:
            if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) and node.targets[0].id in values:
                node.value = values[node.targets[0].id]
        (result_dir / "recipe.py").write_text(ast.unparse(ast.fix_missing_locations(tree)) + "\n", encoding="utf-8")
        run_core(["recipe.py"], result_dir)
        rows = read_predictions(result_dir / "selected-scores.csv")
        require([(r.query_id, r.item_id, r.score, r.relevance) for r in rows] == [
            (q, d, score, None) for q, docs in scores.items() for d, score in docs.items()],
            "CSV bridge: IDs, scores, order or unknown labels changed")
        csv_hash = digest(result_dir / "selected-scores.csv")
        run_core(["recipe.py"], result_dir, expected_success=False)
        require(digest(result_dir / "selected-scores.csv") == csv_hash,
                "CSV bridge: existing destination changed")
        with (result_dir / "supplied-qrels.csv").open("x", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["query_id", "item_id", "relevance"])
            writer.writerows((q, d, grade) for q, docs in labels.items() for d, grade in docs.items())
        for name, extra, unknown in (("score-only", [], 6), ("sparse-judgments", ["--qrels", "supplied-qrels.csv"], 4)):
            run_core(["-m", "rankprobe", "audit", "selected-scores.csv", *extra,
                      "--cutoffs", "1,3", "--fail-on", "never", "--out", name], result_dir)
            report = json.loads((result_dir / name / "report.json").read_text(encoding="utf-8"))
            require((result_dir / name / "report.html").stat().st_size > 0, "CLI: HTML missing")
            require(report["summary"]["unknown_candidates"] == unknown
                    and report["summary"]["assumed_nonrelevant_candidates"] == 0
                    and report["protocol"]["unjudged"] == "unknown" and not report["protocol"]["qrels_complete"]
                    and report["tie_analysis"]["tie_groups"] == 2, "CLI: ties or unknown semantics differ")
            for key, metric in report["metrics"].items():
                if name == "sparse-judgments" and key.startswith("mrr@"):
                    require(metric["value"] == 1 and metric["status"] == "partial"
                            and metric["eligible_query_ids"] == ["q1"] and metric["total_queries"] == 2,
                            "CLI: MRR prefix eligibility differs")
                else:
                    require(metric["value"] is None, "CLI: unresolved metric acquired a value")
        require(digest(predictions) == before and digest(recipe) == recipe_hash, "inputs: source bytes changed")
        native_scores = native.task_results[0].scores["test"][0]
        summary = {"status": "ok", "scope": "native MTEB task with original synthetic text",
                   "python": platform.python_version(), "platform": platform.system(), "versions": versions,
                   "mteb_source_commit": "a689529bef70dae42c0747105154c10b00c63879",
                   "source_sha256": source_hashes, "recipe_sha256": recipe_hash,
                   "prediction_sha256": before, "queries": 2, "candidates": 6,
                   "runtime_network_attempts": network["attempts"],
                   "nonfinite_native_auxiliary_metrics": sorted(k for k, v in native_scores.items()
                                                               if isinstance(v, float) and not math.isfinite(v)),
                   "checks": dict.fromkeys(("native_modules_verified", "official_task_and_model_called",
                       "original_in_memory_input", "only_selected_scope_saved", "native_metadata_preserved",
                       "no_runtime_network", "exact_ties_observed", "documented_bridge_executed",
                       "scores_ids_order_preserved", "no_inline_labels_invented", "both_cli_reports_created",
                       "unknown_labels_preserved", "complete_qrels_not_assumed", "mrr_prefix_coverage_verified",
                       "source_bytes_unchanged", "existing_destination_preserved"), True),
                   "limitations": ["Synthetic native capture; no benchmark dataset or pretrained weights used.",
                       "No numerical parity with native MTEB metrics is asserted.",
                       "Auxiliary native statistics may be undefined for this tiny tied fixture.",
                       "No outside adoption or human time saved has been measured."]}
        (result_dir / "summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        new_output_directory(out)
        shutil.copytree(result_dir, out)
        return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--recipe", type=Path)
    args = parser.parse_args(argv)
    try:
        result = check_workflow(args.out, args.recipe)
    except GateError as exc:
        print(f"MTEB workflow check failed: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"MTEB workflow check failed: native or file operation ({type(exc).__name__})", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
