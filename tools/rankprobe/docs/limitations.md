# Capabilities and limits

RankProbe audits the evidence in supplied prediction and judgment files. It can reveal score-order sensitivity and file-level differences. It cannot certify that a model, dataset, paper, leaderboard, or experiment is correct.

## Inputs do not reveal the whole experiment

Scores alone cannot verify temporal leakage, train/test overlap, causal validity of histories, test-set tuning, genuine independence of a holdout, provenance of human labels, or whether qrels contain every relevant item. A matching query ID can conceal different preprocessing or task text. Save the original evaluation configuration and data lineage.

## Metric values are conditional

Candidate-pool NDCG evaluates the supplied pool. MRR over a supplied shortlist is not a full-corpus retrieval measure. Recall requires a justified denominator. Excluding unknown labels changes the set of evaluated queries. A clean report means the implemented checks found no issue in the supplied evidence, not that every relevant risk has been eliminated.

Exact ties can be valid. Deduplicating sampled negatives changes a protocol and may be inappropriate as a primary replacement. The tool makes these effects visible and requires the user to interpret them.

## Framework compatibility

This is an independent standard-library implementation. It does not run MTEB, RecBole, ReChorus, or their tokenizers. Differences in tie direction, graded gain, relevance thresholds, empty-positive conventions, padding, and averaging can produce legitimate differences. The NPZ adapter supports a documented matrix shape and one-positive-column convention; it does not support every ReChorus task or version.

## Operational and privacy limits

The audit runs locally and does not need a network connection. It reads whole input files into memory; it is designed for inspectable offline exports rather than a claim of streaming, billion-row scale. No universal memory or throughput guarantee is made.

HTML reports are self-contained. They include identifiers and selected examples from the input, while JSON can contain additional audit detail. Renaming IDs is pseudonymization; relational structure and scores can still be sensitive. Do not upload reports to public issues without reviewing them. The optional adapter omits user IDs but does not make third-party data legally redistributable.

## Early software

The `0.1.0a1` JSON schema can evolve. Pin a version when integrating reports into automated checks. Local tests and configured CI do not establish external adoption or cross-platform results that have not actually run. There is no claim of revenue, security certification, online business improvement, or accepted research output.
