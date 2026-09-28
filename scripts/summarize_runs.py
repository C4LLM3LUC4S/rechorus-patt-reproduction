"""Generate a factual run inventory without mixing pilots and final runs."""
import argparse
import csv
import json
import re
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    args = parser.parse_args()
    rows = []
    for folder in sorted((args.root / 'runs').iterdir()):
        if not folder.is_dir() or not (folder / 'config.json').exists():
            continue
        config = json.loads((folder / 'config.json').read_text(encoding='utf-8'))
        log = (folder / 'train.log').read_text(encoding='utf-8') if (folder / 'train.log').exists() else ''
        completed = (folder / 'results.json').exists() and 'RUN_COMPLETED' in log and (folder / 'best.pt').exists()
        result = json.loads((folder / 'results.json').read_text(encoding='utf-8')) if completed else {}
        best = re.search(r'Best Iter\(dev\)=\s*(\d+)', log)
        rows.append({'run': folder.name, 'stage': config.get('stage', 'pilot'), 'model': config['model'],
                     'dataset': config['dataset'], 'seed': config['random_seed'], 'lr': config['lr'],
                     'status': 'completed' if completed else 'incomplete',
                     'best_epoch': best.group(1) if best else '',
                     'dev_ndcg20': result.get('dev', {}).get('NDCG@20', ''),
                     'test_ndcg20': result.get('test', {}).get('NDCG@20', ''),
                     'elapsed_seconds': result.get('elapsed_seconds', '')})
    target = args.root / 'planning/run_inventory.csv'
    with target.open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]) if rows else ['run'])
        writer.writeheader()
        writer.writerows(rows)
    print(json.dumps(rows, indent=2))


if __name__ == '__main__':
    main()
