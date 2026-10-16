import hashlib
import json

from rankprobe.cli import main


def test_trec_audit_uses_scores_and_records_format(tmp_path):
    run = tmp_path / "scores.txt"
    qrels = tmp_path / "judgments.txt"
    run.write_text("001 Q0 b 1 0.1 demo\n001 Q0 a 99 0.9 demo\n", encoding="utf-8")
    qrels.write_text("001 0 a 1\n001 0 b 0\n", encoding="utf-8")
    out = tmp_path / "audit"
    assert main([
        "audit", str(run), "--input-format", "trec", "--qrels", str(qrels),
        "--qrels-format", "trec", "--qrels-complete", "--cutoffs", "1", "--out", str(out),
    ]) == 0
    report = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert report["metrics"]["mrr@1"]["value"] == 1
    assert report["metrics"]["recall@1"]["value"] == 1
    sources = report["provenance"]["sources"]
    assert {s["input_format"] for s in sources} == {"trec"}
    prediction = next(s for s in sources if s["role"] == "predictions")
    assert prediction["sha256"] == hashlib.sha256(run.read_bytes()).hexdigest()
    assert "rank" in prediction["ordering_note"]


def test_trec_unknown_is_excluded_and_complete_claim_rejected(tmp_path, capsys):
    run, qrels = tmp_path / "scores.run", tmp_path / "judgments.qrels"
    run.write_text("q Q0 x 0 2 demo\nq Q0 y 1 1 demo\n", encoding="utf-8")
    qrels.write_text("q 0 x -1\nq 0 y 1\n", encoding="utf-8")
    out = tmp_path / "partial"
    arguments = ["audit", str(run), "--qrels", str(qrels), "--cutoffs", "2", "--out"]
    assert main([*arguments, str(out)]) == 0
    report = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert report["metrics"]["mrr@2"]["value"] is None
    assert report["metrics"]["recall@2"]["value"] is None
    assert report["summary"]["explicit_unjudged_qrels"] == 1
    rejected = tmp_path / "rejected"
    assert main([*arguments, str(rejected), "--qrels-complete"]) == 2
    assert not rejected.exists()
    assert "unjudged" in capsys.readouterr().err.lower()


def test_compare_auto_accepts_mixed_csv_and_trec(tmp_path):
    csv = tmp_path / "left.csv"
    trec = tmp_path / "right.run"
    qrels = tmp_path / "labels.qrels"
    csv.write_text("query_id,item_id,score\nq,a,3\nq,b,2\n", encoding="utf-8")
    trec.write_text("q Q0 a 1 3 run\nq Q0 b 2 2 run\n", encoding="utf-8")
    qrels.write_text("q 0 a 1\nq 0 b 0\n", encoding="utf-8")
    out = tmp_path / "compare"
    assert main([
        "compare", "--run", f"csv={csv}", "--run", f"trec={trec}",
        "--qrels", str(qrels), "--out", str(out),
    ]) == 0
    report = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert report["pairs"][0]["status"] == "comparable"
    sources = {s.get("run_name"): s for s in report["provenance"]["sources"]}
    assert sources["csv"]["input_format"] == "csv"
    assert sources["trec"]["input_format"] == "trec"


def test_ambiguous_text_requires_explicit_format(tmp_path, capsys):
    run = tmp_path / "scores.txt"
    run.write_text("q Q0 a 1 3 run\n", encoding="utf-8")
    out = tmp_path / "bad"
    assert main(["audit", str(run), "--out", str(out)]) == 2
    assert not out.exists()
    assert "trec" in capsys.readouterr().err


def test_explicit_format_overrides_extension_in_provenance(tmp_path):
    run = tmp_path / "scores.run"
    run.write_text("query_id,item_id,score,relevance\nq,a,1,1\n", encoding="utf-8")
    out = tmp_path / "audit"
    assert main([
        "audit", str(run), "--input-format", "csv", "--out", str(out),
    ]) == 0
    report = json.loads((out / "report.json").read_text(encoding="utf-8"))
    source = report["provenance"]["sources"][0]
    assert source["input_format"] == "csv"
    assert "ordering_note" not in source


def test_format_without_judgments_is_rejected(tmp_path, capsys):
    assert main(["demo", "--qrels-format", "trec", "--out", str(tmp_path / "bad")]) == 2
    assert "requires --qrels" in capsys.readouterr().err
