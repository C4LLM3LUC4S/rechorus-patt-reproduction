"""Generate report assets from the complete, independently audited final matrix."""
import argparse
import hashlib
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
import numpy as np


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    root = args.root
    audit = json.loads((root / 'analysis/prediction_audit.json').read_text())
    assert audit['status'] == 'PASS_COMPLETE' and audit['completed_runs_checked'] == 24
    source = root / 'analysis/final_metrics.json'
    rows = json.loads(source.read_text())
    index = {(r['dataset'], r['model'], r['metric']): r for r in rows}
    models = ['patt2', 'sasrec', 'gru4rec', 'lcpatt2']
    labels = ['PAtt2', 'SASRec', 'GRU4Rec', 'LC-PAtt2']
    colors = ['#0077BB', '#009988', '#777777', '#CC3311']
    font_manager.findfont('Times New Roman', fallback_to_default=False)
    plt.rcParams.update({'font.family': 'Times New Roman', 'font.size': 10,
                         'axes.spines.top': False, 'axes.spines.right': False,
                         'pdf.fonttype': 42, 'svg.fonttype': 'path', 'savefig.dpi': 220})
    destination = args.output or root / 'report/figures'
    destination.mkdir(parents=True, exist_ok=True)
    for filename, metrics in [('final_accuracy', ['HR@20', 'NDCG@20']),
                              ('final_diversity', ['CC_unique@20', 'ILD_Jaccard_unique@20'])]:
        fig, axes = plt.subplots(2, 2, figsize=(7, 5.2))
        for i, dataset in enumerate(['grocery', 'ml1m']):
            for j, metric in enumerate(metrics):
                ax = axes[i, j]
                data = [index[(dataset, m, metric)] for m in models]
                assert all(r['n_seeds'] == 3 for r in data)
                means = [r['mean'] for r in data]
                errors = [r['sample_std'] for r in data]
                bars = ax.bar(np.arange(4), means, yerr=errors, color=colors,
                              edgecolor='white', capsize=3, width=.65)
                for bar, hatch in zip(bars, ['', '//', '..', 'xx']):
                    bar.set_hatch(hatch)
                for x, r in enumerate(data):
                    samples = [r[f'seed{s}'] for s in [14, 42, 2026]]
                    ax.scatter(x + np.array([-.12, 0, .12]), samples, color='black', s=12, zorder=4)
                ax.set_xticks(range(4), labels, rotation=12)
                display_metric = metric.replace('_unique', '').replace('_Jaccard', '')
                ax.set_ylabel(display_metric)
                ax.set_title(('Grocery' if i == 0 else 'MovieLens-1M') + ' / ' + display_metric,
                             fontsize=10, loc='left')
                ax.set_ylim(0, min(1.05, max(m + s for m, s in zip(means, errors)) * 1.25 + .005))
                ax.grid(axis='y', alpha=.2)
                ax.set_axisbelow(True)
        fig.suptitle('Test results: mean +/- sample SD; dots = three seeds', fontsize=11)
        fig.tight_layout(rect=(0, 0, 1, .96))
        for ext in ['svg', 'png', 'pdf']:
            fig.savefig(destination / f'{filename}.{ext}', bbox_inches='tight')
        plt.close(fig)
    lines = ['# 正式实验结果表', '', '数值为三个随机种子的均值 ± 样本标准差；不代表置信区间或显著性检验。', '',
             '| 数据集 | 模型 | HR@5 | NDCG@5 | HR@20 | NDCG@20 |',
             '|---|---|---:|---:|---:|---:|']
    for dataset in ['grocery', 'ml1m']:
        for model, label in zip(models, labels):
            values = [index[(dataset, model, metric)] for metric in ['HR@5', 'NDCG@5', 'HR@20', 'NDCG@20']]
            lines.append('| ' + ' | '.join([dataset, label] + [f"{r['mean']:.4f} ± {r['sample_std']:.4f}" for r in values]) + ' |')
    (root / 'analysis/final_tables.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    (destination / 'final_figures_provenance.json').write_text(json.dumps({
        'metrics_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
        'audited_runs': 24, 'error_bars': 'sample standard deviation, n=3, not confidence intervals',
        'visual_review': 'pending'}, indent=2), encoding='utf-8')
    print('FINAL_FIGURES_CREATED: numerical gates passed; visual inspection still required')


if __name__ == '__main__':
    main()
