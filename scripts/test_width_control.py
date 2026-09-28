"""Check that only feed-forward shapes/parameters change in the control."""
import argparse
import json
from pathlib import Path
from types import SimpleNamespace
import torch
from run_width_control import install


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    args = parser.parse_args()
    original, narrow = install(args.root.resolve())
    config = SimpleNamespace(device=torch.device('cpu'), model_path='', buffer=0, num_neg=1,
                             dropout=.3, test_all=0, history_max=30, emb_size=64, num_layers=1,
                             patt_lambda=4, length_scale=0)
    corpus = SimpleNamespace(n_users=8, n_items=100)
    torch.manual_seed(14)
    base = original(config, corpus)
    torch.manual_seed(14)
    control = narrow(config, corpus)
    for key, value in base.state_dict().items():
        if '.ffn.' not in key:
            assert torch.equal(value, control.state_dict()[key]), key
    delta = sum(p.numel() for p in base.parameters()) - sum(p.numel() for p in control.parameters())
    assert delta == 24768, delta
    assert control.blocks[0].ffn[0].out_features == 64
    feed = {'history_items': torch.tensor([[1, 2, 3], [5, 0, 0]]),
            'lengths': torch.tensor([3, 1]), 'item_id': torch.tensor([[4, 6], [7, 8]])}
    scores = control(feed)['prediction']
    assert scores.shape == (2, 2) and torch.isfinite(scores).all()
    loss = control.loss({'prediction': scores})
    loss.backward()
    assert all(torch.isfinite(p.grad).all() for p in control.parameters() if p.grad is not None)
    result = {'status': 'PASS', 'parameter_reduction': delta, 'non_ff_initial_weights_identical': True,
              'finite_forward_backward': True}
    (args.root / 'planning/width_control_tests.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result))


if __name__ == '__main__':
    main()
