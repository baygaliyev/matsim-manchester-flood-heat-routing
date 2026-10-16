#!/usr/bin/env python3
"""Diagnose the weekend bike bug: same path, different heat exposure."""

import os, argparse
import numpy as np
import pandas as pd
from config import output_dir

_ap = argparse.ArgumentParser(description=__doc__)
_ap.add_argument("--output-dir", default=str(output_dir()),
                 help="Directory containing the results_heat_* run folders")
_ap.add_argument("--run-dir", default=None,
                 help="Specific results_heat_* run folder (default: latest weekend run)")
_args = _ap.parse_args()


def _latest_run(base, prefix):
    dirs = sorted(d for d in os.listdir(base) if d.startswith(prefix))
    return os.path.join(base, dirs[-1]) if dirs else None


BASE = _args.output_dir
latest = _args.run_dir or _latest_run(BASE, "results_heat_weekend_")

fastest = pd.read_csv(os.path.join(latest, "routes_fastest_bike.csv"))
optimal = pd.read_csv(os.path.join(latest, "routes_heat_bike.csv"))

# Check trip count
print(f"Fastest routes: {len(fastest)}")
print(f"Optimal routes: {len(optimal)}")

# Check person lists match
print(f"Same persons: {fastest['person'].equals(optimal['person'])}")

# Check path equality
def parse_list(s):
    s = s.strip()
    if s.startswith('[') and s.endswith(']'):
        s = s[1:-1]
    return [x.strip() for x in s.split(',')] if s.strip() else []

f_paths = fastest['path'].apply(parse_list)
o_paths = optimal['path'].apply(parse_list)
same_path = sum(f_paths.iloc[i] == o_paths.iloc[i] for i in range(len(f_paths)))
print(f"Same path: {same_path}/{len(fastest)}")

# Check travel time equality
same_time = np.isclose(fastest['travel_time'], optimal['travel_time']).sum()
print(f"Same travel time: {same_time}/{len(fastest)}")

# Find trips with same path but different heat
bug_trips = []
for i in range(len(fastest)):
    if f_paths.iloc[i] == o_paths.iloc[i]:
        h1 = fastest.iloc[i]['heat_exposure']
        h2 = optimal.iloc[i]['heat_exposure']
        if not np.isclose(h1, h2):
            ratio = h2 / h1 if h1 > 0 else float('inf')
            bug_trips.append({
                'person': fastest.iloc[i]['person'],
                'h1': h1,
                'h2': h2,
                'ratio': ratio,
                'weight': optimal.iloc[i]['weight'],
                'travel_time': fastest.iloc[i]['travel_time'],
            })

print(f"\nBug trips: {len(bug_trips)}/{len(fastest)}")

if bug_trips:
    df = pd.DataFrame(bug_trips)
    print(f"\nRatio stats:")
    print(f"  Min ratio: {df['ratio'].min():.6f}")
    print(f"  Max ratio: {df['ratio'].max():.6f}")
    print(f"  Mean ratio: {df['ratio'].mean():.6f}")
    print(f"  Std ratio: {df['ratio'].std():.6f}")
    print(f"\nWeight distribution:")
    print(df['weight'].value_counts().sort_index())
    print(f"\nFirst 5 bug trips:")
    print(df.head(10).to_string(index=False))
    
    # Check non-bug trips
    non_bug = []
    for i in range(len(fastest)):
        if f_paths.iloc[i] == o_paths.iloc[i]:
            h1 = fastest.iloc[i]['heat_exposure']
            h2 = optimal.iloc[i]['heat_exposure']
            if np.isclose(h1, h2):
                non_bug.append({
                    'person': fastest.iloc[i]['person'],
                    'h1': h1,
                    'h2': h2,
                    'weight': optimal.iloc[i]['weight'],
                })
    print(f"\nNon-bug trips (same path, same heat): {len(non_bug)}")
    if non_bug:
        ndf = pd.DataFrame(non_bug)
        print(f"  Weight distribution:")
        print(ndf['weight'].value_counts().sort_index())

# Check trips with different paths
diff_path_trips = 0
for i in range(len(fastest)):
    if f_paths.iloc[i] != o_paths.iloc[i]:
        diff_path_trips += 1
print(f"\nDifferent paths: {diff_path_trips}/{len(fastest)}")
