# RankProbe

首个 alpha 暂放在现有复现仓库的独立目录与分支。试用时可分享直达 [RankProbe 项目页](https://github.com/C4LLM3LUC4S/rechorus-patt-reproduction/tree/feature/rankprobe-alpha/tools/rankprobe)和[首次报告指南](https://github.com/C4LLM3LUC4S/rechorus-patt-reproduction/blob/feature/rankprobe-alpha/tools/rankprobe/docs/try-it.md)的链接。没有 Git 时，可[下载源码 ZIP](https://codeload.github.com/C4LLM3LUC4S/rechorus-patt-reproduction/zip/refs/heads/feature/rankprobe-alpha)，解压，在解压后的仓库文件夹打开终端，再运行 `cd tools/rankprobe`。

Windows 建议选择较短的解压路径；如果创建环境时 pip/ensurepip 提示路径过长，请换一个较短的文件夹重新开始。

也可以用 Git 获取：

```sh
git clone --branch feature/rankprobe-alpha https://github.com/C4LLM3LUC4S/rechorus-patt-reproduction.git
cd rechorus-patt-reproduction/tools/rankprobe
```

**检查推荐与检索指标是否受到同分排序、重复候选和评测集合变化的影响。**

RankProbe 在本地读取候选分数及相关性标签，生成 HTML 和 JSON 报告，解释发现、影响范围与评测假设。无需重新训练模型、云账户或 API 密钥；核心只依赖 Python 标准库。

[English](README.md) · [输入格式](docs/input-format.md) · [指标定义](docs/metrics.md) · [首次本地报告](docs/try-it.md) · [能力边界](docs/limitations.md)

使用 BEIR 时，可按 [导出与评估接入指南](docs/beir-workflow.md) 保留检索原始快照，明确同名 ID 过滤和候选截断策略，并仅转移已有 qrels 标签。

使用 RecBole 非序列 full-sort 时，可按 [安全导出指南](docs/recbole-workflow.md) 记录 padding/history 排除原因，保留外部 ID，并拒绝有效候选上的异常分数；未观察到的交互仍保持未知。

使用 ReChorus 时，可按 [runner 捕获指南](docs/rechorus-workflow.md) 在默认 top-100 展示导出之前保存 sampled 候选，或按明确原因导出基础 full-sort 输入约定下的有效分数。跨 run 比较可显式保留事件与物品 ID；未知标签保持未知。

已有 MTEB 检索预测文件时，可按 [分数文件接入指南](docs/mteb-workflow.md) 明确选择一个 subset 和 split，转入现有 CSV 接口，并核对缓存、输出目录和评分前后的候选范围。只有汇总指标的结果 JSON 无法恢复候选分数。

## 快速开始

需要 Python 3.10 或以上版本。目前从本地源码安装，尚未声称已发布到 PyPI。

在这个包的文件夹中创建独立环境，直接使用它的解释器，无需激活。

Windows PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install .
.\.venv\Scripts\python.exe -m rankprobe demo --out reports/demo
```

macOS / Linux：

```sh
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/python -m rankprobe demo --out reports/demo
```

用浏览器离线打开 `reports/demo/report.html`。[完整试用步骤](docs/try-it.md) 包含有预期数值的比较，以及已有框架环境与本环境的衔接。下文的 `python` 都指同一环境的解释器：Windows 使用 `.\.venv\Scripts\python.exe`，macOS / Linux 使用 `.venv/bin/python`。也可以尝试合成案例：

```sh
python -m rankprobe audit examples/ties.csv --cutoffs 1,5 --out reports/ties
python -m rankprobe audit examples/ties.csv --tie-policy input --cutoffs 1,5 --out reports/ties-input
python -m rankprobe compare --run baseline=examples/clean.csv --run changed=examples/mismatch.csv --out reports/compare
```

报告包括输入标识符与部分样例，分享前需自行检查是否包含私人信息。

比较报告可先看 **Comparison results**：原始运行指标、匹配集合上的指标与右减左差值并排显示，每个值都附带覆盖范围和参考池。展开覆盖明细能看到排除了哪些查询，再按发现卡片中的建议检查原因。差值表示指定协议下的数值差异，不表示统计显著性。

## 解决什么问题

- **同分敏感性：**定位完全相同的候选分数，比较输入顺序与确定排序，计算允许同分候选换序时的指标范围。
- **重复候选：**列出重复 `(query_id, item_id)`、分数或标签冲突，记录去重方式及影响。
- **多次运行可比性：**比较查询覆盖、每个查询的候选集合和相关性标签，说明仍需人工核对的协议。
- **独立指标复算：**给出 MRR、NDCG，以及满足条件时的 Recall；同时明确 cutoff、gain、同分规则、未知标签处理和分母范围。

同分或重复不必然是错误。工具不把不同的合法评测选择统一解释成一个“正确分数”。

## 输入自己的结果

每行是一次排序事件中的一个候选项。`query_id` 表示事件，不应直接把同一用户的不同时刻合并成一个查询。

```csv
query_id,item_id,score,relevance
q1,doc_a,0.9,1
q1,doc_b,0.7,0
q2,doc_c,0.4,2
```

分数必须有限，越大越靠前。相关性非负，MRR 与 Recall 把大于 0 的标签视为相关。缺少标签表示未知，只有显式指定 `--unjudged nonrelevant` 才将未标注候选视为不相关。JSONL 使用相同字段。

从 `0.1.0a4` 起，首个相关项及其之前的标签已知时，MRR 可以纳入该查询，后续未知标签仍保持未知。旧版采用更保守的资格规则；跨版本比较条件均值前，请先看[指标语义和迁移说明](docs/metrics.md#mrrk)。

```sh
python -m rankprobe audit predictions.jsonl --out reports/my-run
```

独立 qrels 包含 `query_id,item_id,relevance`。只有确有完整相关项信息时，才声明 `--qrels-complete`：

```sh
python -m rankprobe audit examples/unjudged.csv --qrels examples/qrels.csv --qrels-complete --out reports/qrels
```

候选池内的指标不等于全语料检索质量。完整性开关是使用者的声明，工具不能根据分数文件验证声明是否属实。

现在也能直接读取检索实验常用的 TREC run 与 qrels，无需先转换成 CSV：

```sh
python -m rankprobe audit results.run --qrels judgments.qrels --out reports/retrieval
```

若文件扩展名是 `.txt`，需显式加入 `--input-format trec --qrels-format trec`。排序由 score 决定，文件中的 rank 不参与排序；qrels 的 `-1` 保持为未知，含此类条目时不能声明完整 qrels。[检索案例](examples/trec/README.md) 展示了一个可手算的陷阱：漏掉困难查询就能让平均 MRR 翻倍，共同查询上的结果却没有提升。案例是原创合成数据。

## 导出已有实验

提供独立实现的 ReChorus 风格 NPZ 适配器，NumPy 仅为此可选工具所需：

```sh
python -m pip install -e ".[adapters]"
python scripts/export_rechorus.py local_test_predictions.npz --out local_export.csv --positive-index 0 --limit-queries 100
python -m rankprobe audit local_export.csv --out reports/local-export
```

此例只声明指定列为正例，其他标签保持未知；仅在核验过的评测协议确有依据时，另加 `--other-candidates nonrelevant`。每个矩阵行单独成为一个查询；`user_id` 数组不导出，物品标识被替换。依赖模型的捕获步骤应使用你原有框架的解释器，导出文件后再用上面的核心环境审计。导出假设、隐私边界与跨文件对齐限制见 [适配器说明](docs/adapters.md)。公开示例均为原创合成数据，不分发私人预测、MovieLens 数据或第三方代码。

RankProbe 不保证与任意框架输出相同。默认同分规则是物品 ID 字符串升序，与 `trec_eval` 的规则不同。已有公共问题只用作背景，不声称发现了新漏洞或替代上游修复，见 [案例来源](docs/known-cases.md)。新增的 [trec_eval 独立交叉验证](docs/trec-reference.md) 提供可复现检查：共同协议下核对数值，协议不同时保留并解释差异，不能为了对齐结果而随意补零或宣称标签完整。

## 当前阶段

这是早期 `0.1.0a4` 实现，已执行的检查见 [验证记录](docs/verification.md)，尚无外部采用、收入或论文成果的证据。下一步按 [试用计划](docs/validation-plan.md) 和 [路线图](docs/roadmap.md) 验证陌生用户能否独立使用并获得实际帮助，再决定扩展方向。CI 覆盖多个 Python 版本及 Windows/Ubuntu，是否实际通过需查看对应提交的运行记录。

```sh
python -m pip install -e ".[dev,adapters]"
python -m pytest
python -m ruff check .
python -m build
python scripts/check_distribution.py
python scripts/check_wheel_install.py --wheel dist/rankprobe-0.1.0a4-py3-none-any.whl
```

CI 同时检查源码与构建出的 wheel：在干净环境中独立安装后，运行模块入口、实际命令行入口和检索比较，见 [安装验证说明](docs/installation-checks.md)。是否通过以对应提交的运行记录为准。

欢迎用最小合成输入报告问题。许可证见 [LICENSE](LICENSE)，软件引用信息见 [CITATION.cff](CITATION.cff)。第三方数据与输出继续受其来源条款约束。
