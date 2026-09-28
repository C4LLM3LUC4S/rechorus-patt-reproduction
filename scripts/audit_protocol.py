"""Audit candidate sets and actual SeqReader history ordering on both datasets."""
import argparse
import json
import sys
from pathlib import Path
from types import SimpleNamespace
import pandas as pd
from audit_inputs import audit_data


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(args.root / 'sources/ReChorus/src'))
    from helpers.SeqReader import SeqReader
    results = {}
    for name, path in [('Grocery_and_Gourmet_Food', args.root / 'sources/ReChorus/data'),
                       ('ML_1MTOPK', args.root / 'data/processed')]:
        summary = audit_data(path / name)
        corpus = SeqReader(SimpleNamespace(path=str(path), dataset=name, sep='\t'))
        phase_map = {}
        for phase, part in corpus.data_df.items():
            for row in part.itertuples():
                phase_map[(row.user_id, row.item_id, row.time)] = phase
        inversions = 0
        for uid, history in corpus.user_his.items():
            levels = [{'train': 0, 'dev': 1, 'test': 2}[phase_map[(uid, iid, t)]] for iid, t in history]
            inversions += sum(a > b for a, b in zip(levels, levels[1:]))
        counts = {}
        for phase, part in corpus.data_df.items():
            counts[phase] = {'usable_rows': int((part.position > 0).sum()),
                             'users': int(part.user_id.nunique()),
                             'no_history_rows': int((part.position == 0).sum())}
            original = pd.read_csv(path / name / (phase + '.csv'), sep='\t')
            assert len(part) == len(original), 'history merge changed sample count'
        assert inversions == 0, 'a later split precedes an earlier split in user history'
        summary['actual_history_phase_inversions'] = inversions
        summary['evaluation_semantics'] = 'Rolling observed history: earlier held-out interactions may enter later histories.'
        summary['phase_counts'] = counts
        results[name] = summary
    (args.root / 'planning/protocol_audit.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()
