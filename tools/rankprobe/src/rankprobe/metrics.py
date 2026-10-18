"""Independent ranking metrics with explicit judgment and reference boundaries.

Scores are sorted in descending order. Ties use either lexical item IDs or
stable input order. Relevance thresholds affect binary MRR and Recall only;
NDCG uses the nonnegative graded judgments and the selected gain function.
MRR requires a known prefix through its first relevant item, not later labels.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
import math
from typing import Iterable

from .model import Protocol, Row, _unicode_text

Qrels = dict[str, dict[str, float | None]]
MRR_ELIGIBILITY_RULE = "known_first_relevant_prefix"


def validate_inputs(
    rows: Iterable[Row], protocol: Protocol, qrels: Qrels | None = None
) -> list[Row]:
    """Validate direct Python callers as well as data loaded by the CLI."""
    if not isinstance(protocol, Protocol):
        raise ValueError("protocol must be a Protocol instance")
    try:
        rows = list(rows)
    except TypeError as exc:
        raise ValueError("rows must be an iterable of Row instances") from exc
    if protocol.qrels_complete and qrels is None:
        raise ValueError("qrels_complete=True requires an explicit qrels mapping")
    for row in rows:
        if not isinstance(row, Row):
            raise ValueError("every prediction must be a Row instance")
        if not isinstance(row.query_id, str) or not row.query_id:
            raise ValueError("query_id must be a nonempty string")
        if not isinstance(row.item_id, str) or not row.item_id:
            raise ValueError("item_id must be a nonempty string")
        if (
            isinstance(row.score, bool)
            or not isinstance(row.score, (int, float))
            or not math.isfinite(row.score)
        ):
            raise ValueError("scores must be finite numbers")
        if row.relevance is not None:
            _check_relevance(row.relevance)
    if qrels is not None:
        if not isinstance(qrels, dict):
            raise ValueError("qrels must be a mapping of query IDs to judgment mappings")
        for query_id, judgments in qrels.items():
            if not isinstance(query_id, str) or not query_id or not isinstance(judgments, dict):
                raise ValueError(
                    "qrels query IDs must be nonempty strings and judgments must be mappings"
                )
            _unicode_text(query_id, "qrels query_id")
            for item_id, relevance in judgments.items():
                if not isinstance(item_id, str) or not item_id:
                    raise ValueError("qrels item IDs must be nonempty strings")
                _unicode_text(item_id, "qrels item_id")
                if relevance is None:
                    if protocol.qrels_complete:
                        raise ValueError(
                            "qrels_complete=True contradicts explicitly unjudged qrels "
                            f"for query {query_id!r}, item {item_id!r}"
                        )
                else:
                    _check_relevance(relevance)
    labels: dict[tuple[str, str], float] = {}
    for row in rows:
        key = row.query_id, row.item_id
        if row.relevance is not None:
            if key in labels and labels[key] != row.relevance:
                raise ValueError(
                    f"conflicting relevance for query {row.query_id!r}, item {row.item_id!r}"
                )
            labels[key] = row.relevance
        if qrels is not None and row.query_id in qrels:
            judgments = qrels[row.query_id]
            if row.item_id in judgments and judgments[row.item_id] is not None:
                if row.relevance is not None and row.relevance != judgments[row.item_id]:
                    raise ValueError(
                        f"row relevance conflicts with qrels for query {row.query_id!r}, item {row.item_id!r}"
                    )
            elif protocol.qrels_complete and row.relevance not in (None, 0):
                raise ValueError(
                    f"positive row relevance is absent from complete qrels for query {row.query_id!r}, item {row.item_id!r}"
                )
    return rows


def _check_relevance(value: float) -> None:
    try:
        valid = (
            not isinstance(value, bool)
            and isinstance(value, (int, float))
            and math.isfinite(value)
            and value >= 0
        )
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError("relevance must be a finite nonnegative number")


def group_rows(rows: Iterable[Row]) -> dict[str, list[Row]]:
    result: dict[str, list[Row]] = defaultdict(list)
    for row in rows:
        result[row.query_id].append(row)
    return dict(result)


def resolve_rows(rows: list[Row], protocol: Protocol, qrels: Qrels | None) -> list[Row]:
    """Resolve known labels, authoritative known qrels, then explicit assumptions.

    An explicit unjudged qrels entry preserves a known inline label. It records
    the absence of a source judgment, not evidence against another known label.
    """
    supplied = {(r.query_id, r.item_id): r.relevance for r in rows if r.relevance is not None}
    result = []
    for row in rows:
        relevance = supplied.get((row.query_id, row.item_id))
        if qrels is not None and row.query_id in qrels:
            if row.item_id in qrels[row.query_id] and qrels[row.query_id][row.item_id] is not None:
                relevance = qrels[row.query_id][row.item_id]
            elif protocol.qrels_complete:
                relevance = 0.0
        if relevance is None and protocol.unjudged == "nonrelevant":
            relevance = 0.0
        result.append(replace(row, relevance=relevance))
    return result


def deduplicate_rows(rows: Iterable[Row]) -> list[Row]:
    """Keep one item per query, with its maximum score and first occurrence slot."""
    chosen: dict[tuple[str, str], Row] = {}
    for row in rows:
        key = row.query_id, row.item_id
        if key not in chosen or row.score > chosen[key].score:
            chosen[key] = row
    return list(chosen.values())


def rank_rows(rows: Iterable[Row], tie_policy: str) -> list[Row]:
    if tie_policy == "item_id":
        return sorted(rows, key=lambda row: (-row.score, row.item_id))
    if tie_policy == "input":
        return sorted(rows, key=lambda row: -row.score)
    raise ValueError("tie_policy must be 'item_id' or 'input'")


def _reference_pool(
    query_id: str, candidates: list[Row], protocol: Protocol, qrels: Qrels | None
) -> tuple[list[float], str]:
    if qrels is not None and query_id in qrels:
        pool = {item: rel for item, rel in qrels[query_id].items() if rel is not None}
        for row in candidates:
            if row.relevance is not None:
                pool[row.item_id] = row.relevance
        return list(
            pool.values()
        ), "complete_qrels" if protocol.qrels_complete else "known_qrels_pool"
    pool = {row.item_id: row.relevance for row in candidates if row.relevance is not None}
    return list(pool.values()), "candidate_pool"


def _ndcg(relevances: list[float], ideal_relevances: list[float], cutoff: int, gain: str) -> float:
    # Integral floats represent exact integers. Normalize only these local
    # gain inputs so mixing them with a larger int does not round that int.
    relevances = [
        int(rel) if isinstance(rel, float) and rel.is_integer() else rel
        for rel in relevances
    ]
    ideal_relevances = [
        int(rel) if isinstance(rel, float) and rel.is_integer() else rel
        for rel in ideal_relevances
    ]
    # Scaling every gain by the same positive factor preserves NDCG and avoids
    # overflow for very large but finite labels (including exponential gain).
    largest = max(ideal_relevances + relevances, default=0.0)
    if largest == 0:
        return 0.0
    if gain == "linear":

        def gains(rel: float) -> float:
            return rel / largest
    elif largest < 512:
        # expm1(x) / x approaches 1 at zero. Take the relevance ratio first:
        # multiplying subnormal relevance by log(2) can otherwise round two
        # distinct grades to the same gain before their ratio is calculated.
        log_two = math.log(2)

        def expm1_ratio(value: float) -> float:
            return math.expm1(value) / value if value else 1.0

        denominator = expm1_ratio(largest * log_two)

        def gains(rel: float) -> float:
            return (rel / largest) * (expm1_ratio(rel * log_two) / denominator)
    else:
        baseline = 2.0 ** (-largest)

        def gains(rel: float) -> float:
            if 0 < rel < 1:
                if largest > 1075:
                    # Each such scaled gain is below half the minimum subnormal.
                    return 0.0
                # Subtracting a large grade first can erase a small positive
                # grade. Retain it before applying the full power-of-two scale.
                whole = math.floor(largest)
                scaled = math.expm1(rel * math.log(2)) * 2.0 ** (whole - largest)
                return math.ldexp(scaled, -whole)
            return max(0.0, 2.0 ** (rel - largest) - baseline)

    dcg = math.fsum(
        gains(rel) / math.log2(index + 2) for index, rel in enumerate(relevances[:cutoff])
    )
    ideal = sorted(ideal_relevances, reverse=True)[:cutoff]
    idcg = math.fsum(gains(rel) / math.log2(index + 2) for index, rel in enumerate(ideal))
    return dcg / idcg if idcg > 0 else 0.0


def _evaluate_rankings(
    rankings: dict[str, list[Row]], protocol: Protocol, qrels: Qrels | None
) -> dict:
    observations: dict[str, list[float]] = {}
    eligible_queries: dict[str, list[str]] = {}
    references: dict[str, set[str]] = {}
    reasons: dict[str, dict[str, int]] = {}
    for cutoff in protocol.cutoffs:
        for prefix in ("mrr", "ndcg", "recall"):
            key = f"{prefix}@{cutoff}"
            observations[key] = []
            eligible_queries[key] = []
            references[key] = set()
            reasons[key] = defaultdict(int)
    for query_id, candidates in rankings.items():
        missing_qrels_query = protocol.qrels_complete and (qrels is None or query_id not in qrels)
        pool, ndcg_reference = _reference_pool(query_id, candidates, protocol, qrels)
        all_known = all(row.relevance is not None for row in candidates)
        for cutoff in protocol.cutoffs:
            top = candidates[:cutoff]
            mrr_key, ndcg_key, recall_key = (
                f"{name}@{cutoff}" for name in ("mrr", "ndcg", "recall")
            )
            if missing_qrels_query:
                for key in (mrr_key, ndcg_key, recall_key):
                    reasons[key]["query_missing_from_complete_qrels"] += 1
                continue
            reciprocal = 0.0
            for rank, row in enumerate(top, 1):
                if row.relevance is None:
                    reciprocal = None
                    break
                if row.relevance > protocol.relevance_threshold:
                    reciprocal = 1.0 / rank
                    break
            if reciprocal is None:
                reasons[mrr_key]["unknown_top_k_judgment"] += 1
            else:
                observations[mrr_key].append(reciprocal)
                eligible_queries[mrr_key].append(query_id)
                references[mrr_key].add("submitted_candidates")
            if not all_known:
                reasons[ndcg_key]["unknown_candidate_judgment"] += 1
            else:
                observations[ndcg_key].append(
                    _ndcg([r.relevance for r in candidates], pool, cutoff, protocol.gain)
                )
                eligible_queries[ndcg_key].append(query_id)
                references[ndcg_key].add(ndcg_reference)
            if not protocol.qrels_complete or qrels is None:
                reasons[recall_key]["complete_qrels_not_declared"] += 1
            else:
                total_relevant = sum(
                    rel > protocol.relevance_threshold for rel in qrels[query_id].values()
                )
                if total_relevant == 0:
                    reasons[recall_key]["no_relevant_items_in_qrels"] += 1
                else:
                    # A set also makes the diagnostic preserve-rows calculation
                    # incapable of counting the same relevant item twice.
                    retrieved = {
                        r.item_id
                        for r in top
                        if r.relevance is not None and r.relevance > protocol.relevance_threshold
                    }
                    observations[recall_key].append(len(retrieved) / total_relevant)
                    eligible_queries[recall_key].append(query_id)
                    references[recall_key].add("complete_qrels")
    result = {}
    total = len(rankings)
    qrels_only = sorted(set(qrels or {}) - set(rankings))
    for key, values in observations.items():
        reference = (
            next(iter(references[key]))
            if len(references[key]) == 1
            else "mixed"
            if references[key]
            else "unavailable"
        )
        restricted_ndcg = key.startswith("ndcg") and reference != "complete_qrels"
        status = (
            "not_checked"
            if not values
            else "partial"
            if len(values) != total
            or restricted_ndcg
            or protocol.unjudged == "nonrelevant"
            or qrels_only
            else "ok"
        )
        result[key] = {
            "value": math.fsum(values) / len(values) if values else None,
            "status": status,
            "evaluated_queries": len(values),
            "total_queries": total,
            "excluded_queries": total - len(values),
            "eligible_query_ids": sorted(eligible_queries[key]),
            "excluded_query_ids": sorted(set(rankings) - set(eligible_queries[key])),
            "query_universe": "submitted_prediction_queries",
            "qrels_only_queries": len(qrels_only),
            "reference": reference,
            "exclusion_reasons": dict(reasons[key]),
            "reason": "No eligible queries under the declared judgment policy."
            if not values
            else "Some qrels queries have no predictions; averages cover only submitted prediction queries."
            if qrels_only
            else "NDCG uses a limited reference pool; this is not full-corpus NDCG."
            if restricted_ndcg
            else "Macro average over eligible queries.",
        }
        if key.startswith("mrr@"):
            result[key]["eligibility_rule"] = MRR_ELIGIBILITY_RULE
    return result


def evaluate_metrics(
    rows: Iterable[Row],
    protocol: Protocol,
    qrels: Qrels | None = None,
    *,
    tie_policy: str | None = None,
    duplicate_policy: str | None = None,
) -> dict:
    """Return macro metrics and coverage, never silently treating unknowns as 0.

    ``duplicate_policy='preserve_rows'`` is a diagnostic counterfactual only:
    repeated rows do not constitute a valid ranking of distinct documents.
    """
    checked = validate_inputs(rows, protocol, qrels)
    resolved = resolve_rows(checked, protocol, qrels)
    policy = protocol.duplicate_policy if duplicate_policy is None else duplicate_policy
    if policy == "max_score":
        resolved = deduplicate_rows(resolved)
    elif policy != "preserve_rows":
        raise ValueError("duplicate_policy must be 'max_score' or diagnostic 'preserve_rows'")
    rankings = {
        query_id: rank_rows(group, protocol.tie_policy if tie_policy is None else tie_policy)
        for query_id, group in group_rows(resolved).items()
    }
    return _evaluate_rankings(rankings, protocol, qrels)


def metric_deltas(left: dict, right: dict) -> dict:
    """Subtract aggregates only with matching eligibility sets, rules and pools."""
    result = {}
    for key in left.keys() & right.keys():
        a, b = left[key], right[key]
        if (
            a["value"] is not None
            and b["value"] is not None
            and a["eligible_query_ids"] == b["eligible_query_ids"]
            and a["reference"] == b["reference"]
            and (
                not key.startswith("mrr@")
                or (
                    isinstance(a.get("eligibility_rule"), str)
                    and bool(a["eligibility_rule"].strip())
                    and a["eligibility_rule"] == b.get("eligibility_rule")
                )
            )
        ):
            result[key] = {
                "delta": b["value"] - a["value"],
                "status": "checked",
                "evaluated_queries": a["evaluated_queries"],
            }
        else:
            result[key] = {
                "delta": None,
                "status": "not_checked",
                "reason": "Metric availability, eligible query sets, eligibility rules, or reference pools differ.",
            }
    return dict(sorted(result.items()))
