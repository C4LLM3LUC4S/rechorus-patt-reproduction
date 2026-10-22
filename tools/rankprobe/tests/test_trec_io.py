import pytest

from rankprobe.io import InputError, read_predictions, read_qrels
from rankprobe.metrics import rank_rows
from rankprobe.model import Row


def test_run_bom_blank_lines_comments_string_ids_and_scientific_scores(tmp_path):
    path = tmp_path / "retrieval.run"
    path.write_text(
        "# synthetic example\n\n001\tQ0\t文档-01\t0\t-2.5e-2\tfirst-tag\n"
        "001 ignored 文档-02 04 1E+3 another_tag\n",
        encoding="utf-8-sig",
    )
    before = path.read_bytes()
    assert read_predictions(path) == [
        Row("001", "文档-01", -0.025),
        Row("001", "文档-02", 1000),
    ]
    assert path.read_bytes() == before


def test_rank_is_advisory_and_input_ties_follow_file_order(tmp_path):
    path = tmp_path / "ranking.trec"
    path.write_text(
        "q Q0 z 99 1 tag\nq Q0 a 2 1 tag\nq Q0 high 2 3 other\n", encoding="utf-8"
    )
    rows = read_predictions(path)
    assert [row.item_id for row in rows] == ["z", "a", "high"]
    assert [row.item_id for row in rank_rows(rows, "input")] == ["high", "z", "a"]
    assert [row.item_id for row in rank_rows(rows, "item_id")] == ["high", "a", "z"]


@pytest.mark.parametrize("suffix", [".txt", ".data", ""])
def test_trec_requires_explicit_format_for_ambiguous_extensions(tmp_path, suffix):
    path = tmp_path / f"retrieval{suffix}"
    path.write_text("q Q0 doc 1 2 tag\n", encoding="utf-8")
    with pytest.raises(InputError, match="format='trec'"):
        read_predictions(path)
    assert read_predictions(path, format="trec") == [Row("q", "doc", 2)]


@pytest.mark.parametrize(
    "body, reason",
    [
        ("q Q0 doc 1 2", "exactly 6"),
        ("q Q0 doc 1 2 tag extra", "exactly 6"),
        ("q Q0 doc -1 2 tag", "rank must"),
        ("q Q0 doc 1.0 2 tag", "rank must"),
        ("q Q0 doc 1e2 2 tag", "rank must"),
        ("q Q0 doc +1 2 tag", "rank must"),
        ("q Q0 doc ١ 2 tag", "rank must"),
        ("q Q0 doc 1 NaN tag", "score must"),
        ("q Q0 doc 1 inf tag", "score must"),
        ("q Q0 doc 1 1e309 tag", "score must"),
        ("q Q0 doc 1 not-a-score tag", "score must"),
        ("q Q0 doc\x00suffix 1 2 tag", "NUL"),
        (f"q Q0 {'a' * 4097} 1 2 tag", "4096-character"),
    ],
)
def test_bad_run_records_show_file_and_physical_line(tmp_path, body, reason):
    path = tmp_path / "bad.run"
    path.write_text(f"# comment\n\n{body}\n", encoding="utf-8")
    with pytest.raises(InputError, match=f"bad.run:3:.*{reason}"):
        read_predictions(path)


@pytest.mark.parametrize("body", ["", "\n \t\n", "# comments only\n  # more\n"])
def test_empty_run_rejected(tmp_path, body):
    path = tmp_path / "empty.run"
    path.write_text(body, encoding="utf-8")
    with pytest.raises(InputError, match="no prediction rows"):
        read_predictions(path)


def test_qrels_preserves_explicit_unknown_pairs_and_query_universe(tmp_path):
    path = tmp_path / "labels.qrels"
    path.write_text(
        "# graded judgments\n\n001 0 文档-01 -1\n001 unused 文档-02 2.5e0\n"
        "unjudged 0 unseen -1\nzero 0 doc 0\n",
        encoding="utf-8-sig",
    )
    assert read_qrels(path) == {
        "001": {"文档-01": None, "文档-02": 2.5},
        "unjudged": {"unseen": None},
        "zero": {"doc": 0.0},
    }


def test_all_unjudged_qrels_is_valid_nonempty_input(tmp_path):
    path = tmp_path / "all-unknown.qrels"
    path.write_text("q 0 x -1\nq 0 y -1\n", encoding="utf-8")
    assert read_qrels(path) == {"q": {"x": None, "y": None}}


@pytest.mark.parametrize(
    "body, reason",
    [
        ("q 0 doc", "exactly 4"),
        ("q 0 doc 1 extra", "exactly 4"),
        ("q 0 doc -2", "non-negative or -1"),
        ("q 0 doc -0.5", "non-negative or -1"),
        ("q 0 doc NaN", "finite number"),
        ("q 0 doc -inf", "finite number"),
        ("q 0 doc 1e309", "finite number"),
        ("q 0 doc no", "finite number"),
        ("q 0 doc\x00suffix 1", "NUL"),
    ],
)
def test_bad_qrels_records_show_file_and_physical_line(tmp_path, body, reason):
    path = tmp_path / "bad.qrels"
    path.write_text(f"\n# comment\n{body}\n", encoding="utf-8")
    with pytest.raises(InputError, match=f"bad.qrels:3:.*{reason}"):
        read_qrels(path)


@pytest.mark.parametrize("first, second", [("-1", "-1"), ("-1", "1"), ("1", "-1"), ("1", "1")])
def test_duplicate_qrels_pairs_rejected_including_unknown(tmp_path, first, second):
    path = tmp_path / "duplicate.qrels"
    path.write_text(f"q 0 doc {first}\nq another doc {second}\n", encoding="utf-8")
    with pytest.raises(InputError, match="duplicate.qrels:2:.*duplicate qrels entry"):
        read_qrels(path)


def test_qrels_txt_needs_explicit_format(tmp_path):
    path = tmp_path / "labels.txt"
    path.write_text("001 0 002 1\n", encoding="utf-8")
    with pytest.raises(InputError, match="format='trec'"):
        read_qrels(path)
    assert read_qrels(path, format="trec") == {"001": {"002": 1.0}}


@pytest.mark.parametrize("body", ["", "\n# only comments\n"])
def test_empty_qrels_rejected(tmp_path, body):
    path = tmp_path / "empty.qrels"
    path.write_text(body, encoding="utf-8")
    with pytest.raises(InputError, match="no qrels rows"):
        read_qrels(path)


def test_explicit_csv_and_jsonl_override_extensions_without_changing_contract(tmp_path):
    predictions = tmp_path / "predictions.txt"
    predictions.write_text("query_id,item_id,score\n001,002,1e2\n", encoding="utf-8")
    assert read_predictions(predictions, format="csv") == [Row("001", "002", 100)]
    qrels = tmp_path / "labels.txt"
    qrels.write_text('{"query_id":"001","item_id":"002","relevance":2}\n', encoding="utf-8")
    assert read_qrels(qrels, format="jsonl") == {"001": {"002": 2.0}}
    for grade in ["null", "-1"]:
        qrels.write_text(
            f'{{"query_id":"001","item_id":"002","relevance":{grade}}}\n', encoding="utf-8"
        )
        with pytest.raises(InputError, match="labels.txt:1:"):
            read_qrels(qrels, format="jsonl")


@pytest.mark.parametrize("loader", [read_predictions, read_qrels])
def test_invalid_explicit_format_and_unreadable_trec_file(tmp_path, loader):
    path = tmp_path / "missing.txt"
    with pytest.raises(InputError, match="format must"):
        loader(path, format="xml")
    with pytest.raises(InputError, match="cannot read input"):
        loader(path, format="trec")


@pytest.mark.parametrize("suffix", [".RUN", ".TREC"])
def test_run_extension_detection_case_insensitive(tmp_path, suffix):
    path = tmp_path / f"ranking{suffix}"
    path.write_text("q Q0 doc 1 2 tag\n", encoding="utf-8")
    assert read_predictions(path) == [Row("q", "doc", 2)]


def test_qrels_extension_detection_case_insensitive(tmp_path):
    path = tmp_path / "judgments.QRELS"
    path.write_text("q 0 doc 1\n", encoding="utf-8")
    assert read_qrels(path) == {"q": {"doc": 1.0}}
