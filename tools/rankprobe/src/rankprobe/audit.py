"""Evidence-bounded ranking audits. Findings describe risks, never model bugs."""

from __future__ import annotations

from dataclasses import asdict, replace
from itertools import combinations, groupby

from .model import Protocol, Row
from .metrics import (
    Qrels,
    _evaluate_rankings,
    deduplicate_rows,
    evaluate_metrics,
    group_rows,
    metric_deltas,
    rank_rows,
    resolve_rows,
    validate_inputs,
)

_SAMPLE_LIMIT = 10


def _finding(code: str, severity: str, title: str, message: str, evidence: dict) -> dict:
    return {
        "code": code,
        "severity": severity,
        "title": title,
        "message": message,
        "evidence": evidence,
    }


def _duplicate_analysis(
    rows: list[Row], protocol: Protocol, qrels: Qrels | None, primary_metrics: dict
) -> dict:
    groups: dict[tuple[str, str], list[Row]] = {}
    for row in rows:
        groups.setdefault((row.query_id, row.item_id), []).append(row)
    duplicates = {key: group for key, group in groups.items() if len(group) > 1}
    examples = []
    for (query_id, item_id), group in sorted(duplicates.items())[:_SAMPLE_LIMIT]:
        scores = sorted({r.score for r in group})
        examples.append(
            {
                "query_id": query_id,
                "item_id": item_id,
                "occurrences": len(group),
                "scores": scores[:_SAMPLE_LIMIT],
                "distinct_score_count": len(scores),
                "selected_score": max(r.score for r in group),
            }
        )
    result = {
        "status": "checked",
        "duplicate_groups": len(duplicates),
        "duplicate_rows": sum(len(group) - 1 for group in duplicates.values()),
        "conflicting_scores": sum(
            len({r.score for r in group}) > 1 for group in duplicates.values()
        ),
        "examples": examples,
        "metric_sensitivity": {
            "status": "not_applicable",
            "reason": "No repeated query-item pairs.",
        },
    }
    if duplicates:
        raw = evaluate_metrics(rows, protocol, qrels, duplicate_policy="preserve_rows")
        result["metric_sensitivity"] = {
            "status": "checked",
            "deduplicated": primary_metrics,
            "raw_rows": raw,
            "delta_raw_minus_deduplicated": metric_deltas(primary_metrics, raw),
            "reason": "Raw-row metrics are a diagnostic counterfactual, not a valid ranking of unique items. NDCG may exceed 1 when repeated gains are counted.",
        }
    return result


def _tie_analysis(rows: list[Row], protocol: Protocol, qrels: Qrels | None) -> dict:
    grouped = group_rows(rows)
    best, worst = {}, {}
    tied_queries, examples = [], []
    tied_candidates = tie_groups = 0
    for query_id, group in grouped.items():
        ranking = rank_rows(group, "item_id")
        optimum, pessimum = [], []
        query_has_ties = False
        complete = all(row.relevance is not None for row in group)
        missing_query = protocol.qrels_complete and (qrels is None or query_id not in qrels)
        for score, members_iter in groupby(ranking, key=lambda row: row.score):
            members = list(members_iter)
            if len(members) > 1:
                query_has_ties = True
                tie_groups += 1
                tied_candidates += len(members)
                if len(examples) < _SAMPLE_LIMIT:
                    examples.append(
                        {
                            "query_id": query_id,
                            "score": score,
                            "size": len(members),
                            "item_ids": [r.item_id for r in members[:_SAMPLE_LIMIT]],
                            "judgments_known": all(r.relevance is not None for r in members),
                        }
                    )
            if complete and not missing_query:
                optimum.extend(sorted(members, key=lambda row: (-row.relevance, row.item_id)))
                pessimum.extend(sorted(members, key=lambda row: (row.relevance, row.item_id)))
        if query_has_ties:
            tied_queries.append(query_id)
        if complete and not missing_query:
            best[query_id], worst[query_id] = optimum, pessimum
    best_metrics = _evaluate_rankings(best, protocol, qrels)
    worst_metrics = _evaluate_rankings(worst, protocol, qrels)
    bounds = {}
    for key in best_metrics:
        high, low = best_metrics[key], worst_metrics[key]
        available = high["value"] is not None and low["value"] is not None
        excluded_query_ids = sorted(set(grouped) - set(high["eligible_query_ids"]))
        status = (
            "not_checked"
            if not available
            else "partial"
            if excluded_query_ids or high["status"] != "ok" or low["status"] != "ok"
            else "checked"
        )
        bounds[key] = {
            "min": low["value"],
            "max": high["value"],
            "width": high["value"] - low["value"] if available else None,
            "status": status,
            "evaluated_queries": high["evaluated_queries"],
            "total_queries": len(grouped),
            "excluded_queries": len(excluded_query_ids),
            "eligible_query_ids": high["eligible_query_ids"],
            "excluded_query_ids": excluded_query_ids,
            "reference": high["reference"],
        }
    reverse_rows = [row for group in grouped.values() for row in reversed(group)]
    original = evaluate_metrics(rows, protocol, qrels, tie_policy="input")
    reversed_metrics = evaluate_metrics(reverse_rows, protocol, qrels, tie_policy="input")
    return {
        "status": "checked",
        "queries_with_ties": len(tied_queries),
        "tie_groups": tie_groups,
        "tied_candidate_count": tied_candidates,
        "examples": examples,
        "metric_bounds": bounds,
        "bounds_scope": "Exact extrema over permutations within equal-score groups, on queries whose candidate judgments are all known. Query-level extrema may use different tie orders for different metrics; bounds are not a joint confidence interval.",
        "input_order_probe": {
            "original": original,
            "reversed": reversed_metrics,
            "delta_reversed_minus_original": metric_deltas(original, reversed_metrics),
            "reason": "Reverses submitted candidate order within each query, then uses stable score sorting. This is one counterexample probe; the exact bounds cover all within-tie permutations.",
        },
    }


def audit_run(
    rows: list[Row], protocol: Protocol, qrels: Qrels | None = None, run_name: str = "run"
) -> dict:
    """Audit one run, preserving source records and returning finite JSON data."""
    checked = validate_inputs(rows, protocol, qrels)
    resolved = resolve_rows(checked, protocol, qrels)
    unique = deduplicate_rows(resolved)
    metrics = evaluate_metrics(checked, protocol, qrels)
    duplicates = _duplicate_analysis(checked, protocol, qrels, metrics)
    ties = _tie_analysis(unique, protocol, qrels)
    unknown = [r for r in unique if r.relevance is None]
    supplied_labels = {(r.query_id, r.item_id) for r in checked if r.relevance is not None}
    candidate_keys = {(r.query_id, r.item_id) for r in unique}
    explicit_unjudged = {
        (query_id, item_id)
        for query_id, judgments in (qrels or {}).items()
        for item_id, relevance in judgments.items()
        if relevance is None
    }
    unjudged_candidates = explicit_unjudged & candidate_keys
    inline_labeled_unjudged = unjudged_candidates & supplied_labels
    known_labels = supplied_labels | {
        (query_id, item_id)
        for query_id, judgments in (qrels or {}).items()
        for item_id, relevance in judgments.items()
        if relevance is not None
    }
    assumed = implicit_qrels_zero = 0
    for row in unique:
        if (row.query_id, row.item_id) in supplied_labels:
            continue
        judgments = None if qrels is None else qrels.get(row.query_id)
        if judgments is not None and judgments.get(row.item_id) is not None:
            continue
        if judgments is not None and protocol.qrels_complete:
            implicit_qrels_zero += 1
        elif protocol.unjudged == "nonrelevant":
            assumed += 1
    missing_queries = (
        sorted(set(group_rows(unique)) - set(qrels or {})) if protocol.qrels_complete else []
    )
    qrels_only_queries = sorted(set(qrels or {}) - set(group_rows(unique)))
    constant_queries = [
        query_id
        for query_id, group in group_rows(unique).items()
        if len(group) > 1 and len({r.score for r in group}) == 1
    ]
    constant = [replace(row, score=0.0) for row in unique]
    constant_item = evaluate_metrics(constant, protocol, qrels, tie_policy="item_id")
    constant_input = evaluate_metrics(constant, protocol, qrels, tie_policy="input")
    findings = []
    if not checked:
        findings.append(
            _finding(
                "empty_run",
                "warning",
                "No prediction rows",
                "No ranking metrics or data checks can establish run quality from an empty run.",
                {},
            )
        )
    if duplicates["duplicate_groups"]:
        findings.append(
            _finding(
                "duplicate_candidates",
                "warning",
                "Repeated candidates",
                "The primary metrics keep the maximum score for each query-item pair. Inspect whether repetitions are intentional; raw-row counting can change metrics.",
                {
                    "groups": duplicates["duplicate_groups"],
                    "extra_rows": duplicates["duplicate_rows"],
                    "examples": duplicates["examples"],
                },
            )
        )
    if ties["queries_with_ties"]:
        findings.append(
            _finding(
                "score_ties",
                "warning",
                "Equal scores make tie policy consequential",
                "Equal scores do not establish a model defect. Inspect exact metric bounds and the input-order probe, and declare the tie policy when comparing results.",
                {
                    "queries": ties["queries_with_ties"],
                    "groups": ties["tie_groups"],
                    "examples": ties["examples"],
                },
            )
        )
    if constant_queries:
        findings.append(
            _finding(
                "constant_scores",
                "warning",
                "Constant-score queries",
                "All candidates share a score in these queries. Their order is determined entirely by the tie policy; a nonzero metric is not evidence of discrimination by scores.",
                {
                    "count": len(constant_queries),
                    "query_ids": sorted(constant_queries)[:_SAMPLE_LIMIT],
                },
            )
        )
    if unknown:
        findings.append(
            _finding(
                "unknown_judgments",
                "warning",
                "Judgment coverage limits metrics",
                "Unknown relevance is not silently zero. MRR requires known labels through the first relevant item within top-k; an earlier unknown excludes the query, while later unknowns stay unknown without affecting that reciprocal rank. With no relevant item, every top-k label must be known to report zero. NDCG excludes queries with any unknown candidate label.",
                {
                    "candidates": len(unknown),
                    "examples": [
                        {"query_id": r.query_id, "item_id": r.item_id}
                        for r in unknown[:_SAMPLE_LIMIT]
                    ],
                },
            )
        )
    if explicit_unjudged:
        findings.append(
            _finding(
                "explicit_unjudged_qrels",
                "warning",
                "Qrels explicitly contain unjudged items",
                "TREC -1 or API None records no source judgment, not a verified zero. Known inline labels are retained; otherwise relevance stays unknown unless unjudged='nonrelevant' explicitly assumes zero. These qrels cannot support a complete-qrels declaration.",
                {
                    "entries": len(explicit_unjudged),
                    "retrieved_candidates": len(unjudged_candidates),
                    "known_inline_labels": len(inline_labeled_unjudged),
                    "assumed_nonrelevant_candidates": len(
                        unjudged_candidates - supplied_labels
                    )
                    if protocol.unjudged == "nonrelevant"
                    else 0,
                    "examples": [
                        {"query_id": query_id, "item_id": item_id}
                        for query_id, item_id in sorted(explicit_unjudged)[:_SAMPLE_LIMIT]
                    ],
                },
            )
        )
    if missing_queries:
        findings.append(
            _finding(
                "missing_qrels_queries",
                "warning",
                "Queries missing from complete qrels",
                "Completeness was declared, but these query IDs are absent. They are excluded from every metric rather than assumed to have no relevant items.",
                {"count": len(missing_queries), "query_ids": missing_queries[:_SAMPLE_LIMIT]},
            )
        )
    if qrels_only_queries:
        findings.append(
            _finding(
                "qrels_queries_without_predictions",
                "warning",
                "Qrels queries have no submitted predictions",
                "These qrels query IDs are absent from the run. Macro averages cover only submitted prediction queries, not the entire qrels query set. Missing predictions are not automatically scored as zero; confirm the intended evaluation universe.",
                {"count": len(qrels_only_queries), "query_ids": qrels_only_queries[:_SAMPLE_LIMIT]},
            )
        )
    if not protocol.qrels_complete:
        findings.append(
            _finding(
                "limited_reference_pool",
                "info",
                "NDCG reference is limited; Recall is unavailable",
                "NDCG uses the submitted candidate pool or known qrels pool. It does not establish full-corpus retrieval quality. Recall requires explicitly complete qrels.",
                {
                    "ndcg_references": sorted(
                        {m["reference"] for name, m in metrics.items() if name.startswith("ndcg")}
                    ),
                    "recall_status": "not_checked",
                },
            )
        )
    if protocol.unjudged == "nonrelevant":
        findings.append(
            _finding(
                "unjudged_assumed_nonrelevant",
                "warning",
                "Explicit nonrelevance assumption",
                "The selected protocol maps unjudged candidates to zero. This is a user-declared evaluation assumption, not a verified label.",
                {"assumed_candidates": assumed},
            )
        )
    return {
        "schema_version": "0.1",
        "report_type": "audit",
        "run_name": str(run_name),
        "summary": {
            "queries": len(group_rows(unique)),
            "rows": len(checked),
            "unique_candidates": len(unique),
            "duplicate_rows": len(checked) - len(unique),
            "judged_candidates": len(candidate_keys & known_labels),
            "resolved_candidates": len(unique) - len(unknown),
            "unknown_candidates": len(unknown),
            "assumed_nonrelevant_candidates": assumed,
            "implicit_complete_qrels_zeros": implicit_qrels_zero,
            "qrels_queries": len(qrels) if qrels is not None else None,
            "explicit_unjudged_qrels": len(explicit_unjudged),
            "explicit_unjudged_qrels_candidates": len(unjudged_candidates),
            "inline_labeled_unjudged_qrels_candidates": len(inline_labeled_unjudged),
            "qrels_queries_without_predictions": len(qrels_only_queries),
            "query_universe": "submitted_prediction_queries",
        },
        "protocol": asdict(protocol),
        "metrics": metrics,
        "findings": findings,
        "tie_analysis": ties,
        "duplicates": duplicates,
        "negative_controls": {
            "constant_scores": {
                "status": "checked" if checked else "not_checked",
                "metrics": constant_item,
                "input_order_metrics": constant_input,
                "item_id_vs_input_delta": metric_deltas(constant_item, constant_input),
                "reason": "All scores are set to zero while candidates and judgments stay fixed. The result measures tie-policy behavior, not model performance; nonzero values may be expected.",
            }
        },
        "limitations": [
            "This audit does not inspect training data, temporal leakage, provenance, or distribution shift.",
            "Findings identify evaluation risks and counterfactual sensitivity, not proof of a model bug.",
            "Macro averages use only eligible queries; inspect coverage and reference pools before comparing.",
        ],
    }


def compare_runs(
    runs: dict[str, list[Row]], protocol: Protocol, qrels: Qrels | None = None
) -> dict:
    """Compare query coverage, candidates, labels, and same-pool sensitivity."""
    if not isinstance(runs, dict) or len(runs) < 2:
        raise ValueError("compare_runs requires at least two named runs")
    normalized = {}
    metrics = {}
    audits = {}
    findings = []
    for name, rows in runs.items():
        if not isinstance(name, str) or not name:
            raise ValueError("run names must be nonempty strings")
        checked = validate_inputs(rows, protocol, qrels)
        normalized[name] = group_rows(deduplicate_rows(resolve_rows(checked, protocol, qrels)))
        audits[name] = audit_run(checked, protocol, qrels, name)
        metrics[name] = audits[name]["metrics"]
        for finding in audits[name]["findings"]:
            findings.append(
                {
                    **finding,
                    "run_name": name,
                    "message": f"Run {name!r}: {finding['message']}",
                    "evidence": {"run_name": name, **finding["evidence"]},
                }
            )
    pairs = []
    for left_name, right_name in combinations(runs, 2):
        left, right = normalized[left_name], normalized[right_name]
        common_queries = set(left) & set(right)
        only_left, only_right = sorted(set(left) - set(right)), sorted(set(right) - set(left))
        differences, label_conflicts = [], []
        comparable_query_ids = []
        for query_id in sorted(common_queries):
            a, b = {r.item_id: r for r in left[query_id]}, {r.item_id: r for r in right[query_id]}
            if set(a) != set(b):
                differences.append(
                    {
                        "query_id": query_id,
                        "left_only_count": len(set(a) - set(b)),
                        "right_only_count": len(set(b) - set(a)),
                        "left_only": sorted(set(a) - set(b))[:_SAMPLE_LIMIT],
                        "right_only": sorted(set(b) - set(a))[:_SAMPLE_LIMIT],
                    }
                )
            conflicts_for_query = 0
            for item_id in sorted(set(a) & set(b)):
                if a[item_id].relevance != b[item_id].relevance:
                    conflicts_for_query += 1
                    label_conflicts.append(
                        {
                            "query_id": query_id,
                            "item_id": item_id,
                            "left_relevance": a[item_id].relevance,
                            "right_relevance": b[item_id].relevance,
                        }
                    )
            if set(a) == set(b) and not conflicts_for_query:
                comparable_query_ids.append(query_id)
        same_queries = not only_left and not only_right
        same_candidates = not differences
        same_labels = not label_conflicts
        status = (
            "comparable"
            if same_queries and same_candidates and same_labels and common_queries
            else "partially_comparable"
            if comparable_query_ids
            else "not_comparable"
        )
        left_common = [r for q in comparable_query_ids for r in left[q]]
        right_common = [r for q in comparable_query_ids for r in right[q]]
        restricted_left = evaluate_metrics(left_common, protocol, qrels)
        restricted_right = evaluate_metrics(right_common, protocol, qrels)
        pair = {
            "left": left_name,
            "right": right_name,
            "status": status,
            "query_coverage": {
                "left_queries": len(left),
                "right_queries": len(right),
                "common_queries": len(common_queries),
                "left_only_count": len(only_left),
                "right_only_count": len(only_right),
                "left_only": only_left[:_SAMPLE_LIMIT],
                "right_only": only_right[:_SAMPLE_LIMIT],
            },
            "candidate_sets": {
                "differing_queries": len(differences),
                "examples": differences[:_SAMPLE_LIMIT],
            },
            "label_consistency": {
                "conflicts": len(label_conflicts),
                "examples": label_conflicts[:_SAMPLE_LIMIT],
            },
            "matched_pool_comparison": {
                "status": "checked" if comparable_query_ids else "not_checked",
                "query_count": len(comparable_query_ids),
                "query_ids": comparable_query_ids,
                "left_metrics": restricted_left,
                "right_metrics": restricted_right,
                "delta_right_minus_left": metric_deltas(restricted_left, restricted_right),
                "reason": "Restricts to existing queries with identical candidate sets and resolved labels. It does not invent scores for missing candidates or establish data provenance.",
            },
        }
        pairs.append(pair)
        if not same_queries:
            findings.append(
                _finding(
                    "query_coverage_mismatch",
                    "warning",
                    "Runs cover different queries",
                    "Unrestricted macro averages use different query populations.",
                    {"left": left_name, "right": right_name, **pair["query_coverage"]},
                )
            )
        if not same_candidates:
            findings.append(
                _finding(
                    "candidate_set_mismatch",
                    "warning",
                    "Runs score different candidate sets",
                    "Metric differences may reflect candidate selection as well as ranking quality.",
                    {"left": left_name, "right": right_name, **pair["candidate_sets"]},
                )
            )
        if not same_labels:
            findings.append(
                _finding(
                    "cross_run_label_mismatch",
                    "error",
                    "Resolved relevance differs across runs",
                    "The same query-item pairs have different labels or judgment availability. These are not the same evaluation judgments.",
                    {"left": left_name, "right": right_name, **pair["label_consistency"]},
                )
            )
    return {
        "schema_version": "0.1",
        "report_type": "compare",
        "protocol": asdict(protocol),
        "summary": {
            "runs": len(runs),
            "pairs": len(pairs),
            "comparable_pairs": sum(p["status"] == "comparable" for p in pairs),
        },
        "runs": {
            name: {
                "queries": len(normalized[name]),
                "unique_candidates": sum(len(group) for group in normalized[name].values()),
                "metrics": metrics[name],
                "audit": audits[name],
            }
            for name in runs
        },
        "pairs": pairs,
        "findings": findings,
        "limitations": [
            "All runs use the single supplied protocol; historical protocol differences cannot be inferred from prediction files.",
            "Matching IDs and labels do not verify matching data provenance, training splits, or absence of leakage.",
        ],
    }
