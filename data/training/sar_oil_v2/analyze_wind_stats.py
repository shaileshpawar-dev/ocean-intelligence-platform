import json
import math
import numpy as np
from collections import defaultdict

cache = json.load(open('data/cache/era5_wind_cache.json'))
p12_manifest = json.load(open('data/training/sar_oil_v2/sar_splits_v2_2_clean_manifest.json'))
p13_manifest = json.load(open('data/training/sar_oil_v2/sar_splits_phase13_manifest.json'))

p12_test = p12_manifest['splits']['test']
p13_locked = p13_manifest['splits']['locked_final_test']
p13_dev = p13_manifest['splits']['env_dev']
p13_val = p13_manifest['splits']['env_val']

all_samples = []
for s in p12_test: all_samples.append({**s, 'split': 'p12_test'})
for s in p13_locked: all_samples.append({**s, 'split': 'p13_locked'})
for s in p13_dev: all_samples.append({**s, 'split': 'p13_dev'})
for s in p13_val: all_samples.append({**s, 'split': 'p13_val'})

for s in all_samples:
    w = cache.get(s['image'], {})
    s['wind_speed'] = w.get('wind_speed_ms')
    s['wind_dir'] = w.get('wind_direction_deg')
    s['is_coastal_cache'] = w.get('is_coastal', s.get('is_coastal', False))

# Breakdown by cluster
clusters = defaultdict(list)
for s in all_samples:
    if s['wind_speed'] is not None:
        clusters[s['cluster']].append(s)

print('=== WIND SPEED BY CLUSTER (ALL 300 SAMPLES) ===')
header = f"{'Cluster':10s} {'Type':6s} {'N':4s} {'Mean':6s} {'Med':6s} {'<3m/s':8s} {'Pct':6s} {'Coastal':7s}"
print(header)
print('-' * len(header))
for cl in sorted(clusters.keys()):
    items = clusters[cl]
    spds = [x['wind_speed'] for x in items]
    low_cnt = sum(1 for w in spds if w < 3.0)
    pct = low_cnt / len(spds) * 100
    ctype = 'oil' if cl == 'oil' else 'la'
    coastal_cnt = sum(1 for x in items if x['is_coastal_cache'])
    print(f"{cl:10s} {ctype:6s} {len(items):4d} {np.mean(spds):6.2f} {np.median(spds):6.2f} {low_cnt:3d}/{len(spds):3d} {pct:5.1f}% {coastal_cnt:3d}/{len(items):3d}")

print('\n=== COASTAL VS OPEN WATER ===')
for c_flag, c_label in [(True, 'Coastal'), (False, 'Open Water')]:
    for l_val, l_name in [(1, 'Oil'), (0, 'Look-alike')]:
        sub = [x['wind_speed'] for x in all_samples if x['is_coastal_cache'] == c_flag and x['label'] == l_val and x['wind_speed'] is not None]
        low = sum(1 for w in sub if w < 3.0)
        pct = (low / len(sub) * 100) if sub else 0.0
        print(f"{c_label:10s} {l_name:10s} (n={len(sub):3d}): Mean={np.mean(sub):.2f} m/s, Median={np.median(sub):.2f} m/s, <3m/s: {low}/{len(sub)} ({pct:.1f}%)")

# Connected component grouping effect
comp_winds = defaultdict(list)
for s in all_samples:
    cid = s.get('component_id') or s.get('tag')
    if s['wind_speed'] is not None:
        comp_winds[cid].append(s)

print(f'\nTotal unique connected components across 300 samples: {len(comp_winds)}')
