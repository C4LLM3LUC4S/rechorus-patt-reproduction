"""Equation, padding, degeneracy, gradient, and ReChorus integration checks."""
import argparse
import itertools
import json
import sys
from pathlib import Path
from types import SimpleNamespace
import torch


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    args = parser.parse_args()
    sys.path[:0] = [str(args.root / 'sources/ReChorus/src'), str(args.root / 'implementation')]
    from PAtt2 import PAtt2, pair_probabilities, dependency_weights
    torch.manual_seed(14)
    x = torch.randn(2, 5, 8, dtype=torch.float64, requires_grad=True)
    valid = torch.tensor([[1, 1, 1, 1, 1], [1, 1, 1, 0, 0]], dtype=torch.bool)
    p = pair_probabilities(x, valid)
    reference = torch.zeros_like(p)
    for b, length in enumerate([5, 3]):
        kernel = x[b, :length] @ x[b, :length].T
        combinations = list(itertools.combinations(range(length), 2))
        determinants = torch.stack([torch.linalg.det(kernel[list(c)][:, list(c)]) for c in combinations])
        for c, value in zip(combinations, determinants / determinants.sum()):
            reference[b, c[0], c[1]] = reference[b, c[1], c[0]] = value
    torch.testing.assert_close(p, reference, rtol=1e-10, atol=1e-12)
    torch.testing.assert_close(p.triu(1).sum((-2, -1)), torch.ones(2, dtype=x.dtype))
    torch.testing.assert_close(pair_probabilities(x * 13, valid), p)
    torch.testing.assert_close(pair_probabilities(x[:1, :3], valid[:1, :3]),
                               pair_probabilities(torch.cat([x[:1, :3], torch.randn(1, 4, 8, dtype=x.dtype)], 1),
                                                  torch.tensor([[1, 1, 1, 0, 0, 0, 0]], dtype=torch.bool))[:, :3, :3])
    weights = dependency_weights(p, valid, 4)
    assert torch.count_nonzero(weights.triu(1)) == 0
    torch.testing.assert_close(weights.diagonal(dim1=-2, dim2=-1), valid.to(x.dtype))
    assert torch.autograd.gradcheck(lambda z: pair_probabilities(z, valid), (x,), atol=1e-5)
    for length in [1, 2, 5]:
        zeros = torch.zeros(1, length, 8, dtype=torch.float64)
        mask = torch.ones(1, length, dtype=torch.bool)
        assert torch.isfinite(pair_probabilities(zeros, mask)).all()
    from helpers.SeqReader import SeqReader
    from utils import utils
    config = SimpleNamespace(path=str(args.root / 'sources/ReChorus/data'), dataset='Grocery_and_Gourmet_Food',
                             sep='\t', device=torch.device('cuda'), model_path='', buffer=0,
                             num_neg=1, dropout=0.3, test_all=0, history_max=30,
                             emb_size=64, num_layers=1, patt_lambda=4, length_scale=0)
    corpus = SeqReader(config)
    model = PAtt2(config, corpus).to(config.device)
    data = model.Dataset(model, corpus, 'train')
    data.actions_before_epoch()
    feed = utils.batch_to_gpu(data.collate_batch([data[i] for i in range(0, 256, 8)]), config.device)
    loss = model.loss(model(feed))
    loss.backward()
    assert torch.isfinite(loss)
    assert all(torch.isfinite(p.grad).all() for p in model.parameters() if p.grad is not None)
    model.eval()
    with torch.no_grad():
        single = utils.batch_to_gpu(data.collate_batch([data[0]]), config.device)
        assert torch.isfinite(model(single)['prediction']).all()
    result = {'status': 'PASS', 'enumerated_minor_max_error': float((p-reference).abs().max().detach()),
              'gradcheck': True, 'padding_invariance': True, 'scale_invariance': True,
              'degenerate_and_singleton': True, 'gpu_real_data_loss': float(loss.detach()),
              'scope': 'Unit and integration checks only; not a trained performance result.'}
    (args.root / 'planning/patt_tests.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
