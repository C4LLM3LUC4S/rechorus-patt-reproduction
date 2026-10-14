"""Self-contained, escaped HTML reports and careful report file writing."""

from __future__ import annotations

import html
import json
import math
import os
from pathlib import Path
import tempfile
from typing import Any, Mapping

EVIDENCE_LIMIT = 20
TABLE_LIMIT = 60


def _text(value: Any) -> str:
    if value is None:
        return "Not available"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, float):
        return f"{value:.6g}" if math.isfinite(value) else "Not finite"
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
    return f'<div class="table-wrap"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>{note}'


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


def _metrics(value: Any) -> str:
    if isinstance(value, Mapping):
        records = []
        for name, metric in value.items():
            if isinstance(metric, Mapping):
                visible = {
                    key: metric[key]
                    for key in (
                        "value",
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
        return note + _table(records)
    return _content(value)


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
    sections: list[str] = []
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
        ("pairs", "Pairwise comparability"),
        ("tie_analysis", "Tie sensitivity"),
        ("duplicates", "Duplicate sensitivity"),
        ("negative_controls", "Negative controls"),
        ("checks", "Check coverage"),
        ("limitations", "Coverage and limitations"),
        ("provenance", "Reproducibility metadata"),
    ):
        if key in report and report[key]:
            rendered = _metrics(report[key]) if key == "metrics" else _diagnostics(report[key])
            sections.append(f'<section id="{key}"><h2>{title}</h2>{rendered}</section>')
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
        cards.append(
            f'<article class="finding {severity}">{badge}{state}<h3>{_esc(title)}</h3><p>{_esc(message)}</p><p class="code">{_esc(code)}</p>{scope}{details}</article>'
        )
    findings_html = (
        "".join(cards)
        or '<div class="empty"><h3>No findings were reported.</h3><p>This means the configured checks found no issues in the supplied data. It does not establish data provenance, relevance quality, or absence of leakage.</p></div>'
    )
    sections.insert(
        0,
        f'<section id="findings"><h2>Findings <span class="count">{len(findings)}</span></h2><p class="muted">A warning identifies a condition to investigate; it does not by itself prove an invalid evaluation.</p>{findings_html}</section>',
    )
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
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:16px/1.6 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}}a{{color:var(--accent);text-underline-offset:3px}}a:focus-visible,summary:focus-visible{{outline:3px solid #dc8400;outline-offset:4px}}.skip{{position:absolute;top:-70px;left:16px;padding:10px;background:white}}.skip:focus{{top:10px;z-index:1}}header{{background:#102c40;color:white;padding:44px max(24px,calc((100vw - 1080px)/2)) 34px}}.eyebrow{{font-size:12px;letter-spacing:.14em;text-transform:uppercase;color:#9ed5d2}}h1{{font-size:clamp(30px,5vw,44px);line-height:1.15;margin:10px 0}}header p{{color:#ccdae5;margin:10px 0}}nav{{display:flex;flex-wrap:wrap;gap:20px;margin-top:20px}}nav a{{color:#c1eee8}}main{{max-width:1128px;margin:auto;padding:24px}}.stats{{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin-bottom:22px}}.stat{{background:white;border:1px solid var(--line);border-top:4px solid var(--accent);padding:16px 20px;border-radius:8px}}.stat.error{{border-top-color:var(--error)}}.stat.warning{{border-top-color:#bd790e}}.stat strong{{display:block;font-size:30px;line-height:1.1}}.stat span{{color:var(--muted)}}section{{background:var(--paper);border:1px solid var(--line);border-radius:10px;margin:0 0 22px;padding:24px}}h2{{font-size:22px;margin:0 0 12px;line-height:1.3}}h3{{font-size:18px;line-height:1.4;margin:10px 0}}p{{margin:10px 0}}.muted,.code,.status{{color:var(--muted)}}.code{{font:12px/1.4 ui-monospace,SFMono-Regular,Consolas,monospace;overflow-wrap:anywhere}}.finding{{border:1px solid var(--line);border-left:4px solid var(--accent);border-radius:6px;margin-top:16px;padding:18px}}.finding.error{{border-left-color:var(--error)}}.finding.warning{{border-left-color:#bd790e}}.badge{{display:inline-block;padding:2px 8px;font-size:11px;font-weight:750;letter-spacing:.06em;border-radius:4px;background:#e6f3f2;color:#0b5559}}.badge.error{{background:#fce9e9;color:var(--error)}}.badge.warning{{background:#fff1cf;color:var(--warning)}}.status{{font-size:12px;margin-left:10px}}.count{{font-size:14px;color:var(--muted)}}details{{margin-top:14px;border-top:1px solid var(--line);padding-top:12px}}summary{{cursor:pointer;font-weight:600;color:var(--accent);padding:4px 0}}.table-wrap{{overflow-x:auto;margin-top:14px}}table{{width:100%;border-collapse:collapse;font-size:14px;text-align:left}}th{{background:#f2f6f9;font-weight:650}}th,td{{padding:10px 12px;border-bottom:1px solid var(--line);vertical-align:top;overflow-wrap:anywhere;min-width:100px;max-width:520px}}td{{white-space:pre-wrap}}.boundary{{background:#f8f3e7;border-color:#e6d9b9}}.empty{{padding:14px;background:#f1f6f8;border-radius:6px}}footer{{max-width:1080px;margin:0 auto;padding:0 24px 30px;color:var(--muted);font-size:13px}}@media(max-width:600px){{header{{padding:30px 18px}}main{{padding:14px}}section{{padding:17px}}.stat{{padding:12px}}.stat strong{{font-size:25px}}.stat span{{font-size:12px}}.finding{{padding:13px}}nav{{gap:14px;font-size:14px}}}}@media print{{body{{background:white}}header{{background:white;color:var(--ink);padding:12px 0}}header p{{color:var(--muted)}}nav,.skip{{display:none}}main{{padding:0}}section,.finding{{break-inside:avoid}}details> *{{display:block}}footer{{padding:0}}}}
</style></head><body><a class="skip" href="#main">Skip to report</a>
<header><div class="eyebrow">Ranking evaluation diagnostics</div><h1>RankProbe</h1><p>{subtitle}</p><nav aria-label="Report navigation"><a href="#findings">Findings</a><a href="#protocol">Protocol</a><a href="#boundaries">Interpretation limits</a><a href="report.json" download>Download JSON</a></nav></header>
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
    output.mkdir(parents=True, exist_ok=True)
    destinations = [output / "report.json", output / "report.html"]
    if not overwrite and any(path.exists() or path.is_symlink() for path in destinations):
        raise FileExistsError(
            f"Report already exists in {output}. Choose a new --out directory or pass --overwrite."
        )
    if any(path.is_dir() for path in destinations):
        raise IsADirectoryError(
            "A report destination is a directory; choose another --out directory."
        )
    with tempfile.TemporaryDirectory(prefix=".rankprobe-", dir=output) as temporary:
        staging = Path(temporary)
        staged = [staging / path.name for path in destinations]
        for path, content in zip(staged, (json_text, html_text)):
            path.write_text(content, encoding="utf-8")
        backups: dict[Path, Path] = {}
        installed: list[Path] = []
        try:
            for destination in destinations:
                if destination.exists() or destination.is_symlink():
                    backup = staging / (destination.name + ".backup")
                    os.replace(destination, backup)
                    backups[destination] = backup
            for source, destination in zip(staged, destinations):
                os.replace(source, destination)
                installed.append(destination)
        except OSError:
            for destination in installed:
                destination.unlink(missing_ok=True)
            for destination, backup in backups.items():
                os.replace(backup, destination)
            raise
    return destinations[0], destinations[1]


# Kept as a discoverable name for library callers.
render_report = render_html
