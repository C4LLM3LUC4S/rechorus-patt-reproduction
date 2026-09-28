"""Six supplementary runs; preserve completed records and stop on any failure."""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from run_experiment_queue import save


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    status_path = root / 'planning/width_queue_status.json'
    state = {'status': 'running', 'pid': os.getpid(), 'completed': [], 'active': None, 'total': 6,
             'timeout_seconds_per_run': 3600, 'started_unix': time.time()}
    frozen = {p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in
              ['implementation/PAtt2.py', 'scripts/run_rechorus.py', 'scripts/run_width_control.py']}
    state['frozen'] = frozen
    save(status_path, state)
    try:
        for dataset, full, path, lr in [('grocery', 'Grocery_and_Gourmet_Food', root / 'sources/ReChorus/data', .0001),
                                        ('ml1m', 'ML_1MTOPK', root / 'data/processed', .001)]:
            for seed in [14, 42, 2026]:
                name = f'width_{dataset}_patt2ff1_s{seed}'
                assert all(hashlib.sha256((root / p).read_bytes()).hexdigest() == h for p, h in frozen.items())
                run = root / 'runs' / name
                if run.exists():
                    config = json.loads((run / 'config.json').read_text())
                    result = json.loads((run / 'results.json').read_text())
                    assert config['ff_multiplier'] == 1 and config['lr'] == lr and config['random_seed'] == seed
                    assert config['control_source_sha256'] == frozen['scripts/run_width_control.py']
                    assert 'RUN_COMPLETED' in (run / 'train.log').read_text()
                    assert 'test' in result and (run / 'test_predictions.npz').exists()
                else:
                    state['active'] = name
                    cmd = [sys.executable, str(root / 'scripts/run_width_control.py'), '--root', str(root),
                           '--model', 'PAtt2', '--run-name', name, '--stage', 'final', '--random-seed', str(seed),
                           '--path', str(path), '--dataset', full, '--epoch', '50', '--early_stop', '10',
                           '--lr', str(lr), '--l2', '0', '--num_layers', '1', '--patt_lambda', '4']
                    with (root / 'planning' / f'{name}.console.log').open('w', encoding='utf-8') as log:
                        child = subprocess.Popen(cmd, cwd=root, stdout=log, stderr=subprocess.STDOUT)
                        state['child_pid'] = child.pid
                        save(status_path, state)
                        try:
                            code = child.wait(timeout=3600)
                        except subprocess.TimeoutExpired:
                            child.kill()
                            child.wait()
                            raise RuntimeError(f'Hard timeout: {name}')
                        if code != 0:
                            raise RuntimeError(f'{name}: exit {code}; no automatic retry')
                    assert 'RUN_COMPLETED' in (run / 'train.log').read_text()
                state['completed'].append(name)
                save(status_path, state)
        state['status'] = 'completed'
        state['active'] = None
    except Exception as error:
        state['status'] = 'failed'
        state['error'] = str(error)
        raise
    finally:
        state['updated_unix'] = time.time()
        save(status_path, state)


if __name__ == '__main__':
    main()
