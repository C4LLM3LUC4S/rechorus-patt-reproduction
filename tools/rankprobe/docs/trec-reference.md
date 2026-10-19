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

The original 960 comparisons use integer nonnegative judgments, finite distinct scores, unique documents per query, at least one relevant item in every query, and the same query universe on both sides. Every submitted candidate is judged. Unretrieved relevant items remain in qrels, so they affect the ideal NDCG ranking and Recall denominator. Completeness is justified by these small constructed universes, not inferred for arbitrary datasets. RankProbe uses linear gain and relevance strictly above zero. Their counts and results remain in the `shared_protocol` summary, alongside four deliberate protocol-boundary probes.

For each cutoff `K`, the reference invocation includes:

```sh
trec_eval -q -M K -l 1 -m recip_rank -m ndcg_cut.K -m recall.K judgments.qrels predictions.run
```

[`recip_rank`](https://github.com/usnistgov/trec_eval/blob/ba38899cbd4de0fb699b47f39b64ef1c107e4a5c/m_recip_rank.c) has no cutoff parameter: `-M K` is needed to compare it to MRR@K. [`ndcg_cut`](https://github.com/usnistgov/trec_eval/blob/ba38899cbd4de0fb699b47f39b64ef1c107e4a5c/m_ndcg_cut.c) uses the qrels grade directly as gain. The default reference text output rounds to four decimals, so the checker uses absolute tolerance `0.00005000001`, with no relative tolerance. Passing this check does not establish agreement at twelve decimal places.

## Bounded exponential-gain NDCG check

A separate `exp2_ndcg` summary records 12 comparisons for one original two-query case: per-query and macro NDCG at cutoffs 1, 2, 5 and 10. RankProbe receives the original grades with `gain="exp2"` and `qrels_complete=True`. Every candidate has an explicit judgment; scores are finite and distinct, candidate IDs are unique within each query, and both evaluators use exactly the same two queries. The constructed qrels include unretrieved items.

| Query | Retrieved items in score order | Complete original judgments |
| --- | --- | --- |
| `q1` | `low` (4), `high` (2) | `low=1`, `high=3`, `unretrieved_medium=2`, `zero=0` |
| `q2` | `medium` (9), `zero` (5) | `medium=2`, `zero=0`, `unretrieved_high=3`, `low=1` |

Only a new reference-qrels copy maps grades `0, 1, 2, 3` to gains `0, 1, 3, 7`, respectively. The original RankProbe rows and qrels stay unchanged in memory. The checker also writes the original qrels and prediction run, then invokes the reference using that prediction run and the transformed qrels copy. It records and compares pre/post SHA256 hashes for all three files in `input_file_integrity`, separately from `original_in_memory_inputs_unchanged`. Because pinned [`ndcg_cut`](https://github.com/usnistgov/trec_eval/blob/ba38899cbd4de0fb699b47f39b64ef1c107e4a5c/m_ndcg_cut.c#L23-L39) uses the qrels values directly, the transformed values supply `2**r - 1` for both retrieved and ideal gains:

```sh
trec_eval -q -m ndcg_cut.1,2,5,10 gain-transformed.qrels predictions.run
```

This invocation requests only cutoff NDCG and needs no `-M`. The uncut [`ndcg` gain-mapping option](https://github.com/usnistgov/trec_eval/blob/ba38899cbd4de0fb699b47f39b64ef1c107e4a5c/m_ndcg.c#L38-L57) is not substituted: its ideal denominator continues through all positive gains, which differs from the ideal at a requested cutoff.

At cutoff 1, the analytic NDCG values are `q1=1/7`, `q2=3/7`, and macro `2/7`. The untransformed linear macro is `1/2`. RankProbe's internal rational controls use absolute tolerance `1e-14`. The checker requires exactly the 12 expected metric/query keys, requires RankProbe status `ok`, and retains absolute tolerance `0.00005000001` for every comparison involving the reference's four-decimal output. Both tolerances use relative tolerance zero. Ignoring or applying the gain transform twice cannot satisfy these controls. Actual executable agreement is established by the pinned-reference CI job for the checked commit.

This case supports only exponential-gain NDCG on these small integer grades. It does not cover fractional or extreme grades, score ties, other judgment policies, or general agreement between evaluators. Restricting the transformed gains to a maximum of 7 also keeps the pinned source's [relevance-level allocation](https://github.com/usnistgov/trec_eval/blob/ba38899cbd4de0fb699b47f39b64ef1c107e4a5c/form_res_rels.c#L153-L157) bounded.

## Bounded fractional linear-gain NDCG check

A separate `fractional_linear_ndcg` summary records 12 comparisons for one original two-query case: per-query and macro NDCG at cutoffs 1, 2, 5 and 10. RankProbe receives the original fractional grades with linear gain and `qrels_complete=True`. Every candidate has an explicit judgment; scores are finite and distinct, candidate IDs are unique within each query, and both evaluators use exactly the same two queries. The complete qrels manually enumerate each small synthetic universe, including unretrieved items. This construction justifies completeness for this case only; it does not establish completeness for user data.

| Query | Retrieved items in score order | Complete original judgments |
| --- | --- | --- |
| `q1` | `low` (4), `high` (2) | `low=0.125`, `high=1.75`, `unretrieved_medium=0.5`, `zero=0` |
| `q2` | `medium` (9), `zero` (5) | `medium=0.5`, `zero=0`, `unretrieved_high=1.75`, `low=0.125` |

Only a new oracle-qrels copy multiplies every original grade by 8, mapping `0, 0.125, 0.5, 1.75` exactly to the integers `0, 1, 4, 14`. The checker independently asserts this exact mapping for every qrels entry, including unretrieved and zero-grade entries. For linear gain, a common positive scaling multiplies both DCG and IDCG by the same factor, so their ratio is unchanged. Different common scales that yield integer oracle grades, such as 8 and 64 (scaling by 8 twice), would produce the same NDCG. Metric agreement therefore cannot verify the required single factor of 8; the per-entry mapping assertions are required separately.

The original RankProbe rows and qrels stay unchanged in memory. The checker writes the original fractional qrels, the original prediction run and the integer oracle qrels, then records and compares pre/post SHA256 hashes for all three files in `input_file_integrity`, separately from `original_in_memory_inputs_unchanged`. Only the integer oracle qrels are supplied to the native reference, in one invocation:

```sh
trec_eval -q -m ndcg_cut.1,2,5,10 gain-transformed.qrels predictions.run
```

This invocation requests only cutoff NDCG and needs no `-M`. At cutoff 1, the analytic NDCG values are `q1=1/14`, `q2=2/7`, and macro `5/28`. RankProbe's internal analytic controls use absolute tolerance `1e-14`. The checker requires exactly the 12 expected metric/query keys and RankProbe status `ok`; every comparison involving the reference's four-decimal output uses absolute tolerance `0.00005000001`. Both tolerances use relative tolerance zero.

This case checks only these bounded fractional grades with linear gain through an integer-scaled oracle. It does not show that native `trec_eval` accepts fractional qrels, and it does not cover fractional exponential gain, extreme grades, score ties, arbitrary decimal labels, or new file-import validation. The original 960 linear comparisons, four boundary probes and 12 integer exponential-gain comparisons retain their separate scopes and summaries. The same modern source pin and executable-provenance limits above apply; actual executable agreement must be confirmed by the pinned-reference CI job for the checked commit.

## Differences to check before changing code

| Situation | RankProbe | Pinned reference behavior |
| --- | --- | --- |
| Exact score tie | Ascending item ID by default; input order is an option | Descending document ID |
| Missing candidate judgment | Kept unknown by default; MRR needs a known prefix through the first relevant item, while NDCG needs all candidate labels | These requested metrics treat the missing judgment as nonrelevant |
| Query with no relevant judgments | Recall excludes it and reports why | Recall contributes zero to the macro average |
| Qrels query without submitted predictions | Reports missing query and averages submitted, eligible queries | This pinned source exits with code 4 by default; `-c` includes the missing query as zero |
| Exponential gain on small integer grades | Explicitly supported by RankProbe | Covered only by the separate bounded case above using transformed reference qrels |
| Fractional or extreme relevance grades | Explicitly supported by RankProbe | Only the bounded fractional linear case above is covered, using an integer-scaled oracle; fractional exponential gain, extreme grades and arbitrary decimal labels remain outside these reference comparisons |
| Duplicate retrieved document | Highest-score deduplication plus a finding | Outside this parity suite; reference can reject it |

These are protocol differences, not proof that either model improved. The boundary probes deliberately assert different outputs where appropriate. They also check that RankProbe keeps unknown labels unknown. The pinned source's [actual missing-query control flow](https://github.com/usnistgov/trec_eval/blob/ba38899cbd4de0fb699b47f39b64ef1c107e4a5c/trec_eval.c#L349-L375) takes precedence over its older intersection wording in help text; results must be confirmed by execution.

For your own disagreement, first save the original run/qrels hashes and both commands. Check ties, gain, binary threshold, cutoff, missing judgments and the evaluated query IDs. Reproduce the difference on a small input you are allowed to inspect. Do not set `--unjudged nonrelevant` or `--qrels-complete` merely to force two numbers to match. No human time-saving baseline or external adoption is established by this developer check.

## Separate gdeval judgment and topic policy check

This source-policy check targets the official [`gdeval.pl` source snapshot in the 2014 repository](https://github.com/trec-web/trec-web-2014/blob/912a21f96b9d489938fc649c5545836bc16038b9/src/eval/gdeval.pl), script version 1.3 (2013-04-29), SHA256 `723ae1254f298ceac475fbc04941a87005f3daf0b7872ee809a745a05c985d31`. With Perl already available and this exact source saved separately, use a new output directory:

```sh
python scripts/check_gdeval_policy.py --gdeval /path/to/gdeval.pl --out gdeval-policy-result
```

Five original synthetic invocations at cutoff 1 check positive-only topic selection, zero gain for unstored judgments, and default versus `-c` averaging. The positive-first baseline requires topic 1 NDCG = 1 in both modes, with means 1 and 1/2 respectively; `-c` includes a missing positive-judgment topic in the mean denominator without adding a per-topic row; nonpositive-only qrels topics stay outside it. Separate runs put supplied grades `-2`, `-1` or `0` first and require NDCG = 0. Original inputs and their hashes are retained.

These are policy checks, not RankProbe parity comparisons or automatic grade mappings. ERR is only parsed for finite output, not validated or added to RankProbe. This check does not establish equivalence to the historical 2011 evaluator. Confirm actual execution in the exact-commit CI run; local parser/unit checks alone do not establish native agreement or justify changing unknown-label or completeness assumptions.
