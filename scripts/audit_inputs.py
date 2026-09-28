"""Read-only source/data audit; writes only the specified JSON report."""
import argparse
import ast
import hashlib
import json
import platform
from pathlib import Path

import numpy as np
import pandas as pd
import torch


def audit_data(folder):
    frames = {s: pd.read_csv(folder / (s + '.csv'), sep='\t')
              for s in ('train', 'dev', 'test')}
    all_df = pd.concat(frames.values(), ignore_index=True)
    max_item = int(all_df.item_id.max())
    clicked = all_df.groupby('user_id').item_id.agg(set).to_dict()
    result = {'rows': {s: len(df) for s, df in frames.items()},
              'users': int(all_df.user_id.nunique()),
              'items': int(all_df.item_id.nunique()),
              'duplicate_user_item_time': int(all_df.duplicated(['user_id', 'item_id', 'time']).sum()),
              'files_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                               for p in sorted(folder.glob('*.csv'))}}
    for phase in ('dev', 'test'):
        counts, repeats, positive_overlap, invalid = [], 0, 0, 0
        for row in frames[phase].itertuples():
            ids = ast.literal_eval(row.neg_items)
            counts.append(len(ids))
            repeats += int(len(set(ids)) != len(ids))
            positive_overlap += int(bool(set(ids) & clicked[row.user_id]))
            invalid += int(any(i < 1 or i > max_item for i in ids))
        result[phase + '_candidates'] = {
            'negative_counts': sorted(set(counts)), 'rows_with_duplicate_negatives': repeats,
            'rows_with_known_positive_negative': positive_overlap,
            'rows_with_out_of_range_negative': invalid}
    train_max = frames['train'].groupby('user_id').time.max()
    dev_min = frames['dev'].groupby('user_id').time.min()
    dev_max = frames['dev'].groupby('user_id').time.max()
    test_min = frames['test'].groupby('user_id').time.min()
    result['train_after_dev_users'] = int((train_max > dev_min.reindex(train_max.index)).sum())
    result['dev_after_test_users'] = int((dev_max > test_min.reindex(dev_max.index)).sum())
    result['train_dev_equal_time_users'] = int((train_max == dev_min.reindex(train_max.index)).sum())
    result['dev_test_equal_time_users'] = int((dev_max == test_min.reindex(dev_max.index)).sum())
    meta = pd.read_csv(folder / 'item_meta.csv', sep='\t')
    result['metadata'] = {'rows': len(meta), 'categories': int(meta.i_category.nunique()),
                          'missing_interacted_items': len(set(all_df.item_id) - set(meta.item_id))}
    return result


def audit_determinants():
    torch.manual_seed(24334094)
    q = torch.randn(3, 10, 16, dtype=torch.float64).square()
    kernel = q @ q.transpose(-1, -2)
    eps = 1e-5
    ref = torch.stack([torch.linalg.det(kernel[:, [i, j]][:, :, [i, j]] + eps * torch.eye(2))
                       for i in range(10) for j in range(10)], dim=1).reshape(3, 10, 10)
    diagonal = kernel.diagonal(dim1=-2, dim2=-1) + eps
    fast = diagonal[:, :, None] * diagonal[:, None, :] - kernel * kernel.transpose(-1, -2)
    diff = float((ref - fast).abs().max())
    assert torch.allclose(ref, fast, atol=1e-9, rtol=1e-10)
    try:
        torch.triu(ref.reshape(3, -1)[0], diagonal=1)
        behavior = 'accepted'
    except RuntimeError as exc:
        behavior = str(exc)
    return {'dtype': 'float64', 'shape': [3, 10, 16], 'max_abs_error_closed_form': diff,
            'upstream_flattened_triu_behavior': behavior,
            'note': 'Algebra-only check. Does not validate paper fidelity or model performance.'}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    report = {'environment': {'python': platform.python_version(), 'torch': torch.__version__,
                              'numpy': np.__version__, 'pandas': pd.__version__,
                              'cuda_available': torch.cuda.is_available()},
              'grocery': audit_data(args.root / 'sources/ReChorus/data/Grocery_and_Gourmet_Food'),
              'determinants': audit_determinants()}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
