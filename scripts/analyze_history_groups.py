"""Post-hoc descriptive groups, aligned to the original saved candidate rows."""
import argparse
import json
import sys
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import pandas as pd


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    sys.path.insert(0, str(root / 'sources/ReChorus/src'))
    from helpers.SeqReader import SeqReader
    rows, populations = [], []
    bins = [(1, 5), (6, 10), (11, 20), (21, 30)]
    for ds, full, path in [('grocery', 'Grocery_and_Gourmet_Food', root / 'sources/ReChorus/data'),
                           ('ml1m', 'ML_1MTOPK', root / 'data/processed')]:
        corpus = SeqReader(SimpleNamespace(path=str(path), dataset=full, sep='\t'))
        frame = corpus.data_df['test'].query('position > 0').reset_index(drop=True)
        lengths = np.minimum(frame.position.to_numpy(), 30)
        expected = np.concatenate([frame.item_id.to_numpy()[:, None], np.asarray(frame.neg_items.tolist())], axis=1)
        users = frame.user_id.to_numpy()
        for lo, hi in bins:
            mask = (lengths >= lo) & (lengths <= hi)
            populations.append({'dataset': ds, 'group': f'{lo}-{hi}', 'n_rows': int(mask.sum()),
                                'n_users': int(len(np.unique(users[mask])))})
        for model in ['patt2', 'sasrec', 'gru4rec', 'lcpatt2']:
            for seed in [14, 42, 2026]:
                run = root / 'runs' / f'final_{ds}_{model}_s{seed}'
                with np.load(run / 'test_predictions.npz') as saved:
                    assert np.array_equal(saved['user_id'], users)
                    assert np.array_equal(saved['item_id'], expected)
                    scores = saved['scores']
                ranks = (scores >= scores[:, :1]).sum(axis=1)
                values = (ranks <= 20) / np.log2(ranks + 1)
                reported = json.loads((run / 'results.json').read_text())['test']['NDCG@20']
                assert abs(values.mean() - reported) < 1e-12
                weighted_sum = 0.0
                for lo, hi in bins:
                    mask = (lengths >= lo) & (lengths <= hi)
                    mean = float(values[mask].mean()) if mask.any() else None
                    rows.append({'dataset': ds, 'model': model, 'seed': seed, 'group': f'{lo}-{hi}',
                                 'n': int(mask.sum()), 'ndcg20': mean})
                    if mean is not None:
                        weighted_sum += mask.sum() * mean
                assert abs(weighted_sum / len(values) - reported) < 1e-12
                macro = pd.DataFrame({'user': users, 'ndcg': values}).groupby('user').ndcg.mean().mean()
                rows.append({'dataset': ds, 'model': model, 'seed': seed, 'group': 'user-macro',
                             'n': int(len(np.unique(users))), 'ndcg20': float(macro)})
    destination = root / 'analysis/round1'
    destination.mkdir(parents=True, exist_ok=True)
    table = pd.DataFrame(rows)
    summary = table.groupby(['dataset', 'model', 'group'], sort=False).agg(
        mean=('ndcg20', 'mean'), sample_std=('ndcg20', 'std'), n=('n', 'first')).reset_index()
    table.to_csv(destination / 'history_group_seeds.csv', index=False)
    summary.to_csv(destination / 'history_group_summary.csv', index=False)
    (destination / 'history_group_populations.json').write_text(json.dumps(populations, indent=2))
    print(summary.to_string(index=False))
    print('HISTORY_GROUP_PASS: 24 candidate matrices aligned; grouped means recover original totals')


if __name__ == '__main__':
    main()
