# ReChorus 中的概率注意力序列推荐

实现 KDD 2024 论文 **Probabilistic Attention for Sequential Recommendation** 的基础 PAtt₂，并比较 SASRec、GRU4Rec 和长度校准变体 LC-PAtt₂。本仓库不是官方实现，不包含 PAtt₃ 和 DPAtt。

论文：Yuli Liu, Christian Walder, Lexing Xie, Yiqun Liu. KDD 2024, 1956–1967. https://doi.org/10.1145/3637528.3671733

## 结果

完成16次学习率调参和24次正式实验。测试 NDCG@20 为三个种子的均值±样本标准差，后者不是置信区间。

| 数据集 | PAtt₂ | SASRec | GRU4Rec | LC-PAtt₂ |
|---|---:|---:|---:|---:|
| Grocery | 0.3708±0.0014 | 0.3393±0.0007 | 0.3071±0.0039 | 0.3512±0.0002 |
| MovieLens-1M | 0.4750±0.0017 | 0.4697±0.0032 | 0.4645±0.0016 | 0.4771±0.0020 |

长度校准没有获得跨数据集一致提升。全部正式预测通过独立准确性复算。`analysis/final_metrics.json`包含完整指标及各次种子结果，试跑结果不计入。

## 环境与数据

验证环境：Python 3.10.11、PyTorch 2.5.1+cu121、NumPy 2.2.6、pandas 2.3.3，RTX 4060 Laptop GPU（8 GB）。下列集成测试使用CUDA；CPU运行未作完整验证，不承诺相同速度或逐位数值一致。

```text
python -m pip install torch==2.5.1 --index-url https://download.pytorch.org/whl/cu121
python -m pip install -r requirements.txt
git clone https://github.com/THUwangcy/ReChorus sources/ReChorus
git -C sources/ReChorus checkout c164ec4303cc20ddcfbd1b57de366a481811d1e5
```

下文 `PROJECT_ROOT` 替换为本仓库绝对路径。自行创建 `planning` 与 `data/raw` 目录。Grocery使用框架自带文件。从 https://grouplens.org/datasets/movielens/1m/ 下载 `ml-1m.zip`，放在 `data/raw/ml-1m.zip`。不再分发原始及处理数据。

```text
python scripts/prepare_movielens.py --root PROJECT_ROOT
python scripts/audit_inputs.py --root PROJECT_ROOT --out PROJECT_ROOT/planning/input_audit.json
python scripts/audit_protocol.py --root PROJECT_ROOT
python scripts/test_patt.py --root PROJECT_ROOT
python scripts/smoke_baselines.py --root PROJECT_ROOT
```

数据准备核对官方压缩包MD5，且拒绝覆盖已有处理目录。需要重新处理时应先保存原目录。

## 完整实验

```text
python scripts/run_experiment_queue.py --root PROJECT_ROOT
python scripts/audit_predictions.py --root PROJECT_ROOT
python scripts/aggregate_final.py --root PROJECT_ROOT
python scripts/plot_validation.py --root PROJECT_ROOT
python scripts/plot_final_results.py --root PROJECT_ROOT
```

队列共40次。每模型、每数据集搜索学习率0.001与0.0001，调参种子14，仅用验证NDCG@20选择。随后固定学习率，以种子14、42、2026从头训练。共享嵌入64、历史30、batch256、Adam、dropout0.3、最多50轮、早停耐心10、一个训练负例。PAtt₂的λ=4，SASRec单层单头。详细规则见 `planning/正式实验协议_v1.md`。

每次运行保留配置、日志、权重和预测。相同名称不覆盖旧结果；完整运行核对配置后跳过，不完整运行停止并要求检查。状态文件短暂占用只重试元数据写入，不自动重跑失败训练。`PASS_PARTIAL`不表示完整验收，聚合要求24次正式结果齐全。图表使用Times New Roman，需要本机有该字体；生成后仍须目视检查。

单次试跑（不进入正式结果）：

```text
python scripts/run_rechorus.py --root PROJECT_ROOT --model PAtt2 --run-name example_grocery --stage pilot --epoch 1
```

SASRec替换模型参数为 `--model SASRec --num_heads 1`，GRU4Rec为 `--model GRU4Rec`。LC-PAtt₂使用 `--model PAtt2 --length_scale 1`。MovieLens额外指定 `--path PROJECT_ROOT/data/processed --dataset ML_1MTOPK`。

## 第一轮补充分析

原主表不变。历史长度分组和用户等权分析使用固定预测，属于事后诊断，不参与模型选择。Grocery上PAtt₂的总体优势主要来自短历史；MovieLens按用户等权时，LC-PAtt₂不再高于基础模型。分组样本数和三个种子的统计量见`analysis/round1/history_group_summary.csv`。

另完成6次前馈宽度对照：仅将PAtt₂的前馈中间宽度从4d改为d，固定原学习率，两个数据集各运行14、42、2026三个种子。独立复算、共享配置与候选行对齐全部通过。

| 数据集 | 窄前馈参数量 | NDCG@20（均值±样本标准差） |
|---|---:|---:|
| Grocery | 572,480 | 0.3699±0.0020 |
| MovieLens-1M | 214,848 | 0.4726±0.0061 |

两数据集的均值均略低于原PAtt₂。该对照未重新搜索学习率；与SASRec仍有位置编码、输入归一化及激活等差异，不是只替换注意力的消融。完整指标见`analysis/round1/width_control_audit.json`。中断的Grocery种子2026保留本地失败记录，按相同配置从头恢复；不把未完成运行计入结果。

完成主实验后运行：

```text
python scripts/analyze_history_groups.py --root PROJECT_ROOT
python scripts/plot_group_diagnostics.py --root PROJECT_ROOT
python scripts/test_width_control.py --root PROJECT_ROOT
python scripts/run_width_queue.py --root PROJECT_ROOT
python scripts/analyze_width_control.py --root PROJECT_ROOT
```

已有完整运行会在核对后跳过，不能同时启动多个队列。`PASS_PARTIAL`表示剩余运行尚未通过完整验收。前馈控制不修改原`implementation/PAtt2.py`。本轮协议见`planning/第一轮优化协议.md`。

## 比较范围

- 基础PAtt₂按论文公式独立重建，不是作者代码逐行运行。差异见 `planning/paper_implementation_audit.md`。
- MovieLens使用评分≥4、5-core、全局时间跨度划分、warm-start与99个无重复候选负例；不同于原文所有评分、10-core与留一法，不能直接比较绝对分数。
- Grocery主准确性保留框架重复候选，另做去重敏感性分析；多样性在去重列表计算。
- 使用滚动观测历史，较早验证/测试交互可进入更晚目标历史，不是固定训练历史评价。
- PAtt₂前馈宽度4d、框架SASRec为d；参数量不同，不能将差异全部归因于注意力。
- 两档学习率、三个种子不构成全局最优搜索，不据此提出显著性或线上效果结论。

## 来源和许可

ReChorus：https://github.com/THUwangcy/ReChorus ，MIT，固定提交 `c164ec4303cc20ddcfbd1b57de366a481811d1e5`。

作者参考代码：https://github.com/l-lyl/PAtt ，GPL-3.0，核查提交 `cefe8b639f9a03c7c4e4da515046909079b472a3`，不随本仓库打包。

不重新授权上游代码或数据。新增文件尚未另行授予开源许可，不将全部内容笼统标记MIT。数据使用须遵守原始来源条款。
