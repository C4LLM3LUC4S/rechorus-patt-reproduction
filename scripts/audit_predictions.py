"""Recompute completed-run accuracy from saved predictions, without training imports."""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
import numpy as np


def metrics(ranks):
    return {f'{metric}@{k}': float(np.mean((ranks <= k) /
            (np.log2(ranks + 1) if metric == 'NDCG' else 1)))
            for k in (5, 20) for metric in ('HR', 'NDCG')}


def audit(folder, phase):
    with np.load(folder / f'{phase}_predictions.npz', allow_pickle=False) as data:
        scores, ids, users = data['scores'], data['item_id'], data['user_id']
    assert scores.shape == ids.shape and len(users) == len(scores)
    assert scores.ndim == 2 and scores.shape[1] == 100 and len(scores) > 0
    assert np.isfinite(scores).all() and (ids > 0).all()
    # Independent sorting implementation of the framework's pessimistic ties.
    ranks = np.array([len(row) - np.searchsorted(np.sort(row), row[0], side='left')
                      for row in scores])
    recalculated = metrics(ranks)
    reported = json.loads((folder / 'results.json').read_text(encoding='utf-8'))[phase]
    errors = {key: abs(value - reported[key]) for key, value in recalculated.items()}
    assert max(errors.values()) < 1e-12, (folder.name, phase, errors)
    unique_ranks, duplicates, max_score_disagreement = [], 0, 0.0
    for row, candidates in zip(scores, ids):
        unique, first = np.unique(candidates, return_index=True)
        assert np.count_nonzero(candidates == candidates[0]) == 1
        duplicates += int(len(unique) != len(candidates))
        for item in unique:
            repeated = row[candidates == item]
            if len(repeated) > 1:
                max_score_disagreement = max(max_score_disagreement, float(np.ptp(repeated)))
        unique_ranks.append(int(np.sum(row[first] >= row[0])))
    assert max_score_disagreement < 1e-5
    return {'run': folder.name, 'phase': phase, 'examples': len(scores),
            'unique_users': len(np.unique(users)), 'max_absolute_error': max(errors.values()),
            'duplicate_candidate_rows': duplicates,
            'duplicate_score_max_difference': max_score_disagreement,
            'framework_accuracy': recalculated,
            'deduplicated_accuracy_sensitivity': metrics(np.asarray(unique_ranks)),
            'negative_ties_with_positive': int(np.sum(scores[:, 1:] == scores[:, :1]))}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    args = parser.parse_args()
    records, pending = [], []
    for dataset in ('grocery', 'ml1m'):
        for model in ('patt2', 'sasrec', 'gru4rec', 'lcpatt2'):
            for seed in (14, 42, 2026):
                folder = args.root / 'runs' / f'final_{dataset}_{model}_s{seed}'
                if not (folder / 'results.json').exists():
                    pending.append(folder.name)
                    continue
                if 'RUN_COMPLETED' not in (folder / 'train.log').read_text(encoding='utf-8'):
                    pending.append(folder.name)
                    continue
                records.extend(audit(folder, phase) for phase in ('dev', 'test'))
    destination = args.root / 'analysis'
    destination.mkdir(exist_ok=True)
    output = {'status': 'PASS_COMPLETE' if not pending else 'PASS_PARTIAL',
              'checked_utc': datetime.now(timezone.utc).isoformat(),
              'completed_runs_checked': len(records) // 2, 'expected_runs': 24,
              'pending': pending, 'records': records,
              'note': 'Deduplicated scores are a sensitivity analysis, not the frozen primary metric.'}
    (destination / 'prediction_audit.json').write_text(json.dumps(output, indent=2), encoding='utf-8')
    print(output['status'], 'completed runs checked:', len(records) // 2, 'pending:', len(pending))


if __name__ == '__main__':
    main()
