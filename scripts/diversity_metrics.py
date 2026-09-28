"""Explicit category coverage and Jaccard intra-list distance definitions."""
import ast
import itertools
import numpy as np
import pandas as pd


def metadata_categories(path):
    frame = pd.read_csv(path, sep='\t')
    if 'i_categories' in frame:
        mapping = {int(r.item_id): set(ast.literal_eval(r.i_categories)) for r in frame.itertuples()}
    else:
        mapping = {int(r.item_id): {int(r.i_category)} for r in frame.itertuples()}
    universe = set().union(*mapping.values())
    return mapping, len(universe)


def list_diversity(items, categories, total_categories):
    sets = [categories[int(i)] for i in items]
    coverage = len(set().union(*sets)) / total_categories if sets else 0.0
    distances = [1 - len(a & b) / len(a | b) if a | b else 0.0
                 for a, b in itertools.combinations(sets, 2)]
    return coverage, float(np.mean(distances)) if distances else 0.0


def evaluate_diversity(scores, item_ids, metadata, topks=(5, 20)):
    categories, total = metadata_categories(metadata)
    records = {k: [] for k in topks}
    for row, ids in zip(scores, item_ids):
        ranking, seen = [], set()
        # Stable score ties; repeated candidate IDs are removed before top-k.
        for j in np.argsort(-row, kind='stable'):
            item = int(ids[j])
            if item > 0 and item not in seen:
                ranking.append(item)
                seen.add(item)
            if len(ranking) >= max(topks):
                break
        for k in topks:
            records[k].append(list_diversity(ranking[:k], categories, total))
    return {f'{name}@{k}': float(np.mean(values, axis=0)[j])
            for k, values in records.items() for j, name in enumerate(['CC_unique', 'ILD_Jaccard_unique'])}


if __name__ == '__main__':
    cc, ild = list_diversity([1, 2, 3], {1: {0}, 2: {0, 1}, 3: {1}}, 2)
    assert cc == 1.0 and np.isclose(ild, 2 / 3)
    assert list_diversity([1], {1: {0}}, 2) == (.5, 0.0)
    assert list_diversity([1, 2], {1: {0}, 2: {0}}, 2) == (.5, 0.0)
    print('DIVERSITY_METRICS_TEST_PASS')
