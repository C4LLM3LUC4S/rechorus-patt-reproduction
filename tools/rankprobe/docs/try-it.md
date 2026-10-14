# Try RankProbe in five minutes

RankProbe is an early offline checker for recommendation, retrieval, and reranking exports. It helps you inspect ties, repeated candidates, missing queries, inconsistent candidate pools, and uncertain judgments. It does not train a model or certify an experiment.

## 1. Install locally

Use Python 3.10 or newer. From this package's root directory:

```sh
python -m venv .venv
```

Activate it on Windows PowerShell with `.\.venv\Scripts\Activate.ps1`, or on macOS / Linux with `source .venv/bin/activate`. Then install:

```sh
python -m pip install .
python -m rankprobe --version
```

If PowerShell blocks activation, use `.\.venv\Scripts\python.exe` in place of `python` in the remaining commands. The core package has no runtime dependency and audits do not require network access. Installing build requirements may need a connection or an existing package cache.

## 2. Inspect a small complete example

```sh
python -m rankprobe compare --run baseline=examples/trec/baseline.run --run reordered=examples/trec/reordered.run --qrels examples/trec/judgments.qrels --cutoffs 1,2 --out reports/first-try
```

Open `reports/first-try/report.html` in a browser. All demonstration records are invented. Baseline MRR@2 is 0.25 and reordered MRR@2 is 0.5, but both are 0.5 on the matched, metric-eligible query. Find the query coverage warning and excluded-query details. [The walkthrough](../examples/trec/README.md) explains every expected value.

If you only have one export, use `audit`; use `compare` when two runs should represent the same evaluation task.

## 3. Try your own export

TREC-style files:

```sh
python -m rankprobe audit my-results.run --qrels my-judgments.qrels --out reports/my-audit
```

CSV / JSONL exports:

```sh
python -m rankprobe audit my-predictions.csv --out reports/my-audit
```

CSV requires `query_id,item_id,score` and optional `relevance`. Scores rank from high to low. Without judgments, label-dependent metrics are unverified; the tool still checks evidence that does not require labels. See [input-format.md](input-format.md) for exact formats and `.txt` overrides. Leave unknown labels unknown until you can justify a convention. Use a fresh output directory, or explicitly add `--overwrite` to replace the report pair.

The report is created on your computer. Review its IDs and examples before sharing it. A screenshot or short description is enough for initial feedback; do not send private rows, access tokens, proprietary labels, or licensed data you cannot redistribute.

## A short invitation you can forward

> I am testing RankProbe, an early open-source offline audit tool for recommendation and retrieval evaluation exports. It takes CSV/JSONL or TREC-style runs and creates local HTML/JSON reports about ties, duplicate candidates, query coverage, and uncertain labels. Would you try one small export you are allowed to inspect and tell me whether it reveals anything useful? It takes no API key and does not upload your input. You do not need to share the source data or the whole report. The documented synthetic example is a safe first step. This is an alpha trial; it does not certify benchmark correctness.

Share the repository / branch link from the main README together with this page. This invitation has not been sent by the project, and it is not evidence of external adoption.

## Six feedback questions

1. What did you try: recommendation, retrieval, reranking, or another ranking task? What file format and evaluator did you use?
2. Could you install the tool and create the first report without help? Where did you stop or get confused?
3. Which finding changed your interpretation or exposed a previously unnoticed issue? If none, say so.
4. Did any finding seem incorrect or unclear? Share the finding code and an invented minimal example if possible.
5. Did you change your export, evaluation settings, or CI because of the report? What concrete change did you make?
6. Would you use it on the next experiment? Which missing capability is essential for that use?

Useful validation is a reproducible issue, a corrected protocol, or repeat use. Stars and installation counts alone do not show that the tool helped. Record feedback only with the contributor's consent; do not infer financial or research outcomes from one trial.
