#!/usr/bin/env python3
"""Local adaptation of heat_analysis_manchester.ipynb for LaTeX table export."""

import os, warnings, argparse
import numpy as np
import pandas as pd
from config import output_dir

warnings.filterwarnings('ignore')

_ap = argparse.ArgumentParser(description=__doc__)
_ap.add_argument("--output-dir", default=str(output_dir()),
                 help="Directory containing the results_heat_* run folders")
BASE = _ap.parse_args().output_dir
SCENARIOS = ['peak', 'commute', 'weekend']
SCENARIO_LABELS = {'peak': 'Peak', 'commute': 'Commute', 'weekend': 'Weekend'}
MODE_LABELS = {'walk': 'Walk', 'bike': 'Cycle'}

def parse_list(s):
    s = s.strip()
    if s.startswith('[') and s.endswith(']'):
        s = s[1:-1]
    if not s.strip():
        return []
    return [x.strip() for x in s.split(',')]

def fmt_median_mean(vals):
    return f'{np.median(vals):.2f}', f'{np.mean(vals):.2f}'

def find_latest_dir(scenario):
    dirs = [d for d in os.listdir(BASE) if d.startswith(f'results_heat_{scenario}_')]
    if not dirs:
        return None
    return os.path.join(BASE, sorted(dirs)[-1])

def jaccard(a, b):
    inter = len(set(a) & set(b))
    union = len(set(a) | set(b))
    return inter / union if union else 0

latex_travel = []
latex_exposure = []
latex_jaccard = []

for scenario in SCENARIOS:
    latest = find_latest_dir(scenario)
    if latest is None:
        print(f"  No results dir for {scenario}")
        continue
    print(f"\n{'='*60}")
    print(f"  Scenario: {scenario}")
    print(f"  Loading from: {latest}")

    for mode in ['walk', 'bike']:
        fast_file = os.path.join(latest, f"routes_fastest_{mode}.csv")
        opt_file = os.path.join(latest, f"routes_heat_{mode}.csv")
        if not os.path.exists(fast_file) or not os.path.exists(opt_file):
            print(f"    Missing file for {mode}")
            continue

        fastest = pd.read_csv(fast_file)
        optimal = pd.read_csv(opt_file)
        print(f"    {mode}: {len(fastest)} fastest, {len(optimal)} heat-optimal")

        # Verify they have same persons
        if not fastest['person'].equals(optimal['person']):
            print(f"    WARNING: person lists differ for {mode}!")

        merged = fastest[['person', 'travel_time', 'heat_exposure']].rename(
            columns={'travel_time': 'time_c1', 'heat_exposure': 'heat_c1'}).merge(
            optimal[['person', 'travel_time', 'heat_exposure', 'weight']].rename(
                columns={'travel_time': 'time_c2', 'heat_exposure': 'heat_c2'}),
            on='person')

        # Detect null result: are fastest and heat-optimal routes actually the same?
        f_paths = fastest.set_index('person')['path'].apply(parse_list)
        o_paths = optimal.set_index('person')['path'].apply(parse_list)
        same_path = sum(f_paths.iloc[i] == o_paths.iloc[i] for i in range(len(f_paths)))
        same_time = np.isclose(merged['time_c1'], merged['time_c2']).sum()
        print(f"    Same path: {same_path}/{len(f_paths)}")
        print(f"    Same travel time: {same_time}/{len(merged)}")

        # Check for the weekend bike bug: identical path but different heat_exposure
        diff_heat_same_path = 0
        for i in range(len(f_paths)):
            if f_paths.iloc[i] == o_paths.iloc[i]:
                h1 = fastest.iloc[i]['heat_exposure']
                h2 = optimal.iloc[i]['heat_exposure']
                if not np.isclose(h1, h2):
                    diff_heat_same_path += 1
        if diff_heat_same_path > 0:
            print(f"    *** BUG: {diff_heat_same_path} trips with same path but different heat_exposure ***")
            # Show first few
            bug_indices = []
            for i in range(len(f_paths)):
                if f_paths.iloc[i] == o_paths.iloc[i]:
                    h1 = fastest.iloc[i]['heat_exposure']
                    h2 = optimal.iloc[i]['heat_exposure']
                    if not np.isclose(h1, h2):
                        bug_indices.append(i)
                        if len(bug_indices) <= 3:
                            print(f"      person={fastest.iloc[i]['person']}: fastest heat={h1:.2f}, optimal heat={h2:.2f}, ratio={h2/h1:.4f}")
            print(f"      Total bug trips: {len(bug_indices)}")

        # --- Travel time stats ---
        t1 = merged['time_c1'] / 60.0
        t2 = merged['time_c2'] / 60.0
        t1_med, t1_mean = fmt_median_mean(t1)
        t2_med, t2_mean = fmt_median_mean(t2)
        sl = SCENARIO_LABELS[scenario]
        ml = MODE_LABELS[mode]
        latex_travel.append(f'{ml} & {sl} & Median & {t1_med} & {t2_med} \\\\')
        latex_travel.append(f'       &       & Mean   & {t1_mean} & {t2_mean} \\\\')

        # --- WBGT exposure stats ---
        h1_cum = merged['heat_c1']
        h2_cum = merged['heat_c2']
        h1_cum_med, h1_cum_mean = fmt_median_mean(h1_cum)
        h2_cum_med, h2_cum_mean = fmt_median_mean(h2_cum)
        latex_exposure.append(f'{ml} & {sl} & Cumul. WBGT & {h1_cum_med} & {h2_cum_med} \\\\')

        # --- Jaccard ---
        merged['jaccard'] = [
            jaccard(fastest.iloc[i]['path'], optimal.iloc[i]['path'])
            for i in range(len(merged))
        ]
        j_mean, j_med = fmt_median_mean(merged['jaccard'])
        latex_jaccard.append(f'{ml} & {sl} & {j_mean} & {j_med} \\\\')

print('\n\n=== LATEX: TRAVEL TIME ===')
for line in latex_travel:
    print(line)

print('\n\n=== LATEX: WBGT EXPOSURE ===')
for line in latex_exposure:
    print(line)

print('\n\n=== JACCARD ===')
for line in latex_jaccard:
    print(line)
