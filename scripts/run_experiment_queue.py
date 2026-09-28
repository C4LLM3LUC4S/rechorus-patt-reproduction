"""Serial, fail-fast execution of the frozen two-dataset experiment protocol."""
import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


def stamp():
    return datetime.now(timezone.utc).isoformat()


def save(path, value):
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value, indent=2), encoding='utf-8')
    # Windows readers/security scanners can briefly deny atomic replacement.
    # Retry only this metadata operation; never retry a failed training process.
    for attempt in range(40):
        try:
            temp.replace(path)
            return
        except PermissionError:
            if attempt == 39:
                raise
            time.sleep(.25)


def result_if_valid(folder, expected, patt_hash):
    if not folder.exists():
        return None
    for name in ['config.json', 'results.json', 'best.pt', 'train.log']:
        if not (folder / name).exists():
            raise RuntimeError(f'Incomplete existing run, manual review required: {folder}')
    config = json.loads((folder / 'config.json').read_text(encoding='utf-8'))
    for key, value in expected.items():
        if config.get(key) != value:
            raise RuntimeError(f'Configuration mismatch in {folder.name}: {key}')
    if config['patt_sha256'] != patt_hash:
        raise RuntimeError(f'Model source changed since {folder.name}')
    result = json.loads((folder / 'results.json').read_text(encoding='utf-8'))
    if 'RUN_COMPLETED' not in (folder / 'train.log').read_text(encoding='utf-8'):
        raise RuntimeError(f'Missing completion marker: {folder}')
    if not math.isfinite(result['dev']['NDCG@20']):
        raise RuntimeError(f'Non-finite validation metric: {folder}')
    if expected['stage'] == 'tune' and 'test' in result:
        raise RuntimeError('Tuning run unexpectedly evaluated the test set')
    if expected['stage'] == 'final':
        if not math.isfinite(result['test']['NDCG@20']):
            raise RuntimeError('Non-finite test metric')
        for name in ['dev_predictions.npz', 'test_predictions.npz']:
            if not (folder / name).exists():
                raise RuntimeError(f'Missing predictions: {folder}')
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--timeout-seconds', type=int, default=3600)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    root = args.root.resolve()
    models = [('patt2', 'PAtt2', []), ('sasrec', 'SASRec', ['--num_heads', '1']),
              ('gru4rec', 'GRU4Rec', []), ('lcpatt2', 'PAtt2', ['--length_scale', '1'])]
    datasets = [('grocery', 'Grocery_and_Gourmet_Food', root / 'sources/ReChorus/data'),
                ('ml1m', 'ML_1MTOPK', root / 'data/processed')]
    if args.dry_run:
        print(json.dumps({'tuning_runs': 16, 'final_runs': 24,
                          'datasets': [x[1] for x in datasets], 'models': [x[0] for x in models],
                          'seeds': [14, 42, 2026], 'learning_rates': [.001, .0001]}, indent=2))
        return
    state_path = root / 'planning/queue_status.json'
    lock = root / 'planning/queue.lock'
    handle = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.write(handle, str(os.getpid()).encode())
    os.close(handle)
    frozen_files = [root / 'implementation/PAtt2.py', root / 'scripts/run_rechorus.py',
                    root / 'scripts/diversity_metrics.py']
    frozen = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in frozen_files}
    patt_hash = frozen[str(root / 'implementation/PAtt2.py')]
    state = {'status': 'running', 'pid': os.getpid(), 'started_utc': stamp(),
             'total_runs': 40, 'completed_runs': [], 'active_run': None, 'frozen_code': frozen}
    child = None
    selections = {}

    def run(stage, ds_short, dataset, data_path, short, model, extra, lr, seed):
        nonlocal child
        for path, digest in frozen.items():
            if hashlib.sha256(Path(path).read_bytes()).hexdigest() != digest:
                raise RuntimeError('Source modified while queue was running: ' + path)
        tag = '1e3' if lr == .001 else '1e4'
        name = (f'tune_{ds_short}_{short}_lr{tag}_s{seed}' if stage == 'tune'
                else f'final_{ds_short}_{short}_s{seed}')
        folder = root / 'runs' / name
        expected = {'stage': stage, 'dataset': dataset, 'model': model, 'lr': lr,
                    'random_seed': seed, 'epoch': 50, 'batch_size': 256, 'history_max': 30,
                    'dropout': .3, 'emb_size': 64, 'early_stop': 10}
        if model == 'PAtt2':
            expected.update(length_scale=int(short == 'lcpatt2'), patt_lambda=4.0, num_layers=1)
        if model == 'SASRec':
            expected.update(num_heads=1, num_layers=1)
        result = result_if_valid(folder, expected, patt_hash)
        state.update(active_run=name, updated_utc=stamp())
        save(state_path, state)
        if result is None:
            cmd = [sys.executable, str(root / 'scripts/run_rechorus.py'), '--root', str(root),
                   '--path', str(data_path), '--dataset', dataset, '--model', model,
                   '--run-name', name, '--stage', stage, '--epoch', '50', '--lr', str(lr),
                   '--random-seed', str(seed)] + extra
            print('START ' + name, flush=True)
            console_path = root / 'planning' / (name + '.console.log')
            with console_path.open('x', encoding='utf-8') as console:
                child = subprocess.Popen(cmd, stdout=console, stderr=subprocess.STDOUT,
                                         cwd=root, env={**os.environ, 'PYTHONIOENCODING': 'utf-8'})
                start = time.monotonic()
                while child.poll() is None:
                    elapsed = time.monotonic() - start
                    state.update(child_pid=child.pid, elapsed_seconds=elapsed, updated_utc=stamp())
                    save(state_path, state)
                    if elapsed > args.timeout_seconds:
                        print('HARD_TIMEOUT ' + name, flush=True)
                        child.kill()
                        child.wait()
                        raise TimeoutError(name)
                    time.sleep(10)
                if child.returncode:
                    raise RuntimeError(f'Run failed ({child.returncode}): {name}; see {console_path}')
            result = result_if_valid(folder, expected, patt_hash)
        state['completed_runs'].append(name)
        state.update(active_run=None, updated_utc=stamp())
        save(state_path, state)
        print('DONE ' + name, flush=True)
        return result

    try:
        for ds_short, dataset, data_path in datasets:
            for short, model, extra in models:
                candidates = [(lr, run('tune', ds_short, dataset, data_path, short, model, extra, lr, 14))
                              for lr in [.001, .0001]]
                # List order resolves exact ties in favor of .001.
                chosen = max(candidates, key=lambda x: x[1]['dev']['NDCG@20'])[0]
                selections[dataset + '/' + short] = chosen
                save(root / 'planning/selected_learning_rates.json', selections)
        for ds_short, dataset, data_path in datasets:
            for short, model, extra in models:
                for seed in [14, 42, 2026]:
                    run('final', ds_short, dataset, data_path, short, model, extra,
                        selections[dataset + '/' + short], seed)
        state.update(status='completed', active_run=None, finished_utc=stamp())
        print('EXPERIMENT_QUEUE_COMPLETED', flush=True)
    except BaseException as exc:
        if child is not None and child.poll() is None:
            child.terminate()
            child.wait()
        state.update(status='failed', error=repr(exc), finished_utc=stamp())
        raise
    finally:
        save(state_path, state)
        lock.unlink()


if __name__ == '__main__':
    main()
