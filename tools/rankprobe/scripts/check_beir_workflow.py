"""Check a model-free BEIR export/evaluation workflow with original synthetic data.

BEIR and its export/evaluation dependencies are optional and imported only when
the check runs. This is an integration check, not a retrieval benchmark.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
import csv
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


def check_split_loader_scope(out: Path) -> dict:
    from beir.datasets.data_loader import GenericDataLoader

    folder = out / "loader-split-scope"
    folder.mkdir(exist_ok=False)
    corpus = {
        "d_dev": {"title": "Toy development", "text": "Original development document."},
        "d_test": {"title": "Toy test", "text": "Original test document."},
    }
    cases = (("shared", "q_shared", "q_shared"), ("disjoint", "q_dev", "q_test"))
    inputs = []
    for name, dev_query, test_query in cases:
        dataset = folder / name
        dataset.mkdir(exist_ok=False)
        (dataset / "qrels").mkdir(exist_ok=False)
        records = {
            "corpus.jsonl": [
                {"_id": item_id, **document} for item_id, document in corpus.items()
            ],
            "queries.jsonl": [
                {"_id": query_id, "text": f"Original query {query_id}."}
                for query_id in dict.fromkeys((dev_query, test_query))
            ],
        }
        for filename, rows in records.items():
            path = new_file(dataset / filename)
            with path.open("x", encoding="utf-8", newline="\n") as handle:
                for row in rows:
                    handle.write(json.dumps(row, ensure_ascii=True, allow_nan=False) + "\n")
            inputs.append(path)
        for split, query_id, item_id in (
            ("dev", dev_query, "d_dev"), ("test", test_query, "d_test")
        ):
            path = new_file(dataset / "qrels" / f"{split}.tsv")
            with path.open("x", encoding="utf-8", newline="\n") as handle:
                handle.write(f"query-id\tcorpus-id\tscore\n{query_id}\t{item_id}\t1\n")
            inputs.append(path)
    hashes_before = {path.relative_to(out).as_posix(): digest(path) for path in inputs}

    shared = folder / "shared"
    reused = GenericDataLoader(data_folder=str(shared))
    dev_corpus, dev_queries, dev_qrels = reused.load(split="dev")
    expected_dev = {"q_shared": {"d_dev": 1}}
    expected_test = {"q_shared": {"d_test": 1}}
    expected_merged = {"q_shared": {"d_dev": 1, "d_test": 1}}
    require(dev_corpus == corpus and set(dev_queries) == {"q_shared"},
            "split loader: initial shared dev data differs")
    require(dev_qrels == expected_dev, "split loader: initial shared dev judgments differ")
    dev_snapshot = deepcopy(dev_qrels)
    _, test_queries, test_qrels = reused.load(split="test")
    require(set(test_queries) == {"q_shared"} and test_qrels == expected_merged,
            "split loader: expected shared-query judgment merge was not observed")
    require(test_qrels is dev_qrels and dev_qrels is reused.qrels,
            "split loader: expected returned judgment reference was not shared")
    require(dev_qrels != dev_snapshot and dev_qrels == expected_merged,
            "split loader: earlier dev judgment reference did not change")

    fresh_scopes = {}
    for name, dev_query, test_query in cases:
        dataset = folder / name
        fresh = {}
        for split, query_id, item_id in (
            ("dev", dev_query, "d_dev"), ("test", test_query, "d_test")
        ):
            loaded_corpus, queries, judgments = GenericDataLoader(
                data_folder=str(dataset)
            ).load(split=split)
            require(loaded_corpus == corpus, "split loader: fresh corpus differs")
            require(queries == {query_id: f"Original query {query_id}."},
                    "split loader: fresh query scope differs")
            require(judgments == {query_id: {item_id: 1}},
                    "split loader: fresh judgment scope differs")
            fresh[split] = judgments
        require(fresh["dev"] is not fresh["test"],
                "split loader: fresh split judgments unexpectedly share a reference")
        require(fresh["dev"] == {dev_query: {"d_dev": 1}},
                "split loader: fresh dev judgments changed after loading test")
        fresh_scopes[name] = deepcopy(fresh)
    require(fresh_scopes["shared"] == {"dev": expected_dev, "test": expected_test},
            "split loader: fresh shared-query splits were not isolated")

    disjoint = GenericDataLoader(data_folder=str(folder / "disjoint"))
    _, disjoint_dev_queries, disjoint_dev_qrels = disjoint.load(split="dev")
    require(set(disjoint_dev_queries) == {"q_dev"}
            and disjoint_dev_qrels == {"q_dev": {"d_dev": 1}},
            "split loader: initial disjoint dev data differs")
    try:
        disjoint.load(split="test")
    except KeyError as exc:
        require(exc.args == ("q_test",), "split loader: unexpected disjoint missing-query error")
    else:
        raise GateError("split loader: expected disjoint-query KeyError was not observed")
    expected_disjoint_merge = {"q_dev": {"d_dev": 1}, "q_test": {"d_test": 1}}
    require(disjoint.qrels == expected_disjoint_merge
            and disjoint_dev_qrels is disjoint.qrels,
            "split loader: disjoint failure did not preserve the expected merged reference")
    require(all(digest(path) == hashes_before[path.relative_to(out).as_posix()]
                for path in inputs), "split loader: generated dataset files changed")

    return {
        "synthetic_input_sha256": hashes_before,
        "observations": {
            "shared_dev_judgments_before_reuse": dev_snapshot,
            "shared_test_judgments_from_reused_loader": deepcopy(test_qrels),
            "shared_prior_dev_reference_after_reuse": deepcopy(dev_qrels),
            "shared_returned_qrels_is_same_object": test_qrels is dev_qrels,
            "fresh_loader_scopes": fresh_scopes,
            "disjoint_reused_loader_second_split_error": "KeyError",
            "disjoint_judgments_after_failed_second_load": deepcopy(disjoint.qrels),
        },
        "checks": {
            "real_generic_data_loader_called": True,
            "reused_loader_shared_query_judgments_merged": True,
            "prior_split_judgment_reference_mutation_observed": True,
            "fresh_loader_per_split_scopes_preserved": True,
            "reused_loader_disjoint_query_keyerror_observed": True,
            "generated_loader_dataset_files_unchanged": True,
        },
    }


def check_duplicate_loader_judgments(out: Path) -> dict:
    from beir.datasets.data_loader import GenericDataLoader
    from rankprobe.io import InputError, read_qrels

    folder = out / "loader-source-duplicates"
    folder.mkdir(exist_ok=False)
    shared = out / "loader-split-scope" / "shared"
    reused_inputs = (shared / "corpus.jsonl", shared / "queries.jsonl")
    hashes_before = {path.relative_to(out).as_posix(): digest(path) for path in reused_inputs}
    inputs = list(reused_inputs)
    observations = {}
    loaded_by_order = []
    for name, grades in (("one-then-zero", (1, 0)), ("zero-then-one", (0, 1))):
        source = new_file(folder / f"{name}.tsv")
        with source.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write("query-id\tcorpus-id\tscore\n")
            for grade in grades:
                handle.write(f"q_shared\td_dev\t{grade}\n")
        inputs.append(source)
        hashes_before[source.relative_to(out).as_posix()] = digest(source)
        corpus, queries, judgments = GenericDataLoader(
            corpus_file=str(reused_inputs[0]), query_file=str(reused_inputs[1]),
            qrels_file=str(source),
        ).load_custom()
        expected = {"q_shared": {"d_dev": grades[-1]}}
        require("d_dev" in corpus and set(queries) == {"q_shared"},
                "source duplicates: loaded corpus or query scope differs")
        require(judgments == expected,
                "source duplicates: fresh loader did not retain the final source grade")
        loaded_by_order.append(judgments)

        with source.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.reader(handle, delimiter="\t"))
        require(rows[0] == ["query-id", "corpus-id", "score"]
                and rows[1:] == [["q_shared", "d_dev", str(grade)] for grade in grades],
                "source duplicates: original conflicting rows differ")
        mapped = new_file(folder / f"{name}-mapped.qrels")
        with mapped.open("x", encoding="utf-8", newline="\n") as handle:
            for query_id, items in judgments.items():
                for item_id, grade in items.items():
                    handle.write(f"{query_id} 0 {item_id} {grade}\n")
        inputs.append(mapped)
        hashes_before[mapped.relative_to(out).as_posix()] = digest(mapped)
        require(len(mapped.read_text(encoding="utf-8").splitlines()) == 1,
                "source duplicates: mapped export did not contain one surviving row")
        parsed_mapped = read_qrels(mapped)
        require(parsed_mapped == expected,
                "source duplicates: mapped export changed the surviving judgment")

        # Only these verified invented tokens are copied; this is not a general TSV converter.
        preserved = new_file(folder / f"{name}-source-rows.qrels")
        with preserved.open("x", encoding="utf-8", newline="\n") as handle:
            for query_id, item_id, grade in rows[1:]:
                handle.write(f"{query_id} 0 {item_id} {grade}\n")
        inputs.append(preserved)
        hashes_before[preserved.relative_to(out).as_posix()] = digest(preserved)
        require(preserved.read_text(encoding="utf-8").splitlines()
                == [f"q_shared 0 d_dev {grade}" for grade in grades],
                "source duplicates: row-preserving copy changed row order or grades")
        try:
            read_qrels(preserved)
        except InputError as exc:
            require(f"{preserved}:2:" in str(exc) and "duplicate qrels entry" in str(exc),
                    "source duplicates: row-preserving copy had an unexpected rejection")
        else:
            raise GateError("source duplicates: repeated original judgment rows were accepted")
        observations[name] = {
            "source_grades_in_order": list(grades), "source_judgment_rows": len(rows) - 1,
            "fresh_loader_judgments": deepcopy(judgments),
            "mapped_trec_judgment_rows": 1, "mapped_trec_parsed_judgments": parsed_mapped,
            "row_preserving_trec_rows": 2, "row_preserving_copy_error": "duplicate qrels entry",
        }
    require(loaded_by_order[0] is not loaded_by_order[1],
            "source duplicates: fresh loader judgment dictionaries share a reference")
    require(loaded_by_order == [{"q_shared": {"d_dev": 0}}, {"q_shared": {"d_dev": 1}}],
            "source duplicates: reversed source order did not change the surviving judgment")
    require(all(digest(path) == hashes_before[path.relative_to(out).as_posix()]
                for path in inputs), "source duplicates: original or generated inputs changed")
    observations["original_and_generated_inputs_unchanged"] = True
    return {
        "synthetic_input_sha256": {
            path.relative_to(out).as_posix(): hashes_before[path.relative_to(out).as_posix()]
            for path in inputs if path not in reused_inputs
        },
        "observations": observations,
        "checks": {
            "fresh_loader_source_conflict_last_row_wins": True,
            "duplicate_row_order_changes_loaded_judgment": True,
            "mapped_export_keeps_only_surviving_judgment": True,
            "row_preserving_duplicate_copy_rejected": True,
        },
    }


def check_bom_loader_judgments(out: Path) -> dict:
    from beir.datasets.data_loader import GenericDataLoader
    from rankprobe.io import read_qrels

    folder = out / "loader-bom-qrels"
    folder.mkdir(exist_ok=False)
    shared = out / "loader-split-scope" / "shared"
    reused_inputs = (shared / "corpus.jsonl", shared / "queries.jsonl")
    hashes_before = {path.relative_to(out).as_posix(): digest(path) for path in reused_inputs}
    source = new_file(folder / "bom-source.tsv")
    with source.open("x", encoding="utf-8-sig", newline="\n") as handle:
        handle.write("query-id\tcorpus-id\tscore\nq_shared\td_dev\t1\nq_shared\td_test\t-1\n")
    hashes_before[source.relative_to(out).as_posix()] = digest(source)
    require(source.read_bytes().startswith(b"\xef\xbb\xbf"),
            "BOM qrels: generated source has no UTF-8 BOM")
    corpus, queries, judgments = GenericDataLoader(
        corpus_file=str(reused_inputs[0]), query_file=str(reused_inputs[1]),
        qrels_file=str(source),
    ).load_custom()
    require({"d_dev", "d_test"} <= set(corpus) and set(queries) == {"q_shared"},
            "BOM qrels: native corpus or query scope differs")
    require(judgments == {"q_shared": {"d_dev": 1, "d_test": -1}}
            and all(type(grade) is int for grade in judgments["q_shared"].values()),
            "BOM qrels: native loader changed supplied integer judgments")
    mapped = new_file(folder / "mapped.qrels")
    with mapped.open("x", encoding="utf-8", newline="\n") as handle:
        for query_id, items in judgments.items():
            for item_id, grade in items.items():
                handle.write(f"{query_id} 0 {item_id} {grade}\n")
    hashes_before[mapped.relative_to(out).as_posix()] = digest(mapped)
    parsed = read_qrels(mapped)
    require(parsed == {"q_shared": {"d_dev": 1, "d_test": None}}
            and parsed["q_shared"]["d_test"] is None,
            "BOM qrels: mapped explicit unknown was changed or resolved as zero")
    inputs = (*reused_inputs, source, mapped)
    require(all(digest(path) == hashes_before[path.relative_to(out).as_posix()]
                for path in inputs), "BOM qrels: original or generated inputs changed")
    return {
        "synthetic_input_sha256": {
            path.relative_to(out).as_posix(): hashes_before[path.relative_to(out).as_posix()]
            for path in (source, mapped)
        },
        "observations": {
            "source_has_utf8_bom": True, "native_judgments": judgments,
            "mapped_trec_judgments": parsed, "source_judgment_rows": 2,
            "original_and_generated_inputs_unchanged": True,
        },
        "checks": {"bom_tsv_native_and_explicit_unknown_preserved": True},
    }


def check_workflow(out: Path) -> dict:
    out = new_output_directory(out)
    try:
        from beir import util
        from beir.datasets import data_loader
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
    for name, module in (
        ("beir.util", util), ("beir.retrieval.evaluation", evaluation),
        ("beir.datasets.data_loader", data_loader),
    ):
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
    loader_scope = check_split_loader_scope(out)
    duplicate_scope = check_duplicate_loader_judgments(out)
    bom_scope = check_bom_loader_judgments(out)

    result = {
        "status": "passed", "python": platform.python_version(), "platform": sys.platform,
        "versions": versions, "beir_source_sha256": source_hashes,
        "synthetic_input_sha256": {
            **hashes_before, **loader_scope["synthetic_input_sha256"],
            **duplicate_scope["synthetic_input_sha256"],
            **bom_scope["synthetic_input_sha256"],
        },
        "observations": {
            "original_mrr_at_1": 0.5, "filtered_mrr_at_1": 1.0,
            "structurally_matched_query_ids": ["q2"], "matched_mrr_at_1_delta": 0.0,
            "default_export_candidates": 1000, "explicit_export_candidates": 1002,
            "generic_data_loader_split_scope": loader_scope["observations"],
            "generic_data_loader_source_duplicates": duplicate_scope["observations"],
            "generic_data_loader_bom_qrels": bom_scope["observations"],
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
            **loader_scope["checks"],
            **duplicate_scope["checks"],
            **bom_scope["checks"],
        },
        "limitations": [
            "Original synthetic export/evaluation and generated local dataset-loader cases only; "
            "no model or benchmark dataset was loaded.",
            "Observed self-match filtering is a declared policy, not evidence of leakage.",
            "Matched IDs and labels do not establish matching provenance or model quality.",
            "This check does not establish universal metric parity with BEIR or human time saved.",
            "Loader reuse observations target the pinned source, not every BEIR version or "
            "dataset workflow; fresh instances preserve only the declared split-file scope.",
            "A mapped judgment export contains only the loader's surviving values; it does not "
            "establish source-row uniqueness or recover overwritten annotations.",
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
