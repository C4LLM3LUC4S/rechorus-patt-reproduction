"""Small real-data forward/backward checks, not a performance experiment."""
import argparse
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import torch


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', required=True, type=Path)
    args = parser.parse_args()
    sys.path.insert(0, str(args.root / 'sources/ReChorus/src'))
    from helpers.SeqReader import SeqReader
    from models.sequential.SASRec import SASRec
    from models.sequential.GRU4Rec import GRU4Rec
    from utils import utils

    config = SimpleNamespace(path=str(args.root / 'sources/ReChorus/data'),
                             dataset='Grocery_and_Gourmet_Food', sep='\t',
                             device=torch.device('cuda' if torch.cuda.is_available() else 'cpu'),
                             model_path='', buffer=0, num_neg=1, dropout=0.1,
                             test_all=0, history_max=10, emb_size=64, num_layers=1,
                             num_heads=1, hidden_size=64)
    corpus = SeqReader(config)
    outputs = {}
    for cls in (SASRec, GRU4Rec):
        utils.init_seed(24334094)
        model = cls(config, corpus).to(config.device)
        dataset = cls.Dataset(model, corpus, 'train')
        dataset.actions_before_epoch()
        indices = list(range(0, min(len(dataset), 4096), 32))
        feed = utils.batch_to_gpu(dataset.collate_batch([dataset[i] for i in indices]), config.device)
        optimizer = torch.optim.Adam(model.parameters(), lr=0.001)
        losses = []
        model.train()
        for _ in range(3):
            optimizer.zero_grad()
            result = model(feed)
            loss = model.loss(result)
            assert torch.isfinite(loss)
            loss.backward()
            assert all(torch.isfinite(p.grad).all() for p in model.parameters() if p.grad is not None)
            optimizer.step()
            losses.append(float(loss.detach()))
        model.eval()
        dev = cls.Dataset(model, corpus, 'dev')
        check = utils.batch_to_gpu(dev.collate_batch([dev[i] for i in range(16)]), config.device)
        with torch.no_grad():
            scores = model(check)['prediction']
        assert torch.isfinite(scores).all()
        outputs[cls.__name__] = {'device': str(config.device), 'training_rows_available': len(dataset),
                                'training_batch_size': len(indices), 'repeated_batch_steps': 3,
                                'losses': losses, 'dev_score_shape': list(scores.shape),
                                'finite_forward_backward': True}
    outputs['scope'] = 'Smoke test only: no full epoch, hyperparameter selection, or performance claims.'
    target = args.root / 'planning/baseline_smoke.json'
    target.write_text(json.dumps(outputs, indent=2), encoding='utf-8')
    print(json.dumps(outputs, indent=2))


if __name__ == '__main__':
    main()
