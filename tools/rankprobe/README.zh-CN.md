# RankProbe

首个 alpha 暂放在现有复现仓库的独立目录与分支，可这样获取：

```sh
git clone --branch feature/rankprobe-alpha https://github.com/C4LLM3LUC4S/rechorus-patt-reproduction.git
cd rechorus-patt-reproduction/tools/rankprobe
```

**检查推荐与检索指标是否受到同分排序、重复候选和评测集合变化的影响。**

RankProbe 在本地读取候选分数及相关性标签，生成 HTML 和 JSON 报告，解释发现、影响范围与评测假设。无需重新训练模型、云账户或 API 密钥；核心只依赖 Python 标准库。

[English](README.md) · [输入格式](docs/input-format.md) · [指标定义](docs/metrics.md) · [示例](examples/README.md) · [能力边界](docs/limitations.md)

## 快速开始

需要 Python 3.10 或以上版本。目前从本地源码安装，尚未声称已发布到 PyPI。

```sh
python -m pip install -e .
python -m rankprobe demo --out reports/demo
```

用浏览器打开生成的 `report.html`。也可以直接尝试有预期结果的合成案例：

```sh
python -m rankprobe audit examples/ties.csv --cutoffs 1,5 --out reports/ties
python -m rankprobe audit examples/ties.csv --tie-policy input --cutoffs 1,5 --out reports/ties-input
python -m rankprobe compare --run baseline=examples/clean.csv --run changed=examples/mismatch.csv --out reports/compare
```

报告包括输入标识符与部分样例，分享前需自行检查是否包含私人信息。

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

```sh
python -m rankprobe audit predictions.jsonl --out reports/my-run
```

独立 qrels 包含 `query_id,item_id,relevance`。只有确有完整相关项信息时，才声明 `--qrels-complete`：

```sh
python -m rankprobe audit examples/unjudged.csv --qrels examples/qrels.csv --qrels-complete --out reports/qrels
```

候选池内的指标不等于全语料检索质量。完整性开关是使用者的声明，工具不能根据分数文件验证声明是否属实。

## 导出已有实验

提供独立实现的 ReChorus 风格 NPZ 适配器，NumPy 仅为此可选工具所需：

```sh
python -m pip install -e ".[adapters]"
python scripts/export_rechorus.py local_test_predictions.npz --out local_export.csv --positive-index 0 --other-candidates nonrelevant --limit-queries 100
python -m rankprobe audit local_export.csv --out reports/local-export
```

每个矩阵行单独成为一个查询；用户标识不导出，物品标识被替换。导出假设、隐私边界与跨文件对齐限制见 [适配器说明](docs/adapters.md)。公开示例均为原创合成数据，不分发私人预测、MovieLens 数据或第三方代码。

RankProbe 不保证与任意框架输出相同。默认同分规则是物品 ID 字符串升序，与 `trec_eval` 的规则不同。已有公共问题只用作背景，不声称发现了新漏洞或替代上游修复，见 [案例来源](docs/known-cases.md)。

## 当前阶段

这是早期 `0.1.0a1` 实现，已执行的检查见 [本地验证记录](docs/verification.md)，尚无外部采用、收入或论文成果的证据。下一步按 [试用计划](docs/validation-plan.md) 验证陌生用户能否独立使用并获得实际帮助。CI 配置覆盖多个 Python 版本及 Windows/Ubuntu，是否实际通过需查看对应提交的运行记录。

```sh
python -m pip install -e ".[dev,adapters]"
python -m pytest
python -m build
```

欢迎用最小合成输入报告问题。许可证见 [LICENSE](LICENSE)，软件引用信息见 [CITATION.cff](CITATION.cff)。第三方数据与输出继续受其来源条款约束。
