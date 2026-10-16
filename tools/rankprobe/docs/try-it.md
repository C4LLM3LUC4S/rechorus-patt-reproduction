# Create your first local report

RankProbe is an early offline checker for recommendation, retrieval, and reranking exports. It helps you inspect ties, repeated candidates, missing queries, inconsistent candidate pools, and uncertain judgments. It does not train a model or certify an experiment.

If you are trying it to give feedback, open the [trial record](validation-plan.md#feedback-form) before installing or reading a report. Write down your question and existing judgment first. If you have already completed a step without timing it, mark its time `not measured` rather than guessing.

## 1. Install locally

Use Python 3.10 or newer. No Git is required: [download the source ZIP](https://codeload.github.com/C4LLM3LUC4S/rechorus-patt-reproduction/zip/refs/heads/feature/rankprobe-alpha), extract it, and open a terminal in the extracted repository folder. Run `cd tools/rankprobe` to reach this package's root. The ZIP contains the examples and source helpers; a wheel installation alone does not supply their checkout paths. The [main README](../README.md) also gives the optional Git route. This alpha has not been published to PyPI.

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

Open `reports/first-try/report.html` and start at **Comparison results**. All demonstration records are invented. Baseline MRR@2 is 0.25 and reordered MRR@2 is 0.5, but both are 0.5 on the matched, metric-eligible query, so the matched delta is zero. The table shows the sample count and scope beside each value. Follow the query coverage finding's next step and expand the metric coverage to inspect excluded queries. [The walkthrough](../examples/trec/README.md) explains every expected value.

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

Share the repository / branch link from the main README together with this page. This invitation has not been sent by the project, and it is not evidence of external adoption.

## Six feedback questions

Use the [copyable trial record](validation-plan.md#feedback-form) to record the task and your existing judgment before opening your report. It separates real exports from synthetic examples, active human time from waiting, assistance and actual repeat use. Unmeasured time stays `not measured`; a machine runtime is not human time saved.

1. What did you try: recommendation, retrieval, reranking, or another ranking task? What file format and evaluator did you use?
2. Could you install the tool and create the first report without help? Where did you stop or get confused?
3. Which finding changed your interpretation or exposed a previously unnoticed issue? If none, say so.
4. Did any finding seem incorrect or unclear? Share the finding code and an invented minimal example if possible.
5. Did you change your export, evaluation settings, or CI because of the report? What concrete change did you make?
6. Would you use it on the next experiment? Which missing capability is essential for that use?

Useful validation is a reproducible issue, a corrected protocol, or repeat use. Stars and installation counts alone do not show that the tool helped. Record feedback only with the contributor's consent; do not infer financial or research outcomes from one trial.
