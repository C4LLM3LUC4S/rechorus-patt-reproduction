# Export RecBole full-sort scores with explicit exclusions

RecBole's official [`full_sort_scores`](https://github.com/RUCAIBox/RecBole/blob/7b02be5ec80a88310f2d04a27a82adfcbb5dc211/recbole/utils/case_study.py) sets padding column zero and, for nonsequential evaluation, history items to `-inf`. Those are intentional candidate exclusions. RankProbe accepts finite prediction scores, so flattening the whole tensor directly produces an invalid input. Replacing `-inf` with a large negative number would instead keep excluded items in the candidate pool.

The source-checkout helper `scripts/export_recbole.py` preserves finite scores and external user/item tokens, removes only the declared padding/history positions, and writes their reasons to `exclusions.json`. It rejects nonfinite scores at eligible positions, inconsistent masks, duplicate identities, sequential data, and users with no eligible candidates. It writes predictions without a relevance column: an unobserved interaction is not automatically a zero label.

These observations and the optional integration check target RecBole source [`7b02be5ec80a88310f2d04a27a82adfcbb5dc211`](https://github.com/RUCAIBox/RecBole/tree/7b02be5ec80a88310f2d04a27a82adfcbb5dc211), identified as 1.2.1. They do not establish compatibility with all RecBole versions or evaluation tasks.

## Use your existing nonsequential evaluation environment

Use this helper from the RankProbe source checkout or source distribution in the environment where your trained model, NumPy and `FullSortEvalDataLoader` already exist. The helper is not an installed CLI subcommand and does not require RankProbe to be installed in that model environment. Keep the separate core environment from the [first-report installation](try-it.md#1-install-locally) for the later audit.

For the pinned nonsequential loader, select users from its actual evaluation population. Its [`uid_list` and `user_df`](https://github.com/RUCAIBox/RecBole/blob/7b02be5ec80a88310f2d04a27a82adfcbb5dc211/recbole/data/dataloader/general_dataloader.py#L201-L226) contain users observed in that split. The example deliberately selects at most two of them for a small first export:

```python
import sys
from pathlib import Path
from recbole.utils.case_study import full_sort_scores

sys.path.insert(0, str(Path("path/to/rankprobe/scripts").resolve()))
from export_recbole import export_full_sort

evaluation_uids = test_data.uid_list.detach().cpu().tolist()
uids = evaluation_uids[:2]
if not uids:
    raise ValueError("This evaluation loader has no users to score.")
scores = full_sort_scores(uids, model, test_data, device=model.device)
metadata = export_full_sort(scores, uids, test_data, Path("recbole-export"))
```

Do not substitute `range(1, dataset.user_num)` for this population. A numerically valid ID can have no evaluation record and no history tensor. A [public RecBole report](https://github.com/RUCAIBox/RecBole/issues/2006) describes the resulting failure before export; the [pinned scoring helper](https://github.com/RUCAIBox/RecBole/blob/7b02be5ec80a88310f2d04a27a82adfcbb5dc211/recbole/utils/case_study.py#L44-L50) directly consumes the selected history entries. The optional checker below constructs this population difference with original interactions. The public issue supplies context, not evidence of RankProbe adoption.

If you need a particular user list, check every requested ID against `evaluation_uids` first and stop to report missing IDs; keep the requested order for scoring and export. Reject empty requests and duplicate IDs too. Do not silently drop missing users. The example's small selected subset, all users in this loader, and all users in the dataset are different scopes and need not contain the same users. Record which one you selected; this step supplies neither predictions for absent users nor complete judgments.

The output directory must be new, its parent must exist, and symbolic-link ancestors are refused. Scores must be the complete `[len(uids), dataset.item_num]` matrix from this helper; sampled scores and top-k tensors have different alignment. The exporter reads `dataset.id2token` and `uid2history_item` from the same evaluation object. Do not combine scores with the ID mapping or history from another split: a same-shaped incorrect mapping cannot be detected automatically. Inputs are not modified. Float16/32/64 values are converted to ordinary Python floats for CSV serialization without decimal rounding; float64 values retain their binary64 value on reload. CSV and metadata retain external tokens, so keep real exports private unless redistribution is authorized.

Inspect `exclusions.json` before interpreting the report. Padding and history exclusion counts describe the exported candidate universe, not a detected leakage problem. A large catalog produces a large full-sort CSV; begin with a small user subset and account for both the model's tensor memory and export size. This first bridge does not stream model scoring.

## Transfer only judgments you actually have

Create a separate CSV with `query_id,item_id,relevance`, using the same external tokens and only observed judgments. Relevance must match the question you are evaluating. Do not infer nonrelevance from absence in the interaction log. For example, the following is an illustrative schema, not labels to copy into a real experiment:

```csv
query_id,item_id,relevance
reader-A,book-X,1
reader-A,book-Y,0
```

The export folder is relative to the model process's working directory. Record its absolute location before changing directories. Return to the RankProbe package folder and use the separate core interpreter below. Replace the example input paths with your actual permitted exports and judgments; omit `--qrels` if you have no independent judgments. Choose a new report directory.

Windows PowerShell:

```powershell
.\.venv\Scripts\python.exe -m rankprobe audit "D:/my evaluation/recbole-export/predictions.csv" --qrels "D:/my evaluation/judgments.csv" --cutoffs 1,10 --out reports/recbole-report
```

macOS / Linux:

```sh
.venv/bin/python -m rankprobe audit "/absolute/path/to/recbole-export/predictions.csv" --qrels "/absolute/path/to/judgments.csv" --cutoffs 1,10 --out reports/recbole-report
```

Unknown judgments can make some metrics unavailable. Read the metric eligibility and coverage in the report. In the pinned evaluator, [Recall](https://github.com/RUCAIBox/RecBole/blob/7b02be5ec80a88310f2d04a27a82adfcbb5dc211/recbole/evaluator/metrics.py#L153-L160) uses the [collected held-out positive-item count](https://github.com/RUCAIBox/RecBole/blob/7b02be5ec80a88310f2d04a27a82adfcbb5dc211/recbole/evaluator/collector.py#L159-L169) for each user, then [averages the collected users](https://github.com/RUCAIBox/RecBole/blob/7b02be5ec80a88310f2d04a27a82adfcbb5dc211/recbole/evaluator/base_metric.py#L67-L82). Align the same user IDs, candidate exclusions and held-out positive sets before comparing values: a small `uids` export and an aggregate over the full loader have different scope. Positive-only judgments leave other exported candidates unknown in RankProbe. A native Recall value does not establish complete judgments; do not enable `--qrels-complete` or change unknown labels merely to make values match. Tie order and eligible-query coverage can still differ, so this workflow does not promise numerical equality. See [protocol reference differences](trec-reference.md).

Before comparing native `hit@k` with this report, read [Hit/HR and Recall](metrics.md#native-hithr-and-recall); RankProbe does not report a Hit/HR field.

The official [`full_sort_topk`](https://github.com/RUCAIBox/RecBole/blob/7b02be5ec80a88310f2d04a27a82adfcbb5dc211/recbole/utils/case_study.py#L72-L90) applies `torch.topk` to the masked matrix. Requesting more items than remain eligible can therefore return masked entries. Export the full matrix through the exclusion-aware helper, rather than treating every returned top-k position as an eligible recommendation.

Sequential evaluation has a separate context problem: multiple interactions can belong to one user. A user token alone is not an event ID. This exporter rejects sequential inputs; it does not merge distinct prediction contexts or claim support for sampled evaluation.

## Reproduce the bounded integration check

In the isolated optional environment described by the [CI job](../.github/workflows/ci.yml), run from the source checkout:

```sh
python scripts/check_recbole_workflow.py --out recbole-workflow-example
```

The checker calls the official `Config`, `create_dataset` and `data_preparation` functions on eight original interactions in three local files: five train, one validation and two test rows. This constructs a real `Dataset`, phase samplers and nonsequential `FullSortEvalDataLoader` objects. It consumes an actual test batch and checks token mappings, positive items and history masks against manually specified expectations. One dataset user appears in the train and validation files but has no test interaction; the checker distinguishes this user from the actual test population and refuses a requested list containing an absent user instead of dropping that ID.

The scoring model remains a deterministic fixture with an original finite score table. Both official case-study helpers run against the real test loader, followed by the exclusion-aware export and installed RankProbe CLI. No model is trained or loaded from a checkpoint, and no dataset is downloaded. This exercises dataset loading and evaluation-loader construction, scoring-mask behavior and the export bridge; it does not validate a full production experiment lifecycle or establish equality with native RecBole metrics. Unknown judgments remain unknown.

This isolated check uses NumPy 1.26.4 because the pinned `Config` compatibility setup refers to `np.float_`, `np.complex_` and `np.unicode_`, which NumPy 2 removed. Its loader imports also require PyYAML 6.0.2, SciPy 1.15.3, scikit-learn 1.6.1 and tqdm 4.67.1 alongside the existing CPU helper dependencies. These versions belong to the optional checker environment; they do not pin core RankProbe dependencies or your existing model environment. The pinned RecBole sources are used without patches.

CI verifies source archive SHA256 `dcd778a920773821e0e1816d06735c79413f2f44a470eab9b119b1435d9c74da`; the checker verifies the installed configuration, dataset, sampler, dataloader, interaction and scoring-helper source bytes. The original interaction files, synthetic CSV, exclusion metadata and report are retained for 14 days as an artifact. Consult the current commit's job before claiming actual execution passed.

This closes an export integration gap. External adoption and human time saved still require independent trials with users' own permitted inputs.
