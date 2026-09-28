"""Plot selected tuning histories; never substitute these for final test results."""
import argparse
import csv
import hashlib
import json
import re
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', required=True, type=Path)
    args = parser.parse_args()
    root = args.root
    selected = json.loads((root / 'planning/selected_learning_rates.json').read_text())
    font_path = font_manager.findfont('Times New Roman', fallback_to_default=False)
    plt.rcParams.update({'font.family': 'Times New Roman', 'font.size': 10,
                         'axes.titlesize': 12, 'axes.labelsize': 11,
                         'axes.spines.top': False, 'axes.spines.right': False,
                         'svg.fonttype': 'path', 'savefig.dpi': 220})
    models = [('patt2', 'PAtt2', '#0077BB', 'o', '-'),
              ('sasrec', 'SASRec', '#009988', 's', '--'),
              ('gru4rec', 'GRU4Rec', '#777777', '^', '-.'),
              ('lcpatt2', 'LC-PAtt2', '#CC3311', 'D', ':')]
    fig, axes = plt.subplots(1, 2, figsize=(7.0, 3.35), sharey=True)
    rows, sources = [], []
    for ax, ds, full, title in zip(axes, ['grocery', 'ml1m'],
                                 ['Grocery_and_Gourmet_Food', 'ML_1MTOPK'],
                                 ['(a) Grocery', '(b) MovieLens-1M']):
        for model, label, color, marker, style in models:
            lr = selected[f'{full}/{model}']
            tag = '1e3' if lr == .001 else '1e4'
            folder = root / 'runs' / f'tune_{ds}_{model}_lr{tag}_s14'
            log = (folder / 'train.log').read_text(encoding='utf-8')
            config = json.loads((folder / 'config.json').read_text())
            result = json.loads((folder / 'results.json').read_text())
            assert config['stage'] == 'tune' and config['lr'] == lr
            assert config['random_seed'] == 14 and 'test' not in result
            assert 'RUN_COMPLETED' in log
            points = [(int(epoch), float(value)) for epoch, value in re.findall(
                r'Epoch\s+(\d+)\s+loss=.*?dev=\([^\n]*?NDCG@20:([\d.]+)', log)]
            assert points and len({p[0] for p in points}) == len(points)
            assert abs(max(v for _, v in points) - result['dev']['NDCG@20']) < 0.000051
            x, y = zip(*points)
            ax.plot(x, y, color=color, marker=marker, linestyle=style, linewidth=1.3,
                    markersize=3.3, markevery=7, label=label)
            rows.extend({'dataset': ds, 'model': model, 'learning_rate': lr,
                         'seed': 14, 'epoch': epoch, 'validation_ndcg20': value}
                        for epoch, value in points)
            sources.append({'run': folder.name, 'log_sha256': hashlib.sha256(
                (folder / 'train.log').read_bytes()).hexdigest()})
        ax.set_title(title, loc='left', fontweight='bold')
        ax.set_xlabel('Epoch')
        ax.set_xlim(1, 50)
        ax.set_ylim(0, 0.65)
        ax.grid(axis='y', color='#dddddd', linewidth=.5)
    axes[0].set_ylabel('Validation NDCG@20')
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc='lower center', ncol=4, frameon=False,
               bbox_to_anchor=(.5, -.005))
    fig.tight_layout(rect=(0, .10, 1, 1))
    destination = root / 'report/figures'
    destination.mkdir(parents=True, exist_ok=True)
    for extension in ['svg', 'png']:
        fig.savefig(destination / f'validation_convergence.{extension}', bbox_inches='tight')
    plt.close(fig)
    with (destination / 'validation_convergence.csv').open('w', encoding='utf-8', newline='') as out:
        writer = csv.DictWriter(out, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (destination / 'validation_convergence_provenance.json').write_text(json.dumps({
        'scope': 'selected learning-rate tuning runs, seed 14, validation only',
        'precision': 'four decimal places from training logs', 'font_file': font_path,
        'sources': sources}, indent=2), encoding='utf-8')
    print('VALIDATION_FIGURE_CREATED', len(rows), 'logged epoch points, 8 complete tuning runs')


if __name__ == '__main__':
    main()
