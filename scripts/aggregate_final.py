"""Summarize only a complete, three-seed final matrix. Never include pilots."""
import argparse
import csv
import json
import math
import statistics
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    args = parser.parse_args()
    rows, missing = [], []
    for dataset in ['grocery', 'ml1m']:
        for model in ['patt2', 'sasrec', 'gru4rec', 'lcpatt2']:
            values = []
            for seed in [14, 42, 2026]:
                folder = args.root / 'runs' / f'final_{dataset}_{model}_s{seed}'
                if not (folder / 'results.json').exists():
                    missing.append(folder.name)
                    continue
                config = json.loads((folder / 'config.json').read_text(encoding='utf-8'))
                assert config['stage'] == 'final' and config['random_seed'] == seed
                assert 'RUN_COMPLETED' in (folder / 'train.log').read_text(encoding='utf-8')
                result = json.loads((folder / 'results.json').read_text(encoding='utf-8'))
                metrics = {**result['test'], **result['test_diversity']}
                assert all(math.isfinite(float(v)) for v in metrics.values())
                values.append(metrics)
            if len(values) != 3:
                continue
            for metric in values[0]:
                samples = [v[metric] for v in values]
                rows.append({'dataset': dataset, 'model': model, 'metric': metric,
                             'n_seeds': 3, 'mean': statistics.mean(samples),
                             'sample_std': statistics.stdev(samples),
                             'seed14': samples[0], 'seed42': samples[1], 'seed2026': samples[2]})
    if missing:
        print(json.dumps({'status': 'NOT_READY', 'missing_runs': missing}, indent=2))
        return 2
    destination = args.root / 'analysis'
    destination.mkdir(exist_ok=True)
    with (destination / 'final_metrics.csv').open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (destination / 'final_metrics.json').write_text(json.dumps(rows, indent=2), encoding='utf-8')
    print('FINAL_MATRIX_AGGREGATED: 24 runs, 3 seeds per model/dataset')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
