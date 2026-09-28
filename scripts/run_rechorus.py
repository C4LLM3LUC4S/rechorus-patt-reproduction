"""Small entry point using ReChorus readers, datasets, models and BaseRunner."""
import argparse
import hashlib
import json
import logging
import sys
import time
from pathlib import Path
import numpy as np
import torch


def main():
    first = argparse.ArgumentParser(add_help=False)
    first.add_argument('--root', type=Path, required=True)
    first.add_argument('--model', choices=['PAtt2', 'SASRec', 'GRU4Rec'], required=True)
    first.add_argument('--run-name', required=True)
    first.add_argument('--random-seed', type=int, default=14)
    first.add_argument('--threads', type=int, default=4)
    first.add_argument('--stage', choices=['pilot', 'tune', 'final'], default='pilot')
    known, _ = first.parse_known_args()
    sys.path[:0] = [str(known.root / 'sources/ReChorus/src'), str(known.root / 'implementation')]
    from helpers.SeqReader import SeqReader
    from helpers.BaseRunner import BaseRunner
    from models.sequential.SASRec import SASRec
    from models.sequential.GRU4Rec import GRU4Rec
    from PAtt2 import PAtt2
    from utils import utils
    cls = {'PAtt2': PAtt2, 'SASRec': SASRec, 'GRU4Rec': GRU4Rec}[known.model]
    parser = argparse.ArgumentParser(parents=[first])
    SeqReader.parse_data_args(parser)
    BaseRunner.parse_runner_args(parser)
    cls.parse_model_args(parser)
    parser.set_defaults(path=str(known.root / 'sources/ReChorus/data'), epoch=1, num_workers=0,
                        history_max=30, dropout=0.3, main_metric='NDCG@20', topk='5,20',
                        batch_size=256, eval_batch_size=256, test_epoch=-1)
    args = parser.parse_args()
    run = args.root / 'runs' / args.run_name
    run.mkdir(parents=True, exist_ok=False)
    args.log_file = str(run / 'train.log')
    args.model_path = str(run / 'best.pt')
    args.device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    args.train = 1
    logging.basicConfig(level=logging.INFO, handlers=[logging.FileHandler(args.log_file, encoding='utf-8'),
                                                     logging.StreamHandler(sys.stdout)])
    torch.set_num_threads(args.threads)
    utils.init_seed(args.random_seed)
    manifest = {k: str(v) if isinstance(v, (Path, torch.device)) else v for k, v in vars(args).items()}
    manifest['torch'] = torch.__version__
    manifest['scope'] = args.stage
    manifest['patt_sha256'] = hashlib.sha256((args.root / 'implementation/PAtt2.py').read_bytes()).hexdigest()
    manifest['entry_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    manifest['diversity_sha256'] = hashlib.sha256((args.root / 'scripts/diversity_metrics.py').read_bytes()).hexdigest()
    manifest['data_sha256'] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                               for p in (Path(args.path) / args.dataset).glob('*.csv')}
    (run / 'config.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    start = time.perf_counter()
    corpus = SeqReader(args)
    model = cls(args, corpus).to(args.device)
    datasets = {phase: cls.Dataset(model, corpus, phase) for phase in ['train', 'dev', 'test']}
    for data in datasets.values():
        data.prepare()
    runner = BaseRunner(args)
    runner.train(datasets)
    phases = ['dev'] if args.stage == 'tune' else ['dev', 'test']
    scores = {}
    with torch.no_grad():
        for phase in phases:
            predictions = runner.predict(datasets[phase])
            scores[phase] = runner.evaluate_method(predictions, [5, 20], ['HR', 'NDCG'])
            if args.stage == 'final':
                from diversity_metrics import evaluate_diversity
                item_ids = np.asarray([datasets[phase][i]['item_id'] for i in range(len(datasets[phase]))])
                np.savez_compressed(run / (phase + '_predictions.npz'), scores=predictions,
                                    user_id=np.asarray(datasets[phase].data['user_id']),
                                    item_id=item_ids)
                scores[phase + '_diversity'] = evaluate_diversity(predictions, item_ids,
                                                                 Path(args.path) / args.dataset / 'item_meta.csv')
    scores['elapsed_seconds'] = time.perf_counter() - start
    scores['parameters'] = model.count_variables()
    (run / 'results.json').write_text(json.dumps(scores, indent=2), encoding='utf-8')
    logging.info('RUN_COMPLETED %s', json.dumps(scores))


if __name__ == '__main__':
    main()
