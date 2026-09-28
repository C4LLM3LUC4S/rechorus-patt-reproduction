"""PAtt2: equations (4), (7)-(9), Liu et al., KDD 2024.

Independent equation-based implementation for ReChorus. Not a byte-for-byte
port of the author's published code. See planning/paper_implementation_audit.md.
"""
import torch
from torch import nn
from models.BaseModel import SequentialModel


def pair_probabilities(sampler, valid):
    """Normalized 2-DPP principal minors over valid history positions.

    The common scale cancels in a fixed-cardinality DPP. If every pair has
    zero mass (rank < 2), use uniform valid pairs as an explicit fallback.
    """
    x = sampler * valid.unsqueeze(-1)
    kernel = x @ x.transpose(-1, -2)
    scale = kernel.diagonal(dim1=-2, dim2=-1).sum(-1).clamp_min(torch.finfo(x.dtype).tiny)
    kernel = kernel / scale[:, None, None]
    diagonal = kernel.diagonal(dim1=-2, dim2=-1)
    minors = (diagonal[:, :, None] * diagonal[:, None, :] - kernel.square()).clamp_min(0)
    size = x.shape[1]
    eye = torch.eye(size, dtype=torch.bool, device=x.device)
    pairs = valid[:, :, None] & valid[:, None, :] & ~eye
    minors = minors * pairs
    denominator = minors.triu(diagonal=1).sum((-2, -1))
    count = pairs.triu(diagonal=1).sum((-2, -1))
    tiny = torch.finfo(x.dtype).tiny
    normalized = minors / denominator.clamp_min(tiny)[:, None, None]
    uniform = pairs.to(x.dtype) / count.clamp_min(1)[:, None, None]
    return torch.where((denominator > 0)[:, None, None], normalized, uniform)


def dependency_weights(probability, valid, strength, length_scale=False):
    size = probability.shape[1]
    factor = probability.new_full((probability.shape[0],), float(strength))
    if length_scale:
        lengths = valid.sum(-1).to(probability.dtype)
        factor = factor * (lengths * (lengths - 1) / 2).clamp_min(1)
    weights = torch.exp(-factor[:, None, None] * probability)
    allowed = valid[:, :, None] & valid[:, None, :]
    allowed = allowed & torch.ones(size, size, dtype=torch.bool, device=valid.device).tril()
    return weights * allowed


class PAttBlock(nn.Module):
    def __init__(self, size, dropout, strength, length_scale):
        super().__init__()
        self.sampler = nn.Linear(size, size, bias=False)
        self.norm1 = nn.LayerNorm(size)
        self.norm2 = nn.LayerNorm(size)
        self.dropout = nn.Dropout(dropout)
        self.ffn = nn.Sequential(nn.Linear(size, size * 4), nn.GELU(),
                                 nn.Linear(size * 4, size))
        self.strength, self.length_scale = strength, length_scale

    def forward(self, x, valid):
        probability = pair_probabilities(self.sampler(x), valid)
        weights = dependency_weights(probability, valid, self.strength, self.length_scale)
        x = self.norm1(x + self.dropout(weights @ x))
        x = self.norm2(x + self.dropout(self.ffn(x)))
        return x * valid.unsqueeze(-1)


class PAtt2(SequentialModel):
    reader, runner = 'SeqReader', 'BaseRunner'
    extra_log_args = ['emb_size', 'num_layers', 'patt_lambda', 'length_scale']

    @staticmethod
    def parse_model_args(parser):
        parser.add_argument('--emb_size', type=int, default=64)
        parser.add_argument('--num_layers', type=int, default=1)
        parser.add_argument('--patt_lambda', type=float, default=4.0)
        parser.add_argument('--length_scale', type=int, choices=[0, 1], default=0)
        return SequentialModel.parse_model_args(parser)

    def __init__(self, args, corpus):
        super().__init__(args, corpus)
        self.i_embeddings = nn.Embedding(self.item_num, args.emb_size, padding_idx=0)
        self.p_embeddings = nn.Embedding(self.history_max + 1, args.emb_size, padding_idx=0)
        self.input_norm = nn.LayerNorm(args.emb_size)
        self.input_dropout = nn.Dropout(args.dropout)
        self.blocks = nn.ModuleList([PAttBlock(args.emb_size, args.dropout,
                                              args.patt_lambda, bool(args.length_scale))
                                     for _ in range(args.num_layers)])
        self.apply(self.init_weights)

    def forward(self, feed_dict):
        history = feed_dict['history_items']
        valid = history > 0
        positions = torch.arange(1, history.shape[1] + 1, device=history.device)[None, :] * valid
        x = self.i_embeddings(history) + self.p_embeddings(positions)
        x = self.input_dropout(self.input_norm(x)) * valid.unsqueeze(-1)
        for block in self.blocks:
            x = block(x, valid)
        row = torch.arange(history.shape[0], device=history.device)
        user = x[row, feed_dict['lengths'] - 1]
        scores = (user[:, None, :] * self.i_embeddings(feed_dict['item_id'])).sum(-1)
        return {'prediction': scores}
