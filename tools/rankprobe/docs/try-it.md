# Create your first local report

RankProbe is an early offline checker for recommendation, retrieval, and reranking exports. It helps you inspect ties, repeated candidates, missing queries, inconsistent candidate pools, and uncertain judgments. It does not train a model or certify an experiment.

No active experiment or private prediction file is required to complete this walkthrough. Use the included demo or the original TREC fixtures in section 2; section 3 is optional until you already have a permitted export. There is no need to train a model just to try the checker. With scores but no judgments, structural checks remain available and label-dependent values stay unknown.

The [initial implementation is complete](initial-delivery.md). A successful example walkthrough establishes that the path works for that example; it does not by itself establish a new finding in the reader's work or time saved.

If you are trying it to give feedback, open the [trial record](validation-plan.md#feedback-form) before installing or reading a report. Write down your question and existing judgment first. If you have already completed a step without timing it, mark its time `not measured` rather than guessing.

## 1. Install locally

Use Python 3.10 or newer. For the complete offline distribution, [download `RankProbe-0.1.0a4.zip`](https://github.com/C4LLM3LUC4S/rechorus-patt-reproduction/releases/download/v0.1.0a4/RankProbe-0.1.0a4.zip), extract it and follow its `START_HERE.md`. To use the source-install commands below, obtain the default-branch checkout as shown in the [main README](../README.md) and enter `tools/rankprobe`. All example paths here are relative to that package folder. A wheel alone does not supply checkout paths; the complete bundle also includes them under `source/`. This release is hosted on GitHub, not PyPI.

On Windows, choose a short extraction path. If pip/ensurepip reports a long-path problem while creating the environment, start again from a shorter folder.

Create an isolated core environment and call its interpreter directly; activation and changes to PowerShell's execution policy are unnecessary.

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install .
.\.venv\Scripts\python.exe -m rankprobe --version
```

macOS / Linux:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/python -m rankprobe --version
```

Check that the Python used to create the environment is version 3.10 or newer (`python --version`, or `python3 --version`). If Windows provides only the `py` launcher, replace the first command with `py -3 -m venv .venv`; the remaining explicit paths are unchanged. The core has no runtime dependency and audits need no network access. Installing build requirements may need a connection or an existing package cache. If venv support is unavailable, follow your Python distribution's installation instructions before continuing.

## 2. Inspect a small complete example

Windows PowerShell:

```powershell
.\.venv\Scripts\python.exe -m rankprobe compare --run baseline=examples/trec/baseline.run --run reordered=examples/trec/reordered.run --qrels examples/trec/judgments.qrels --cutoffs 1,2 --out reports/first-try
```

macOS / Linux:

```sh
.venv/bin/python -m rankprobe compare --run baseline=examples/trec/baseline.run --run reordered=examples/trec/reordered.run --qrels examples/trec/judgments.qrels --cutoffs 1,2 --out reports/first-try
```

Open `reports/first-try/report.html` and start at **Comparison results**. Its English/Chinese reading guide puts submitted-query counts and a next step before the numbers. The quick view shows MRR/NDCG at the **largest requested cutoff** (here 2), with each average's eligible count, limited-scope marker and matched reference. Expand **Full metric table and coverage / 完整指标与范围** for every requested cutoff, Recall availability, statuses, reference pools and exclusion details. A missing value is not zero.

All demonstration records are invented. Baseline MRR@2 is 0.25 and reordered MRR@2 is 0.5, but both are 0.5 on the matched, metric-eligible query, so the matched delta is zero. There are two structurally matched queries but only one is eligible for these metrics. Compare runs within one metric; MRR and NDCG use different scoring rules and their numeric sizes are not directly comparable. Follow the query coverage finding's next step and expand metric coverage to inspect excluded queries. [The walkthrough](../examples/trec/README.md) explains every expected value; its [query recovery step](../examples/trec/README.md#restore-the-omitted-query-and-recheck) supplies a complete synthetic control, a fresh-report command and specific rechecks without filling unknown labels.

If you only have one export, use `audit`; use `compare` when two runs should represent the same evaluation task.

## 3. Try your own export

Keep using the same core interpreter. The following Windows PowerShell examples use your own permitted files in the package folder; on macOS / Linux replace `.\.venv\Scripts\python.exe` with `.venv/bin/python`.

TREC-style files:

```powershell
.\.venv\Scripts\python.exe -m rankprobe audit my-results.run --qrels my-judgments.qrels --out reports/my-audit
```

CSV / JSONL exports:

```powershell
.\.venv\Scripts\python.exe -m rankprobe audit my-predictions.csv --out reports/my-audit
```

CSV requires `query_id,item_id,score` and optional `relevance`. Scores rank from high to low. Without judgments, label-dependent metrics are unverified; the tool still checks evidence that does not require labels. See [input-format.md](input-format.md) for exact formats and `.txt` overrides. Leave unknown labels unknown until you can justify a convention. Use a fresh output directory, or explicitly add `--overwrite` to replace the report pair.

The report is created on your computer. Review its IDs and examples before sharing it. A screenshot or short description is enough for initial feedback; do not send private rows, access tokens, proprietary labels, or licensed data you cannot redistribute.

### Recover from a failed command

Read the terminal diagnostic before retrying. Exit code **2** means an argument, input or output operation failed; `--fail-on never` does not make invalid input acceptable. Exit code **1** means a report was completed and contains findings meeting the selected threshold, so open that report before changing anything. See [exit codes](usage.md#exit-codes-and-automation).

| What you see | Next step |
| --- | --- |
| `No module named rankprobe` | Return to this package folder and install with the same explicit environment interpreter used for the audit. On Windows, use `.\.venv\Scripts\python.exe -m pip install .`; on macOS / Linux use `.venv/bin/python -m pip install .`. |
| Unsupported extension for a TREC `.txt` file | Keep the original file and select `--input-format trec`; select `--qrels-format trec` as well when the judgments also use `.txt`. Only use these flags for the documented TREC formats. |
| An invalid score with a filename and line number | Inspect that record in the source export. Produce a corrected copy with finite scores, preserving IDs and supplied judgments; audit the corrected copy with a fresh output directory. Do not replace a missing or invalid score with zero to force an import. |
| `Report already exists` | Choose a new `--out` directory to retain the previous result. Use `--overwrite` only when you intend to replace that report pair. |
| `--out must name a directory` or `A report destination is a directory` | Choose another output directory. A file cannot serve as `--out`, and a directory named `report.json` or `report.html` cannot be replaced with `--overwrite`. Review the existing path before moving anything. |

For a score-parsing failure, RankProbe validates the input before writing a report. Correcting the source does not require deleting a partial report or changing the failure threshold. If an output error occurs after validation, inspect the diagnostic and destination before retrying; do not assume every kind of failure has the same cause.

### If predictions come from an existing framework

Keep model-dependent capture/export in the Python environment that already holds your model, runner and dataset; the new core environment above does not install those frameworks. Follow the [RecBole](recbole-workflow.md), [ReChorus](rechorus-workflow.md) or [BEIR](beir-workflow.md) recipe for your actual task. Source helpers live in the extracted `scripts` folder. The NumPy-only export helpers do not require RankProbe itself to be installed in the model environment; use their source path and that environment's existing NumPy. Capture all scores and IDs from the same evaluation objects and configuration.

After exporting, return to this package folder and audit the file with the core interpreter. For example, if an exporter wrote a sibling folder named `my exports`:

```powershell
.\.venv\Scripts\python.exe -m rankprobe audit "../my exports/predictions.csv" --out reports/my-export
```

On macOS / Linux:

```sh
.venv/bin/python -m rankprobe audit "../my exports/predictions.csv" --out reports/my-export
```

This file boundary avoids moving a trained model into the core environment. Leave undeclared labels unknown; do not add `--unjudged nonrelevant`, `--other-candidates nonrelevant` or `--qrels-complete` merely to make metrics appear. Those options record distinct assumptions that require evidence. The report can still reveal structural findings when label-dependent metrics are unavailable.

For saved MTEB retrieval predictions, use the [scope-specific score-file recipe](mteb-workflow.md). Its file conversion runs in the core environment and selects an explicit subset and split; a metrics-only MTEB result file cannot supply the candidate evidence.

## A short invitation you can forward

> I am testing RankProbe, an early open-source offline audit tool for recommendation and retrieval evaluation exports. It takes CSV/JSONL or TREC-style runs and creates local HTML/JSON reports about ties, duplicate candidates, query coverage, and uncertain labels. Would you try one small export you are allowed to inspect and tell me whether it reveals anything useful? It takes no API key and does not upload your input. You do not need to share the source data or the whole report. The documented synthetic example is a safe first step. This is an alpha trial; it does not certify benchmark correctness.

Share the [complete GitHub distribution](https://github.com/C4LLM3LUC4S/rechorus-patt-reproduction/releases/tag/v0.1.0a4), [RankProbe package page](https://github.com/C4LLM3LUC4S/rechorus-patt-reproduction/tree/main/tools/rankprobe) and [this walkthrough](https://github.com/C4LLM3LUC4S/rechorus-patt-reproduction/blob/main/tools/rankprobe/docs/try-it.md). The curated download contains RankProbe only; the repository also preserves the original coursework. Sharing instructions is not evidence of external adoption.

## Six feedback questions

Use the [copyable trial record](validation-plan.md#feedback-form) to record the task and your existing judgment before opening your report. It separates real exports from synthetic examples, active human time from waiting, assistance and actual repeat use. Unmeasured time stays `not measured`; a machine runtime is not human time saved.

1. What did you try: recommendation, retrieval, reranking, or another ranking task? What file format and evaluator did you use?
2. Could you install the tool and create the first report without help? Where did you stop or get confused?
3. Which finding changed your interpretation or exposed a previously unnoticed issue? If none, say so.
4. Did any finding seem incorrect or unclear? Share the finding code and an invented minimal example if possible.
5. Did you change your export, evaluation settings, or CI because of the report? What concrete change did you make?
6. Would you use it on the next experiment? Which missing capability is essential for that use?

Useful validation is a reproducible issue, a corrected protocol, or repeat use. Stars and installation counts alone do not show that the tool helped. Record feedback only with the contributor's consent; do not infer financial or research outcomes from one trial.
