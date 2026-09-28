"""Plot descriptive history groups and user-weight sensitivity without retraining."""
import argparse
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    args = parser.parse_args()
    root = args.root
    groups = pd.read_csv(root / 'analysis/round1/history_group_summary.csv')
    totals = pd.read_json(root / 'analysis/final_metrics.json')
    plt.rcParams.update({'font.family': 'Times New Roman', 'font.size': 10,
                         'pdf.fonttype': 42, 'svg.fonttype': 'path',
                         'axes.spines.top': False, 'axes.spines.right': False})
    models = ['patt2', 'sasrec', 'gru4rec', 'lcpatt2']
    labels = ['PAtt2', 'SASRec', 'GRU4Rec', 'LC-PAtt2']
    colors = ['#0077BB', '#009988', '#777777', '#CC3311']
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 3.25))
    order = ['1-5', '6-10', '11-20', '21-30']
    for model, label, color, marker in zip(models, labels, colors, ['o', 's', '^', 'D']):
        part = groups[(groups.dataset == 'grocery') & (groups.model == model)].set_index('group').loc[order]
        axes[0].errorbar(range(4), part['mean'], yerr=part.sample_std, label=label,
                         color=color, marker=marker, capsize=2, markersize=4, linewidth=1.2)
    axes[0].set_xticks(range(4), ['1-5\n(n=6,724)', '6-10\n(n=4,745)', '11-20\n(n=2,069)', '21-30\n(n=1,143)'], fontsize=8.5)
    axes[0].set_xlabel('Effective history length')
    axes[0].set_ylabel('Test NDCG@20')
    axes[0].set_ylim(.24, .48)
    axes[0].set_title('(a) Grocery: history groups', loc='left', fontweight='bold', fontsize=11)
    axes[0].legend(frameon=False, fontsize=8, ncol=2, loc='upper left')
    x = np.arange(4)
    for offset, group, color, label, marker in [(-.1, 'interaction', '#0077BB', 'Per interaction', 'o'),
                                                (.1, 'user', '#CC3311', 'Per user', 's')]:
        if group == 'interaction':
            selected = totals[(totals.dataset == 'ml1m') & (totals.metric == 'NDCG@20')].set_index('model').loc[models]
        else:
            selected = groups[(groups.dataset == 'ml1m') & (groups.group == 'user-macro')].set_index('model').loc[models]
        axes[1].errorbar(x + offset, selected['mean'], yerr=selected.sample_std,
                         fmt=marker, capsize=3, label=label, color=color, markersize=5)
    axes[1].set_xticks(x, labels, rotation=15, fontsize=9)
    axes[1].set_ylabel('Test NDCG@20')
    axes[1].set_ylim(.35, .51)
    axes[1].set_title('(b) MovieLens-1M: weighting', loc='left', fontweight='bold', fontsize=11)
    axes[1].legend(frameon=False, fontsize=9, loc='upper right')
    for ax in axes:
        ax.grid(axis='y', alpha=.2)
    fig.tight_layout()
    target = root / 'report/round1'
    for ext in ['pdf', 'png', 'svg']:
        fig.savefig(target / f'group_diagnostics.{ext}', dpi=220, bbox_inches='tight')
    print('GROUP_DIAGNOSTIC_FIGURE_CREATED')


if __name__ == '__main__':
    main()
