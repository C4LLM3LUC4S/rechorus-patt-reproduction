"""Supplementary FF-width control without modifying the frozen training entry."""
import argparse
import hashlib
import sys
from pathlib import Path


def install(root):
    sys.path[:0] = [str(root / 'sources/ReChorus/src'), str(root / 'implementation'), str(root / 'scripts')]
    import torch.nn as nn
    import PAtt2 as module
    original = module.PAtt2

    class PAtt2FF1(original):
        @staticmethod
        def parse_model_args(parser):
            parser = original.parse_model_args(parser)
            parser.add_argument('--ff_multiplier', type=int, choices=[1], default=1)
            parser.add_argument('--control_source_sha256', default=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
            return parser

        def __init__(self, args, corpus):
            super().__init__(args, corpus)
            for block in self.blocks:
                block.ffn = nn.Sequential(nn.Linear(args.emb_size, args.emb_size), nn.GELU(),
                                          nn.Linear(args.emb_size, args.emb_size))
                block.ffn.apply(self.init_weights)

    module.PAtt2 = PAtt2FF1
    return original, PAtt2FF1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--root', type=Path, required=True)
    known, _ = parser.parse_known_args()
    install(known.root)
    import run_rechorus
    run_rechorus.main()
