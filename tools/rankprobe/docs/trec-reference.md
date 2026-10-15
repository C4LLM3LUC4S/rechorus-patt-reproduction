# Checking a metric disagreement with trec_eval

Reading a TREC run does not imply that two evaluators implement the same experiment. This check separates numerical agreement under a shared protocol from deliberate differences in judgment coverage, ties and averaging. It is a developer diagnostic, not a new metric or model-quality certificate.

## Reproduce the reference check

Use an installed RankProbe plus its source checkout and a separately built `trec_eval` executable:

```sh
python scripts/check_trec_eval.py --trec-eval /path/to/trec_eval --summary reference-result.json
```

The checker creates original synthetic run/qrels files in a temporary directory outside the checkout, invokes the executable, and compares per-query and macro results with RankProbe. It does not download a binary or send inputs anywhere. The optional summary refuses an existing file. It records the executable hash/version, case counts, comparison error and explicit protocol-boundary observations. A binary's version string alone does not prove which source produced it.

CI provides the fixed build: NIST [`usnistgov/trec_eval` at `ba38899cbd4de0fb699b47f39b64ef1c107e4a5c`](https://github.com/usnistgov/trec_eval/tree/ba38899cbd4de0fb699b47f39b64ef1c107e4a5c). The archive SHA256 is `d603cd657950aebea3a5ed08cee5ea0e5e836012ed5eb63303d3a7d66e49ba6a`. The Ubuntu reference job verifies this hash, builds the unmodified source with GCC, and runs the upstream `quicktest` before invoking our checker. Source and upstream test data stay in the runner's temporary directory; they are not added to RankProbe's wheel, source package, or public examples. The JSON summary is retained as a CI artifact for 14 days.

The local Windows machine does not currently have a usable C compiler or WSL environment. Actual executable validation therefore comes from the reference CI job, not an unexecuted local build instruction. Check the run for the exact commit before treating this gate as passed.

## Conditions under which values should agree

Shared cases use integer nonnegative judgments, finite distinct scores, unique documents per query, at least one relevant item in every query, and the same query universe on both sides. Every submitted candidate is judged. Unretrieved relevant items remain in qrels, so they affect the ideal NDCG ranking and Recall denominator. Completeness is justified by these small constructed universes, not inferred for arbitrary datasets. RankProbe uses linear gain and relevance strictly above zero.

For each cutoff `K`, the reference invocation includes:

```sh
trec_eval -q -M K -l 1 -m recip_rank -m ndcg_cut.K -m recall.K judgments.qrels predictions.run
```

[`recip_rank`](https://github.com/usnistgov/trec_eval/blob/ba38899cbd4de0fb699b47f39b64ef1c107e4a5c/m_recip_rank.c) has no cutoff parameter: `-M K` is needed to compare it to MRR@K. [`ndcg_cut`](https://github.com/usnistgov/trec_eval/blob/ba38899cbd4de0fb699b47f39b64ef1c107e4a5c/m_ndcg_cut.c) uses the qrels grade directly as gain. The default reference text output rounds to four decimals, so the checker uses absolute tolerance `0.00005000001`, with no relative tolerance. Passing this check does not establish agreement at twelve decimal places.

## Differences to check before changing code

| Situation | RankProbe | Pinned reference behavior |
| --- | --- | --- |
| Exact score tie | Ascending item ID by default; input order is an option | Descending document ID |
| Missing candidate judgment | Kept unknown by default; affected metric/query may be excluded | These requested metrics treat the missing judgment as nonrelevant |
| Query with no relevant judgments | Recall excludes it and reports why | Recall contributes zero to the macro average |
| Qrels query without submitted predictions | Reports missing query and averages submitted, eligible queries | This pinned source exits with code 4 by default; `-c` includes the missing query as zero |
| Fractional or exponential relevance gain | Explicitly supported by RankProbe | Outside this shared integer/linear protocol |
| Duplicate retrieved document | Highest-score deduplication plus a finding | Outside this parity suite; reference can reject it |

These are protocol differences, not proof that either model improved. The boundary probes deliberately assert different outputs where appropriate. They also check that RankProbe keeps unknown labels unknown. The pinned source's [actual missing-query control flow](https://github.com/usnistgov/trec_eval/blob/ba38899cbd4de0fb699b47f39b64ef1c107e4a5c/trec_eval.c#L349-L375) takes precedence over its older intersection wording in help text; results must be confirmed by execution.

For your own disagreement, first save the original run/qrels hashes and both commands. Check ties, gain, binary threshold, cutoff, missing judgments and the evaluated query IDs. Reproduce the difference on a small input you are allowed to inspect. Do not set `--unjudged nonrelevant` or `--qrels-complete` merely to force two numbers to match. No human time-saving baseline or external adoption is established by this developer check.
