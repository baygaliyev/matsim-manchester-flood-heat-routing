#!/usr/bin/env python3
"""Deep investigation of weekend bike bug."""

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

# Also load walk data for comparison (from same dir, different file)
walk_file = os.path.join(latest, "routes_fastest_walk.csv")
if os.path.exists(walk_file):
    f_walk = pd.read_csv(walk_file)

def parse_list(s):
    s = s.strip()
    if s.startswith('[') and s.endswith(']'):
        s = s[1:-1]
    return [x.strip() for x in s.split(',')] if s.strip() else []

# Check link ID equality for all trips
f_links = fastest['links'].apply(parse_list)
o_links = optimal['links'].apply(parse_list)
same_links = sum(f_links.iloc[i] == o_links.iloc[i] for i in range(len(fastest)))
print(f"Same links: {same_links}/{len(fastest)}")

# Check path length equality
f_path_len = fastest['path'].apply(lambda x: len(parse_list(x)))
o_path_len = optimal['path'].apply(lambda x: len(parse_list(x)))
same_len = sum(f_path_len == o_path_len)
print(f"Same path length: {same_len}/{len(fastest)}")

# For bug trips, compare link IDs in detail
f_links = fastest['links'].apply(parse_list)
o_links = optimal['links'].apply(parse_list)
f_paths = fastest['path'].apply(parse_list)
o_paths = optimal['path'].apply(parse_list)

bug_links_differ = 0
for i in range(len(fastest)):
    h1 = fastest.iloc[i]['heat_exposure']
    h2 = optimal.iloc[i]['heat_exposure']
    if not np.isclose(h1, h2) and f_paths.iloc[i] == o_paths.iloc[i]:
        if f_links.iloc[i] != o_links.iloc[i]:
            bug_links_differ += 1
            if bug_links_differ <= 3:
                print(f"\nPerson {fastest.iloc[i]['person']}:")
                print(f"  Same node path but different links!")
                print(f"  Fastest links: {f_links.iloc[i]}")
                print(f"  Optimal links: {o_links.iloc[i]}")
                print(f"  h1={h1:.2f}, h2={h2:.2f}, ratio={h2/h1:.6f}")

print(f"\nBug trips with different link IDs despite same node path: {bug_links_differ}")

# Check: what is the factor 1.799839?
# Try computing it from known constants
walk_speed = 1.27
bike_speed = 4.2
bike_heat_factor = 1.53

print(f"\nFactor analysis:")
print(f"  bike_heat_factor = {bike_heat_factor}")
print(f"  bike_speed / walk_speed = {bike_speed / walk_speed:.6f}")
print(f"  walk_speed / bike_speed = {walk_speed / bike_speed:.6f}")
print(f"  bike_heat_factor * (walk_speed / bike_speed) = {bike_heat_factor * walk_speed / bike_speed:.6f}")
print(f"  bike_heat_factor * (bike_speed / walk_speed) = {bike_heat_factor * bike_speed / walk_speed:.6f}")
print(f"  1 / (walk_speed / bike_speed) = {1.0 / (walk_speed / bike_speed):.6f}")

# Maybe it's related to maxRawHeat ratios?
# If the fastest file's heat was computed with walk WBGT data (without bike factor applied)
h1_sum = fastest['heat_exposure'].sum()
h2_sum = optimal['heat_exposure'].sum()
print(f"\n  Fastest total heat: {h1_sum:.2f}")
print(f"  Optimal total heat: {h2_sum:.2f}")
print(f"  Ratio of sums: {h2_sum/h1_sum:.6f}")

# Check if there's a pattern by travel time
merged = fastest[['person','travel_time','heat_exposure']].merge(
    optimal[['person','heat_exposure']], on='person', suffixes=('_fast','_opt'))
merged['ratio'] = merged['heat_exposure_opt'] / merged['heat_exposure_fast']
merged['time_bin'] = pd.cut(merged['travel_time'], bins=20)
print("\nRatio by travel time bin:")
print(merged.groupby('time_bin')['ratio'].agg(['mean','std','count']).to_string())

# Check if trips with ratio=1 (non-bug) vs ratio=1.8 (bug) differ by some property
# Load corresponding walk data for the same persons
# Actually, let me check the WBGT scenario file to understand the data
# Weekend has lower WBGT than Peak

# Check: are bug trips clustered by origin/destination?
print("\nChecking if bug pattern correlates with route properties...")
merged['is_bug'] = ~np.isclose(merged['heat_exposure_fast'], merged['heat_exposure_opt'])
print(f"  Bug trips: {merged['is_bug'].sum()}")
print(f"  Mean travel time (non-bug): {merged[~merged['is_bug']]['travel_time'].mean():.1f}s")
print(f"  Mean travel time (bug): {merged[merged['is_bug']]['travel_time'].mean():.1f}s")
