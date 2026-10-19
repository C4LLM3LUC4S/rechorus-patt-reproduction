# Capabilities and limits

RankProbe audits the evidence in supplied prediction and judgment files. It can reveal score-order sensitivity and file-level differences. It cannot certify that a model, dataset, paper, leaderboard, or experiment is correct.

## Inputs do not reveal the whole experiment

Scores alone cannot verify temporal leakage, train/test overlap, causal validity of histories, test-set tuning, genuine independence of a holdout, provenance of human labels, or whether qrels contain every relevant item. A matching query ID can conceal different preprocessing or task text. Save the original evaluation configuration and data lineage.

## Metric values are conditional

Candidate-pool NDCG evaluates the supplied pool. MRR over a supplied shortlist is not a full-corpus retrieval measure. Recall requires a justified denominator. Excluding unknown labels changes the set of evaluated queries. A clean report means the implemented checks found no issue in the supplied evidence, not that every relevant risk has been eliminated.

Exact ties can be valid. Deduplicating sampled negatives changes a protocol and may be inappropriate as a primary replacement. The tool makes these effects visible and requires the user to interpret them.

## Framework compatibility

This is an independent standard-library implementation. It does not run MTEB, RecBole, ReChorus, or their tokenizers. Differences in tie direction, graded gain, relevance thresholds, empty-positive conventions, padding, and averaging can produce legitimate differences. The NPZ adapter supports a documented matrix shape and one-positive-column convention; it does not support every ReChorus task or version.

TREC text input is a file-format interface, not a trec_eval compatibility mode. RankProbe sorts by score, then ascending item ID by default, irrespective of the declared rank column. It requires exact field counts and permits nonnegative fractional qrels grades as an extension. It preserves `-1` and absent judgments as unknown by default. These choices can differ from another evaluator even when both read the same file.

Macro averages cover eligible queries present in each prediction file. Queries found only in qrels produce a warning and partial coverage; they are not automatically scored as zero or included in the average. Compare the eligible query IDs and the matched-pool result before interpreting a change. A system that omits difficult queries can otherwise appear better. The [synthetic TREC case](../examples/trec/README.md) isolates this mechanism without making a benchmark claim.

## Operational and privacy limits

The audit runs locally and does not need a network connection. It reads whole input files into memory; it is designed for inspectable offline exports rather than a claim of streaming, billion-row scale. No universal memory or throughput guarantee is made.

HTML reports are self-contained. They include identifiers and selected examples from the input, while JSON can contain additional audit detail. Renaming IDs is pseudonymization; relational structure and scores can still be sensitive. Do not upload reports to public issues without reviewing them. The optional adapter omits user IDs but does not make third-party data legally redistributable.

## Early software

This alpha package and its JSON schema can evolve; the report schema version is currently `0.1`. Unreleased builds can share a package version: retain an exact source commit or build artifact when integrating reports into automated checks. The CLI's [core-source identity](usage.md) distinguishes available source bytes, but does not identify the complete runtime environment. Local tests and configured CI do not establish external adoption or cross-platform results that have not actually run. There is no claim of revenue, security certification, online business improvement, or accepted research output.
