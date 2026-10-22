from rankprobe import Protocol, Row, audit_run, compare_runs


def test_omitted_judged_query_does_not_silently_look_complete():
    report = audit_run(
        [Row("easy", "a", 1)],
        Protocol(cutoffs=(1,), qrels_complete=True),
        {"easy": {"a": 1}, "omitted": {"b": 1}},
    )
    assert report["summary"]["qrels_queries_without_predictions"] == 1
    assert report["summary"]["query_universe"] == "submitted_prediction_queries"
    warning = next(
        f for f in report["findings"] if f["code"] == "qrels_queries_without_predictions"
    )
    assert warning["evidence"]["query_ids"] == ["omitted"]
    for metric in report["metrics"].values():
        assert metric["value"] == 1.0
        assert metric["status"] == "partial"
        assert metric["qrels_only_queries"] == 1


def test_same_omission_in_two_runs_is_still_visible():
    report = compare_runs(
        {"a": [Row("easy", "a", 1)], "b": [Row("easy", "a", 2)]},
        Protocol(cutoffs=(1,), qrels_complete=True),
        {"easy": {"a": 1}, "omitted": {"b": 1}},
    )
    assert report["pairs"][0]["status"] == "comparable"
    warnings = [f for f in report["findings"] if f["code"] == "qrels_queries_without_predictions"]
    assert len(warnings) == 2
