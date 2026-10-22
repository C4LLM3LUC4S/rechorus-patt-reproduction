"""Self-contained, escaped HTML reports and careful report file writing."""

from __future__ import annotations

import html
import json
import math
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Mapping

EVIDENCE_LIMIT = 20
TABLE_LIMIT = 60

FINDING_NEXT_STEPS = {
    "query_coverage_mismatch": "Check the missing query IDs against the intended evaluation set. Restore omitted predictions if accidental; inspect the matched-pool results before interpreting an aggregate change.",
    "candidate_set_mismatch": "Inspect the query IDs and candidate differences; check whether selection changed intentionally. For reranking, export scores from the same actual candidate stage. For complete retrieval systems, evaluate the original runs under a separately justified retrieval protocol. Do not intersect results or invent missing scores or judgments to force a matched-pool delta.",
    "cross_run_label_mismatch": "Resolve the listed query-item judgment differences at their source. Rerun both exports with the same judgments before attributing a change to the model.",
    "unknown_judgments": "Inspect metric coverage and exclusion reasons. Obtain missing judgments where possible; do not select a zero assumption just to make a metric available.",
    "explicit_unjudged_qrels": "Review the listed unjudged pairs against the judgment source. Keep them unknown unless an explicit convention is justified; these qrels do not support a completeness assertion.",
    "qrels_queries_without_predictions": "Check whether the listed queries should have predictions. Restore missing exports or state the narrower evaluation universe alongside the result.",
    "missing_qrels_queries": "Check query ID alignment and supply judgments for the missing queries. Reconsider the completeness assertion if those judgments do not exist.",
    "duplicate_candidates": "Trace the repeated pairs to the export or sampling step. Inspect duplicate sensitivity before deciding whether to fix the source or document intentional repetitions.",
    "score_ties": "Inspect tie bounds and the input-order probe. Check score precision and declare the same tie policy for all compared runs.",
    "constant_scores": "Check that the exported values are the intended model scores. Inspect the constant-score control; tie ordering alone can produce a nonzero metric.",
    "limited_reference_pool": "Report the displayed reference pool with NDCG. Supply independent, justified complete judgments before interpreting full Recall; a flag alone does not establish completeness.",
    "unjudged_assumed_nonrelevant": "Document why the zero assumption is justified and compare with unknown labels preserved. This assumption does not add source judgments.",
    "empty_run": "Check the export path and filters, then supply prediction rows before interpreting ranking metrics.",
}


def _float_text(value: float, *, signed: bool = False) -> str:
    compact = format(value, "+.6g" if signed else ".6g")
    # A rounded 1 (or any other whole number) can falsely suggest an exact
    # result. Use the shortest round-trippable spelling at that boundary.
    if math.isfinite(value) and float(compact).is_integer() and float(compact) != value:
        return format(value, "+") if signed else repr(value)
    return compact


def _text(value: Any) -> str:
    if value is None:
        return "Not available"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, float):
        return _float_text(value) if math.isfinite(value) else "Not finite"
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, default=str)
    return str(value)


def _esc(value: Any) -> str:
    return html.escape(_text(value), quote=True)


def _label(value: str) -> str:
    return value.replace("_", " ").strip().capitalize()


def _table(records: list[Mapping[str, Any]], limit: int = TABLE_LIMIT) -> str:
    if not records:
        return '<p class="muted">No rows to display.</p>'
    keys = list(dict.fromkeys(str(key) for row in records[:limit] for key in row))
    # Evidence remains downloadable as JSON; cap visual complexity in a browser.
    keys = keys[:12]
    head = "".join(f'<th scope="col">{_esc(_label(key))}</th>' for key in keys)
    body = "".join(
        "<tr>" + "".join(f"<td>{_esc(row.get(key))}</td>" for key in keys) + "</tr>"
        for row in records[:limit]
    )
    note = (
        f'<p class="muted">Showing {min(len(records), limit)} of {len(records)} rows. '
        'See <a href="report.json">report.json</a> for the full stored evidence.</p>'
        if len(records) > limit
        else ""
    )
    return f'<div class="table-wrap" tabindex="0" role="region" aria-label="Scrollable data table"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>{note}'


def _content(value: Any, limit: int = TABLE_LIMIT) -> str:
    if isinstance(value, Mapping):
        rows = [{"field": _label(str(key)), "value": item} for key, item in value.items()]
        return _table(rows, limit)
    if isinstance(value, (list, tuple)):
        if not value:
            return '<p class="muted">No entries.</p>'
        if all(isinstance(item, Mapping) for item in value):
            return _table(list(value), limit)
        items = "".join(f"<li>{_esc(item)}</li>" for item in value[:limit])
        note = (
            f'<p class="muted">Showing {limit} of {len(value)} entries; full data is in report.json.</p>'
            if len(value) > limit
            else ""
        )
        return f"<ul>{items}</ul>{note}"
    return f"<p>{_esc(value)}</p>"


def _metrics(value: Any, json_path: str | None = None) -> str:
    if isinstance(value, Mapping):
        records = []
        for name, metric in value.items():
            if isinstance(metric, Mapping):
                visible = {
                    key: metric[key]
                    for key in (
                        "value",
                        "delta",
                        "min",
                        "max",
                        "width",
                        "status",
                        "evaluated_queries",
                        "total_queries",
                        "excluded_queries",
                        "reference",
                        "reason",
                    )
                    if key in metric
                }
                records.append({"metric": name, **visible})
            else:
                records.append({"metric": name, "value": metric})
        note = '<p class="muted">Status <strong>partial</strong> means limited coverage or a candidate-pool reference; <strong>not_checked</strong> means the data or protocol does not support this metric. A missing value is not zero.</p>'
        details = []
        for name, metric in list(value.items())[:TABLE_LIMIT]:
            if not isinstance(metric, Mapping):
                continue
            coverage = {
                key: metric[key]
                for key in (
                    "eligibility_rule",
                    "query_universe",
                    "qrels_only_queries",
                    "exclusion_reasons",
                    "eligible_query_ids",
                    "excluded_query_ids",
                )
                if key in metric
            }
            if coverage:
                location = (
                    f'<p class="code">JSON: {_esc(json_path)}[{_esc(json.dumps(str(name)))}]</p>'
                    if json_path
                    else ""
                )
                details.append(
                    f'<details><summary>{_esc(name)}: coverage details</summary>{location}{_diagnostics(coverage, EVIDENCE_LIMIT)}</details>'
                )
        return note + _table(records) + "".join(details)
    return _content(value)


def _partial_perfect_context(value: Any) -> str:
    if not isinstance(value, Mapping):
        return ""
    notes = []
    for name, metric in list(value.items())[:TABLE_LIMIT]:
        if not (
            isinstance(name, str)
            and re.fullmatch(r"(?:mrr|ndcg|recall)@[1-9][0-9]*", name)
            and isinstance(metric, Mapping)
        ):
            continue
        score = metric.get("value")
        evaluated, total = metric.get("evaluated_queries"), metric.get("total_queries")
        if (
            metric.get("status") == "partial"
            and isinstance(score, (int, float))
            and not isinstance(score, bool)
            and score == 1
            and type(evaluated) is int
            and type(total) is int
            and 0 < evaluated < total
        ):
            query_word = "query" if evaluated == 1 else "queries"
            notes.append(
                f'<p class="muted">{_esc(name)} = 1 is the average over '
                f'{_esc(evaluated)} eligible {query_word} out of {_esc(total)} submitted queries. '
                'Excluded queries are not included in this average, so the value does not establish '
                'perfect results across all submitted queries. See coverage details for exclusion '
                'reasons.</p>'
            )
    return "".join(notes)


def _metric_cell(metric: Any, *, delta: bool = False) -> str:
    if not isinstance(metric, Mapping):
        return _text(metric)
    value = metric.get("delta" if delta else "value")
    if delta and isinstance(value, float) and math.isfinite(value):
        rendered = _float_text(value, signed=True)
    elif delta and type(value) is int:
        rendered = f"{value:+}"
    else:
        rendered = _text(value)
    lines = [rendered, f"status: {_text(metric.get('status'))}"]
    if "evaluated_queries" in metric:
        count = _text(metric["evaluated_queries"])
        total = f" / {_text(metric['total_queries'])}" if "total_queries" in metric else ""
        lines.append(f"metric-eligible queries: {count}{total}")
    for key in (("reference", "reason") if delta else ("reference",)):
        if key in metric:
            lines.append(f"{key}: {_text(metric[key])}")
    return "\n".join(lines)


def _comparison_reader(
    pair: Mapping[str, Any], sources: list[Mapping[str, Any]], protocol: Any,
) -> str:
    left, right = pair.get("left"), pair.get("right")
    coverage = pair.get("query_coverage", {})
    coverage = coverage if isinstance(coverage, Mapping) else {}
    matched = pair.get("matched_pool_comparison", {})
    matched = matched if isinstance(matched, Mapping) else {}
    candidates = pair.get("candidate_sets", {})
    candidates = candidates if isinstance(candidates, Mapping) else {}
    counts = (
        f'<p><strong>Submitted queries / <span lang="zh-CN">已提交查询</span>:</strong> '
        f'{_esc(left)}: {_esc(coverage.get("left_queries"))} · '
        f'{_esc(right)}: {_esc(coverage.get("right_queries"))}. '
        f'Common queries with the same candidate pools: {_esc(matched.get("query_count"))} '
        '(<span lang="zh-CN">候选项相同的共同查询</span>).</p>'
    )
    different_queries = any(
        isinstance(coverage.get(key), int) and coverage[key] > 0
        for key in ("left_only_count", "right_only_count")
    )
    if different_queries:
        action = (
            'Check the missing query IDs. Restore omitted predictions if accidental, then rerun. '
            '<span lang="zh-CN">两份结果覆盖的查询不同。核对缺少的查询；若为漏导出，恢复后重新比较。</span>'
        )
    elif isinstance(candidates.get("differing_queries"), int) and candidates["differing_queries"] > 0:
        action = (
            'Check the actual candidate stage before interpreting a matched change. '
            '<span lang="zh-CN">候选项不同；先核对实际候选来源，不要裁剪或补造分数来强行对齐。</span>'
        )
    else:
        action = (
            'Read the matched values with their metric-eligible counts and reference scope. '
            '<span lang="zh-CN">结合可算查询数及参考范围阅读对齐后结果；无法计算，不是零分。</span>'
        )

    def compact(metric: Any, *, delta: bool = False) -> str:
        if not isinstance(metric, Mapping):
            return _esc(None)
        value = metric.get("delta" if delta else "value")
        if delta and isinstance(value, float) and math.isfinite(value):
            text = _float_text(value, signed=True)
        elif delta and type(value) is int:
            text = f"{value:+}"
        else:
            text = _text(value)
        count = ""
        if "evaluated_queries" in metric:
            total = f' / {_esc(metric["total_queries"])}' if "total_queries" in metric else ""
            count = (
                f' <small>(eligible queries: {_esc(metric["evaluated_queries"])}{total}; '
                '<span lang="zh-CN">可算查询</span>)</small>'
            )
        scope = (
            ' <small>· limited scope / <span lang="zh-CN">范围有限</span></small>'
            if metric.get("status") == "partial" else ""
        )
        return f'<strong>{_esc(text)}</strong>{count}{scope}'

    cutoffs = protocol.get("cutoffs", ()) if isinstance(protocol, Mapping) else ()
    cutoffs = [k for k in cutoffs if type(k) is int and k > 0] if isinstance(cutoffs, (list, tuple)) else []
    previews = []
    if cutoffs:
        k = max(cutoffs)
        for metric in ("mrr", "ndcg"):
            name = f"{metric}@{k}"
            if not any(name in source for source in sources):
                continue
            references = []
            for source in sources[2:4]:
                value = source.get(name, {})
                references.append(value.get("reference") if isinstance(value, Mapping) else None)
            reference_labels = {
                "submitted_candidates": "submitted candidates / 已提交候选项",
                "candidate_pool": "supplied candidate pool / 当前候选池",
                "known_qrels_pool": "supplied judgments / 已提供的判断集合",
                "complete_qrels": "declared complete judgments / 已声明完整的判断集合",
                "unavailable": "unavailable / 无可用范围",
            }
            reference_text = [
                reference_labels.get(value, value) if isinstance(value, str) else value
                for value in references
            ]
            reference = (
                _esc(reference_text[0]) if references[0] == references[1] else
                f'{_esc(left)}: {_esc(reference_text[0])}; {_esc(right)}: {_esc(reference_text[1])}'
            )
            previews.append(
                f'<div class="metric-preview"><h4>{_esc(name)}</h4><dl>'
                '<dt>Submitted averages / <span lang="zh-CN">各自平均</span></dt>'
                f'<dd>{_esc(left)}: {compact(sources[0].get(name))}<br>'
                f'{_esc(right)}: {compact(sources[1].get(name))}</dd>'
                '<dt>Matched averages / <span lang="zh-CN">对齐后平均</span></dt>'
                f'<dd>{_esc(left)}: {compact(sources[2].get(name))}<br>'
                f'{_esc(right)}: {compact(sources[3].get(name))}</dd>'
                f'<dt>Difference / <span lang="zh-CN">差值</span> ({_esc(right)} − {_esc(left)})</dt>'
                f'<dd>{compact(sources[4].get(name), delta=True)}</dd></dl>'
                f'<p class="muted">Matched reference / <span lang="zh-CN">对齐比较参考范围</span>: {reference}.</p></div>'
            )
    preview = ""
    if previews:
        preview = (
            f'<p>Quick view at the largest requested cutoff, k={_esc(k)} '
            f'(<span lang="zh-CN">最大请求截断位置：只看前{_esc(k)}个结果</span>). '
            'All requested cutoffs remain in the full table below.</p>'
            f'<div class="metric-previews">{"".join(previews)}</div>'
        )
    return (
        '<aside class="comparison-reader" aria-label="Comparison reading guide">'
        '<h4>Check the comparison scope first / <span lang="zh-CN">先核对比较范围</span></h4>'
        f'{counts}<p>The common-query count is not the number eligible for every metric. '
        '<span lang="zh-CN">共同查询数不等于每个指标实际能计算的查询数。</span></p>'
        '<p>Submitted averages use each run\'s eligible queries; matched averages restrict to shared pools. '
        '<span lang="zh-CN">各自平均使用各自可算的查询；对齐后平均只比较共同候选范围。平均分更高，还不能据此认定改进。</span> '
        'Values apply only to the shown eligible queries and reference scope '
        '(<span lang="zh-CN">仅在上述查询及参考范围内有效</span>).</p>'
        '<p>Compare runs within one metric card; MRR and NDCG values are not directly comparable. '
        '<span lang="zh-CN">在同一张指标卡片内比较两个run；MRR与NDCG的分数不能直接比较大小。</span></p>'
        f'{preview}<p class="muted">MRR rewards an earlier first relevant result; NDCG rewards relevant results near the top. '
        '<span lang="zh-CN">MRR看首个相关结果的位置；NDCG看相关结果是否排在前面。Not available表示无法计算，不是零分。</span></p>'
        f'<p><strong>Next step / <span lang="zh-CN">下一步</span>:</strong> {action}</p></aside>'
    )


def _pairwise_results(report: Mapping[str, Any]) -> str:
    runs = report.get("runs", {})
    pairs = report.get("pairs", [])
    if not isinstance(runs, Mapping) or not runs or not isinstance(pairs, list):
        return _diagnostics(pairs)
    sections = []
    for index, pair in enumerate(pairs[:TABLE_LIMIT]):
        if not isinstance(pair, Mapping):
            sections.append(_diagnostics(pair))
            continue
        left, right = pair.get("left"), pair.get("right")
        left_run, right_run = runs.get(left, {}), runs.get(right, {})
        left_metrics = left_run.get("metrics", {}) if isinstance(left_run, Mapping) else {}
        right_metrics = right_run.get("metrics", {}) if isinstance(right_run, Mapping) else {}
        matched = pair.get("matched_pool_comparison", {})
        if not isinstance(matched, Mapping):
            matched = {}
        matched_left = matched.get("left_metrics", {})
        matched_right = matched.get("right_metrics", {})
        deltas = matched.get("delta_right_minus_left", {})
        sources = [left_metrics, right_metrics, matched_left, matched_right, deltas]
        sources = [source if isinstance(source, Mapping) else {} for source in sources]
        records = [
            {
                "metric": name,
                "submitted_left": _metric_cell(sources[0].get(name)),
                "submitted_right": _metric_cell(sources[1].get(name)),
                "matched_left": _metric_cell(sources[2].get(name)),
                "matched_right": _metric_cell(sources[3].get(name)),
                "matched_delta_right_minus_left": _metric_cell(sources[4].get(name), delta=True),
            }
            for name in dict.fromkeys(name for source in sources for name in source)
        ]
        detail = {key: item for key, item in pair.items() if key != "matched_pool_comparison"}
        detail["matched_pool_scope"] = {
            key: item for key, item in matched.items()
            if key not in {"left_metrics", "right_metrics", "delta_right_minus_left"}
        }
        coverage = "".join(
            f'<details><summary>Matched {_esc(side)}: metric coverage</summary>{_metrics(metrics, f"pairs[{index}].matched_pool_comparison.{side}_metrics")}</details>'
            for side, metrics in (("left", sources[2]), ("right", sources[3]))
        )
        sections.append(
            f'<article class="finding"><h3>{_esc(left)} → {_esc(right)}</h3>'
            f'{_comparison_reader(pair, sources, report.get("protocol"))}'
            '<details><summary>Full metric table and coverage / <span lang="zh-CN">完整指标与范围</span></summary>'
            f'<p>File-level pair status: <strong>{_esc(pair.get("status"))}</strong>. '
            f'Structurally matched queries: {_esc(matched.get("query_count"))}. '
            'The metric-eligible counts below may be smaller.</p>'
            '<p class="muted">Submitted averages can cover different queries. The matched delta applies only to its stated eligible queries and reference pool; it is not a full-run improvement or a provenance check. Positive delta means right minus left is positive.</p>'
            '<p class="muted">Scroll the table horizontally on narrow screens. Keyboard users can focus it and use the arrow keys.</p>'
            f'{_table(records)}<p class="code">JSON: pairs[{index}].matched_pool_comparison; submitted metrics: runs[run_name].metrics</p>'
            f'<details><summary>Pair scope and mismatches</summary>{_diagnostics(detail, EVIDENCE_LIMIT)}</details>{coverage}</details></article>'
        )
    if len(pairs) > TABLE_LIMIT:
        sections.append(f'<p class="muted">Showing {TABLE_LIMIT} of {len(pairs)} pairs. Full stored results are in report.json.</p>')
    return "".join(sections)


def _compared_runs(value: Any) -> str:
    if not isinstance(value, Mapping):
        return _diagnostics(value)
    sections = []
    for name, run in list(value.items())[:TABLE_LIMIT]:
        if not isinstance(run, Mapping) or not isinstance(run.get("audit"), Mapping):
            sections.append(
                f'<details><summary>{_esc(name)}: run diagnostics</summary>{_diagnostics(run)}</details>'
            )
            continue
        audit = run.get("audit", {})
        summary = audit.get("summary", {}) if isinstance(audit, Mapping) else {}
        remaining = {
            key: item for key, item in audit.items()
            if key not in {"metrics", "summary", "findings", "protocol"}
        } if isinstance(audit, Mapping) else {}
        sections.append(
            f'<details><summary>{_esc(name)}: submitted-run diagnostics</summary>'
            f'{_content(summary)}{_metrics(run.get("metrics", {}), f"runs[{json.dumps(str(name))}].metrics")}'
            f'<details><summary>Sensitivity and remaining diagnostics</summary>{_diagnostics(remaining)}</details></details>'
        )
    if len(value) > TABLE_LIMIT:
        sections.append(f'<p class="muted">Showing {TABLE_LIMIT} of {len(value)} runs. Full stored results are in report.json.</p>')
    return "".join(sections)


def _diagnostics(value: Any, limit: int = TABLE_LIMIT) -> str:
    if isinstance(value, (list, tuple)):
        if all(isinstance(item, Mapping) for item in value) and any(
            any(isinstance(child, (Mapping, list, tuple)) for child in item.values())
            for item in value
        ):
            entries = []
            for index, item in enumerate(value[:limit]):
                name = (
                    f"{item['left']} → {item['right']}"
                    if "left" in item and "right" in item
                    else f"Entry {index + 1}: query {item['query_id']}"
                    if isinstance(item.get("query_id"), str)
                    else f"Entry {index + 1}"
                )
                entries.append(
                    f"<details><summary>{_esc(name)}</summary>{_diagnostics(item, limit)}</details>"
                )
            if len(value) > limit:
                entries.append(
                    f'<p class="muted">Showing {limit} of {len(value)} entries. Full stored evidence is in report.json.</p>'
                )
            return "".join(entries)
        return _content(value, limit)
    if not isinstance(value, Mapping):
        return _content(value, limit)
    sections = []
    scalars = {
        key: item for key, item in value.items() if not isinstance(item, (Mapping, list, tuple))
    }
    if scalars:
        sections.append(_content(scalars, limit))
    for key, item in value.items():
        if isinstance(item, (Mapping, list, tuple)):
            if key == "files" and value.get("scheme") == "rankprobe-core-python-v1" and isinstance(item, Mapping):
                rendered = _table([
                    {"filename": name, "sha256": digest} for name, digest in item.items()
                ], limit)
            else:
                rendered = (
                    _metrics(item)
                    if key
                    in {"metric_bounds", "metrics", "original", "reversed", "deduplicated", "raw_rows"}
                    or str(key).endswith("_metrics")
                    or str(key).startswith("delta_")
                    else _diagnostics(item, limit)
                )
            sections.append(
                f"<details><summary>{_esc(_label(str(key)))}</summary>{rendered}</details>"
            )
    return "".join(sections)


def _findings(report: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    value = report.get("findings", [])
    return (
        [finding if isinstance(finding, Mapping) else {"message": finding} for finding in value]
        if isinstance(value, list)
        else []
    )


def _severity(finding: Mapping[str, Any]) -> str:
    value = str(finding.get("severity", finding.get("level", "info"))).lower()
    return value if value in {"error", "warning", "info"} else "info"


def render_html(report: Mapping[str, Any]) -> str:
    """Render an audit or comparison without requests, scripts, or unsafe markup."""
    findings = _findings(report)
    counts = {
        level: sum(_severity(item) == level for item in findings)
        for level in ("error", "warning", "info")
    }
    kind = str(report.get("report_type", report.get("kind", "audit")))
    run_name = report.get("run_name", report.get("name"))
    subtitle = (
        f"Run: {_esc(run_name)}" if run_name is not None else "Ranking evaluation diagnostics"
    )
    summary = report.get("summary", {})
    protocol = report.get("protocol", {})
    protocol_navigation = '<a href="#protocol">Protocol</a>' if protocol else ""
    sections: list[str] = []
    comparison_section = None
    result_navigation = ""
    if summary:
        sections.append(f'<section id="summary"><h2>Run summary</h2>{_content(summary)}</section>')
    if protocol:
        sections.append(
            f'<section id="protocol"><h2>Evaluation protocol</h2><p class="muted">These choices define what the reported metrics mean. Compare runs only under compatible protocols.</p>{_content(protocol)}</section>'
        )
    if isinstance(summary, Mapping) and summary.get("unknown_candidates", 0):
        sections.insert(
            0,
            f'<section class="boundary"><h2>Relevance coverage is incomplete</h2><p>{_esc(summary["unknown_candidates"])} supplied candidates have no known relevance judgment. Check each metric\'s coverage, reference and stated treatment of unjudged candidates before interpreting results.</p></section>',
        )
    for key, title in (
        ("metrics", "Recomputed metrics"),
        ("comparison", "Run comparison"),
        ("comparisons", "Run comparisons"),
        ("runs", "Compared runs"),
        ("pairs", "Comparison results"),
        ("tie_analysis", "Tie sensitivity"),
        ("duplicates", "Duplicate sensitivity"),
        ("negative_controls", "Negative controls"),
        ("checks", "Check coverage"),
        ("limitations", "Coverage and limitations"),
        ("provenance", "Reproducibility metadata"),
    ):
        if key in report and report[key]:
            if key == "metrics":
                rendered = _partial_perfect_context(report[key]) + _metrics(report[key], "metrics")
            elif key == "pairs":
                rendered = _pairwise_results(report)
            elif key == "runs":
                rendered = _compared_runs(report[key])
            else:
                rendered = _diagnostics(report[key])
            section = f'<section id="{key}"><h2>{title}</h2>{rendered}</section>'
            if key == "pairs":
                comparison_section = section
                result_navigation = '<a href="#pairs">Comparison results</a>'
                if report.get("runs"):
                    result_navigation += '<a href="#runs">Run diagnostics</a>'
            else:
                sections.append(section)
    cards: list[str] = []
    for index, finding in enumerate(findings):
        severity = _severity(finding)
        code = finding.get("code", finding.get("id", f"finding-{index + 1}"))
        title = finding.get("title", _label(str(code)))
        message = finding.get("message", finding.get("description", ""))
        status = finding.get("status")
        badge = f'<span class="badge {severity}">{severity.upper()}</span>'
        state = f'<span class="status">{_esc(status)}</span>' if status is not None else ""
        evidence = finding.get("evidence", finding.get("examples"))
        details = (
            f"<details><summary>Inspect evidence</summary>{_diagnostics(evidence, EVIDENCE_LIMIT)}</details>"
            if evidence is not None
            else ""
        )
        scope = (
            f'<p class="muted">Scope: {_esc(finding["scope"])}</p>' if "scope" in finding else ""
        )
        next_step = FINDING_NEXT_STEPS.get(str(code))
        targets = (
            ("pairs", "Comparison results"),
            ("runs", "Run diagnostics"),
        ) if report.get("pairs") else (
            ("tie_analysis", "Tie sensitivity") if str(code) in {"score_ties", "constant_scores"}
            else ("duplicates", "Duplicate sensitivity") if str(code) == "duplicate_candidates"
            else ("metrics", "Metric coverage"),
        )
        related = next(
            ((key, label) for key, label in targets if report.get(key)), None
        )
        related_link = (
            f' <a href="#{related[0]}">{related[1]}</a>.' if related and next_step else ""
        )
        action = (
            f'<p><strong>Next step:</strong> {_esc(next_step)}{related_link}</p>' if next_step else ""
        )
        location = f'<p class="code">JSON: findings[{index}].evidence</p>'
        cards.append(
            f'<article class="finding {severity}">{badge}{state}<h3>{_esc(title)}</h3><p>{_esc(message)}</p><p class="code">{_esc(code)}</p>{scope}{action}{location}{details}</article>'
        )
    findings_html = (
        "".join(cards)
        or '<div class="empty"><h3>No findings were reported.</h3><p>This means the configured checks found no issues in the supplied data. It does not establish data provenance, relevance quality, or absence of leakage.</p></div>'
    )
    sections.insert(
        0,
        f'<section id="findings"><h2>Findings <span class="count">{len(findings)}</span></h2><p class="muted">A warning identifies a condition to investigate; it does not by itself prove an invalid evaluation.</p>{findings_html}</section>',
    )
    if comparison_section:
        sections.insert(0, comparison_section)
    if report.get("demo_note"):
        sections.insert(
            0,
            f'<section class="boundary"><h2>Synthetic demonstration</h2><p>{_esc(report["demo_note"])}</p></section>',
        )
    boundaries = (
        "RankProbe inspects the supplied predictions and optional judgments. It cannot establish that labels are correct, "
        "the candidate pool represents production traffic, or training data is free of leakage. Missing judgments are not "
        "evidence of non-relevance unless the stated protocol explicitly makes that assumption. Metrics and findings "
        "describe this supplied run; they are not a certificate of model quality."
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src data:; base-uri 'none'; form-action 'none'">
<meta name="color-scheme" content="light"><title>RankProbe — {_esc(kind)} report</title>
<style>
:root{{--ink:#14283b;--muted:#536779;--line:#d8e2eb;--paper:#fff;--bg:#eef3f7;--accent:#075c65;--error:#a52c32;--warning:#825000}}
.table-wrap:focus-visible{{outline:3px solid #dc8400;outline-offset:4px}}
.comparison-reader{{padding:16px;background:#f2f7fa;border:1px solid var(--line);border-radius:6px}}.comparison-reader h4{{margin:0 0 10px;font-size:17px}}.metric-previews{{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,280px),1fr));gap:14px}}.metric-preview{{padding:14px;background:white;border:1px solid var(--line);border-radius:6px;min-width:0;overflow-wrap:anywhere}}.metric-preview h4{{font-family:ui-monospace,monospace}}.metric-preview dl{{margin:0}}.metric-preview dt{{font-weight:600;margin-top:10px}}.metric-preview dd{{margin:3px 0 0}}.metric-preview small{{color:var(--muted)}}
*{{box-sizing:border-box}}h1,h2,h3,p,summary,li{{overflow-wrap:anywhere}}body{{margin:0;background:var(--bg);color:var(--ink);font:16px/1.6 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}}a{{color:var(--accent);text-underline-offset:3px}}a:focus-visible,summary:focus-visible{{outline:3px solid #dc8400;outline-offset:4px}}.skip{{position:absolute;top:-70px;left:16px;padding:10px;background:white}}.skip:focus{{top:10px;z-index:1}}header{{background:#102c40;color:white;padding:44px max(24px,calc((100vw - 1080px)/2)) 34px}}.eyebrow{{font-size:12px;letter-spacing:.14em;text-transform:uppercase;color:#9ed5d2}}h1{{font-size:clamp(30px,5vw,44px);line-height:1.15;margin:10px 0}}header p{{color:#ccdae5;margin:10px 0}}nav{{display:flex;flex-wrap:wrap;gap:20px;margin-top:20px}}nav a{{color:#c1eee8}}main{{max-width:1128px;margin:auto;padding:24px}}.stats{{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin-bottom:22px}}.stat{{background:white;border:1px solid var(--line);border-top:4px solid var(--accent);padding:16px 20px;border-radius:8px}}.stat.error{{border-top-color:var(--error)}}.stat.warning{{border-top-color:#bd790e}}.stat strong{{display:block;font-size:30px;line-height:1.1}}.stat span{{color:var(--muted)}}section{{background:var(--paper);border:1px solid var(--line);border-radius:10px;margin:0 0 22px;padding:24px}}h2{{font-size:22px;margin:0 0 12px;line-height:1.3}}h3{{font-size:18px;line-height:1.4;margin:10px 0}}p{{margin:10px 0}}.muted,.code,.status{{color:var(--muted)}}.code{{font:12px/1.4 ui-monospace,SFMono-Regular,Consolas,monospace;overflow-wrap:anywhere}}.finding{{border:1px solid var(--line);border-left:4px solid var(--accent);border-radius:6px;margin-top:16px;padding:18px}}.finding.error{{border-left-color:var(--error)}}.finding.warning{{border-left-color:#bd790e}}.badge{{display:inline-block;padding:2px 8px;font-size:11px;font-weight:750;letter-spacing:.06em;border-radius:4px;background:#e6f3f2;color:#0b5559}}.badge.error{{background:#fce9e9;color:var(--error)}}.badge.warning{{background:#fff1cf;color:var(--warning)}}.status{{font-size:12px;margin-left:10px}}.count{{font-size:14px;color:var(--muted)}}details{{margin-top:14px;border-top:1px solid var(--line);padding-top:12px}}summary{{cursor:pointer;font-weight:600;color:var(--accent);padding:4px 0}}.table-wrap{{overflow-x:auto;margin-top:14px}}table{{width:100%;border-collapse:collapse;font-size:14px;text-align:left}}th{{background:#f2f6f9;font-weight:650}}th,td{{padding:10px 12px;border-bottom:1px solid var(--line);vertical-align:top;overflow-wrap:anywhere;min-width:100px;max-width:520px}}td{{white-space:pre-wrap}}.boundary{{background:#f8f3e7;border-color:#e6d9b9}}.empty{{padding:14px;background:#f1f6f8;border-radius:6px}}footer{{max-width:1080px;margin:0 auto;padding:0 24px 30px;color:var(--muted);font-size:13px}}@media(max-width:600px){{header{{padding:30px 18px}}main{{padding:14px}}section{{padding:17px}}.stat{{padding:12px}}.stat strong{{font-size:25px}}.stat span{{font-size:12px}}.finding{{padding:13px}}nav{{gap:14px;font-size:14px}}}}@media print{{body{{background:white}}header{{background:white;color:var(--ink);padding:12px 0}}header p{{color:var(--muted)}}nav,.skip{{display:none}}main{{padding:0}}section,.finding{{break-inside:avoid}}details> *{{display:block}}footer{{padding:0}}}}
</style></head><body><a class="skip" href="#main">Skip to report</a>
<header><div class="eyebrow">Ranking evaluation diagnostics</div><h1>RankProbe</h1><p>{subtitle}</p><nav aria-label="Report navigation">{result_navigation}<a href="#findings">Findings</a>{protocol_navigation}<a href="#boundaries">Interpretation limits</a><a href="report.json" download>Download JSON</a></nav></header>
<main id="main"><div class="stats" aria-label="Finding counts"><div class="stat error"><strong>{counts["error"]}</strong><span>Error findings</span></div><div class="stat warning"><strong>{counts["warning"]}</strong><span>Warnings</span></div><div class="stat"><strong>{counts["info"]}</strong><span>Informational findings</span></div></div>
{"".join(sections)}<section id="boundaries" class="boundary"><h2>Interpretation limits</h2><p>{boundaries}</p><p>Evidence tables show at most {EVIDENCE_LIMIT} entries per finding. The downloadable JSON contains the evidence stored by the audit engine; engine-level sampling limits may also apply.</p></section></main>
<footer>RankProbe · Offline report · Schema {_esc(report.get("schema_version", "unspecified"))}. No external resources are requested by this document.</footer></body></html>"""


def write_report(
    report: Mapping[str, Any], output_dir: str | Path, *, overwrite: bool = False
) -> tuple[Path, Path]:
    """Stage both outputs before replacement; retain unrelated files and roll back failures."""
    output = Path(output_dir)
    json_text = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    html_text = render_html(report)
    if (output.exists() or output.is_symlink()) and not output.is_dir():
        raise NotADirectoryError(
            f"--out must name a directory; {output} is a file or unresolved link. "
            "Choose another --out directory."
        )
    output.mkdir(parents=True, exist_ok=True)
    destinations = [output / "report.json", output / "report.html"]
    exists_message = (
        f"Report already exists in {output}. Choose a new --out directory or pass --overwrite."
    )
    if any(path.is_dir() for path in destinations):
        raise IsADirectoryError(
            "A report destination is a directory; choose another --out directory."
        )
    if not overwrite and any(path.exists() or path.is_symlink() for path in destinations):
        raise FileExistsError(exists_message)
    with tempfile.TemporaryDirectory(prefix=".rankprobe-", dir=output) as temporary:
        staging = Path(temporary)
        staged = [staging / path.name for path in destinations]
        for path, content in zip(staged, (json_text, html_text)):
            path.write_text(content, encoding="utf-8")
        backups: dict[Path, Path] = {}
        installed: list[Path] = []
        reserved: list[Path] = []
        try:
            if overwrite:
                for destination in destinations:
                    if destination.exists() or destination.is_symlink():
                        backup = staging / (destination.name + ".backup")
                        os.replace(destination, backup)
                        backups[destination] = backup
            else:
                # The earlier existence check gives a useful fast error, but
                # another writer can pass it too. Reserve both final names
                # atomically before replacing either staged report.
                for destination in destinations:
                    try:
                        descriptor = os.open(
                            destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
                        )
                    except FileExistsError as exc:
                        raise FileExistsError(exists_message) from exc
                    reserved.append(destination)
                    os.close(descriptor)
            for source, destination in zip(staged, destinations):
                os.replace(source, destination)
                installed.append(destination)
        except OSError:
            for destination in installed:
                destination.unlink(missing_ok=True)
            for destination in reserved:
                destination.unlink(missing_ok=True)
            for destination, backup in backups.items():
                os.replace(backup, destination)
            raise
    return destinations[0], destinations[1]


# Kept as a discoverable name for library callers.
render_report = render_html
