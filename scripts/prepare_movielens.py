"""ReChorus MovieLens-1M Top-k preprocessing, with explicit reproducibility fixes.

Retains >=4 ratings, iterative positive 5-core, elapsed-calendar-day 80/90%
split, warm-start evaluation, and 99 unique negatives. See manifest for fixes.
Reads the official ZIP without extracting or redistributing its contents.
"""
import argparse
import hashlib
import io
import json
import zipfile
from pathlib import Path
import numpy as np
import pandas as pd


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    args = parser.parse_args()
    archive = args.root / 'data/raw/ml-1m.zip'
    expected = 'c4d9eecfca2ab87c1945afe126590906'
    assert hashlib.md5(archive.read_bytes()).hexdigest() == expected
    out = args.root / 'data/processed/ML_1MTOPK'
    out.mkdir(parents=True, exist_ok=False)
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None
        ratings = pd.read_csv(io.BytesIO(z.read('ml-1m/ratings.dat')), sep='::', engine='python',
                              names=['original_user', 'original_item', 'rating', 'time'])
        movies = pd.read_csv(io.BytesIO(z.read('ml-1m/movies.dat')), sep='::', engine='python',
                             encoding='latin-1', names=['original_item', 'title', 'genres'])
    df = ratings[ratings.rating >= 4].copy()
    core_steps = []
    while True:
        before = len(df)
        uc = df.groupby('original_user').original_item.transform('size')
        ic = df.groupby('original_item').original_user.transform('size')
        df = df[(uc >= 5) & (ic >= 5)].copy()
        core_steps.append(len(df))
        if len(df) == before:
            break
    # Explicitly fixes notebook datetime.fromtimestamp to this machine's timezone.
    dates = pd.to_datetime(df.time, unit='s', utc=True).dt.tz_convert('Asia/Shanghai').dt.normalize()
    days = (dates - dates.min()).dt.days
    cut1, cut2 = int(days.max() * .8), int(days.max() * .9)
    frames = {'train': df[days <= cut1].copy(),
              'dev': df[(days > cut1) & (days <= cut2)].copy(),
              'test': df[days > cut2].copy()}
    train = frames['train']
    for phase in ['dev', 'test']:
        part = frames[phase]
        frames[phase] = part[part.original_user.isin(train.original_user) &
                             part.original_item.isin(train.original_item)].copy()
    all_df = pd.concat(frames.values())
    # Notebook IDs originate from strings. Keep lexicographic order explicitly.
    user_map = {v: i+1 for i, v in enumerate(sorted(all_df.original_user.unique(), key=str))}
    item_map = {v: i+1 for i, v in enumerate(sorted(all_df.original_item.unique(), key=str))}
    for part in frames.values():
        part['user_id'] = part.original_user.map(user_map)
        part['item_id'] = part.original_item.map(item_map)
        part.sort_values(['user_id', 'time'], kind='stable', inplace=True)
    all_df = pd.concat(frames.values())
    clicked = all_df.groupby('user_id').item_id.agg(set).to_dict()
    universe = np.arange(1, len(item_map) + 1)
    eligible = {u: np.array([i for i in universe if i not in seen]) for u, seen in clicked.items()}
    for phase, seed in [('dev', 1), ('test', 2)]:
        rng = np.random.default_rng(seed)
        frames[phase]['neg_items'] = [rng.choice(eligible[u], 99, replace=False).tolist()
                                      for u in frames[phase].user_id]
    for phase, part in frames.items():
        columns = ['user_id', 'item_id', 'time'] + ([] if phase == 'train' else ['neg_items'])
        part[columns].to_csv(out / (phase + '.csv'), sep='\t', index=False)
    movies = movies[movies.original_item.isin(item_map)].copy()
    movies['item_id'] = movies.original_item.map(item_map)
    combos = {v: i for i, v in enumerate(sorted(movies.genres.unique()))}
    genres = sorted({g for s in movies.genres for g in s.split('|')})
    genre_map = {g: i for i, g in enumerate(genres)}
    movies['i_category'] = movies.genres.map(combos)
    movies['i_categories'] = movies.genres.map(lambda s: json.dumps([genre_map[g] for g in s.split('|')]))
    movies[['item_id', 'i_category', 'i_categories']].sort_values('item_id').to_csv(out / 'item_meta.csv', sep='\t', index=False)
    manifest = {'source': 'https://files.grouplens.org/datasets/movielens/ml-1m.zip',
                'source_md5': expected, 'raw_rows': len(ratings), 'positive_5core_rows': len(df),
                'core_steps': core_steps, 'timezone': 'Asia/Shanghai', 'split_day_thresholds': [cut1, cut2],
                'rows': {k: len(v) for k, v in frames.items()}, 'users': len(user_map), 'items': len(item_map),
                'atomic_genres': genres, 'genre_combinations': len(combos),
                'deviations_from_notebook': ['fixed path/variable/ID-type issues',
                    'explicit timezone and stable within-user ordering',
                    'default_rng without-replacement sampling; same protocol, not identical candidate realization',
                    'omit unused context columns; preserve both genre combinations and atomic genre sets'],
                'protocol': 'ReChorus-derived 5-core positive global-time split; NOT paper 10-core leave-one-out',
                'redistribution': 'Do not upload raw or processed dataset; scripts and statistics only.'}
    manifest['files_sha256'] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in out.glob('*.csv')}
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print(json.dumps(manifest, indent=2))


if __name__ == '__main__':
    main()
