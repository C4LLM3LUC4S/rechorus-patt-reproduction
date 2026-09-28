"""Audit all six width controls before generating supplementary result tables."""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
from audit_predictions import audit


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    source_hashes = {key: hashlib.sha256((root / path).read_bytes()).hexdigest()
                     for key, path in {
                         'patt_sha256': 'implementation/PAtt2.py',
                         'entry_sha256': 'scripts/run_rechorus.py',
                         'control_source_sha256': 'scripts/run_width_control.py',
                     }.items()}
    shared_fields = ['dataset', 'epoch', 'early_stop', 'lr', 'l2', 'batch_size',
                     'optimizer', 'emb_size', 'num_layers', 'patt_lambda',
                     'length_scale', 'history_max', 'num_neg', 'dropout',
                     'main_metric', 'random_seed', 'data_sha256', 'patt_sha256',
                     'entry_sha256', 'diversity_sha256']
    records, summary, missing = [], [], []
    for ds in ['grocery', 'ml1m']:
        data = []
        for seed in [14, 42, 2026]:
            folder = root / 'runs' / f'width_{ds}_patt2ff1_s{seed}'
            if not (folder / 'results.json').exists():
                missing.append(folder.name)
                continue
            assert 'RUN_COMPLETED' in (folder / 'train.log').read_text()
            config = json.loads((folder / 'config.json').read_text())
            assert config['ff_multiplier'] == 1 and config['stage'] == 'final'
            assert config['lr'] == (.0001 if ds == 'grocery' else .001)
            assert config['random_seed'] == seed and config['length_scale'] == 0
            assert all(config[key] == value for key, value in source_hashes.items())
            baseline = root / 'runs' / f'final_{ds}_patt2_s{seed}'
            original = json.loads((baseline / 'config.json').read_text())
            for key in shared_fields:
                assert config[key] == original[key], (folder.name, key)
            result = json.loads((folder / 'results.json').read_text())
            assert result['parameters'] == (572480 if ds == 'grocery' else 214848)
            for phase in ['dev', 'test']:
                with np.load(folder / f'{phase}_predictions.npz', allow_pickle=False) as current, \
                     np.load(baseline / f'{phase}_predictions.npz', allow_pickle=False) as reference:
                    for key in ['user_id', 'item_id']:
                        assert np.array_equal(current[key], reference[key]), (folder.name, phase, key)
                record = audit(folder, phase)
                record['candidate_alignment_to_original'] = True
                record['shared_configuration_match'] = True
                records.append(record)
            data.append(result)
        if len(data) == 3:
            summary.append({'dataset': ds, 'model': 'PAtt2-FF1', 'seeds': [14, 42, 2026],
                            'parameters': data[0]['parameters'],
                            'metrics': {key: {'mean': float(np.mean([v['test'][key] for v in data])),
                                              'sample_std': float(np.std([v['test'][key] for v in data], ddof=1)),
                                              'values': [v['test'][key] for v in data]}
                                        for key in ['HR@5', 'NDCG@5', 'HR@20', 'NDCG@20']}})
    destination = root / 'analysis/round1'
    destination.mkdir(parents=True, exist_ok=True)
    result = {'status': 'PASS_COMPLETE' if not missing else 'PASS_PARTIAL', 'expected_runs': 6,
              'audited_runs': len(records) // 2, 'missing': missing, 'records': records, 'summary': summary,
              'verified_source_hashes': source_hashes,
              'matched_configuration_fields': shared_fields,
              'scope': 'Fixed original learning rates; supplementary width sensitivity, not retuned optimum.'}
    (destination / 'width_control_audit.json').write_text(json.dumps(result, indent=2))
    print(result['status'], result['audited_runs'], '/', 6)
    if missing:
        return 2
    lines = ['# 前馈宽度对照', '', '固定原PAtt2学习率；三种子均值±样本标准差；独立复算通过。', '',
             '| 数据集 | 参数量 | HR@5 | NDCG@5 | HR@20 | NDCG@20 |', '|---|---:|---:|---:|---:|---:|']
    for item in summary:
        numbers = [f"{value['mean']:.4f}±{value['sample_std']:.4f}" for value in item['metrics'].values()]
        lines.append('| ' + ' | '.join([item['dataset'], str(item['parameters'])] + numbers) + ' |')
    (destination / 'width_control_table.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print('\n'.join(lines))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
