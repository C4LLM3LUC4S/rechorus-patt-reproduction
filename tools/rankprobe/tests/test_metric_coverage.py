from rankprobe import Protocol, Row, compare_runs, evaluate_metrics


def test_excluded_ids_follow_each_metrics_judgment_rule():
    rows = [
        Row("fully_known", "a", 1, 1),
        Row("unknown_later", "a", 2, 1),
        Row("unknown_later", "b", 1),
        Row("unknown_first", "a", 1),
    ]
    metrics = evaluate_metrics(rows, Protocol(cutoffs=(1, 2)))
    assert metrics["mrr@1"]["excluded_query_ids"] == ["unknown_first"]
    assert metrics["mrr@2"]["excluded_query_ids"] == ["unknown_first"]
    assert metrics["mrr@2"]["eligible_query_ids"] == ["fully_known", "unknown_later"]
    assert metrics["mrr@2"]["eligibility_rule"] == "known_first_relevant_prefix"
    assert metrics["ndcg@1"]["excluded_query_ids"] == ["unknown_first", "unknown_later"]
    assert metrics["recall@1"]["excluded_query_ids"] == [
        "fully_known", "unknown_first", "unknown_later"
    ]
    for metric in metrics.values():
        eligible, excluded = set(metric["eligible_query_ids"]), set(metric["excluded_query_ids"])
        assert not eligible & excluded
        assert eligible | excluded == {row.query_id for row in rows}
        assert len(excluded) == metric["excluded_queries"]


def test_qrels_only_ids_are_distinct_from_excluded_prediction_queries():
    metrics = evaluate_metrics(
        [Row("submitted", "a", 1)], Protocol(cutoffs=(1,), qrels_complete=True),
        {"unsubmitted": {"a": 1}},
    )
    for metric in metrics.values():
        assert metric["excluded_query_ids"] == ["submitted"]
        assert metric["qrels_only_queries"] == 1
        assert metric["exclusion_reasons"] == {"query_missing_from_complete_qrels": 1}


def test_matched_comparison_does_not_reclassify_removed_queries_as_excluded():
    report = compare_runs(
        {
            "left": [Row("shared", "a", 1, 1), Row("only_left", "a", 1, 1)],
            "right": [Row("shared", "a", 1, 1)],
        }, Protocol(cutoffs=(1,)),
    )
    matched = report["pairs"][0]["matched_pool_comparison"]
    for side in ("left_metrics", "right_metrics"):
        assert matched[side]["mrr@1"]["eligible_query_ids"] == ["shared"]
        assert matched[side]["mrr@1"]["excluded_query_ids"] == []
        assert matched[side]["mrr@1"]["total_queries"] == 1
