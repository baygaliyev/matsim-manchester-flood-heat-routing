#!/usr/bin/env python3
"""Final heat analysis with corrected weekend bike bug."""

import os, argparse
import numpy as np
import pandas as pd
from config import output_dir

def parse_list(s):
    s = s.strip()
    if s.startswith('[') and s.endswith(']'):
        s = s[1:-1]
    return [x.strip() for x in s.split(',')] if s.strip() else []

_ap = argparse.ArgumentParser(description=__doc__)
_ap.add_argument("--output-dir", default=str(output_dir()),
                 help="Directory containing the results_heat_* run folders")
BASE = _ap.parse_args().output_dir
scenarios = ['peak', 'commute', 'weekend']
labels = {'peak': 'Peak', 'commute': 'Commute', 'weekend': 'Weekend'}
modes = ['walk', 'bike']
mode_lbl = {'walk': 'Walk', 'bike': 'Cycle'}

print("=== CORRECTED HEAT ANALYSIS ===\n")
print(f"{'Mode':<8} {'Scenario':<10} {'Metric':<20} {'Fastest':>12} {'Heat-opt':>12}")
print("-"*62)

for sc in scenarios:
    d = [os.path.join(BASE, x) for x in os.listdir(BASE) if x.startswith(f'results_heat_{sc}_')]
    if not d: continue
    latest = sorted(d)[-1] if len(d) > 1 else d[0]
    
    for mode in modes:
        ff = os.path.join(latest, f"routes_fastest_{mode}.csv")
        of = os.path.join(latest, f"routes_heat_{mode}.csv")
        if not os.path.exists(ff) or not os.path.exists(of): continue
        
        fast = pd.read_csv(ff)
        opt = pd.read_csv(of)
        
        f_heat = fast['heat_exposure']
        o_heat = opt['heat_exposure']
        
        # Detect bug: same path, different heat
        f_path = fast['path'].apply(parse_list)
        o_path = opt['path'].apply(parse_list)
        same_path = sum(f_path.iloc[i] == o_path.iloc[i] for i in range(len(fast)))
        
        if same_path == len(fast) and not np.allclose(f_heat, o_heat):
            # Bug detected: use fastest values for both
            o_heat_corrected = f_heat.copy()
            bug_n = sum(~np.isclose(f_heat, o_heat))
            print(f"  *** Weekend bike bug: {bug_n}/{len(fast)} trips corrected ***")
        else:
            o_heat_corrected = o_heat
        
        # Travel time (minutes)
        ft = fast['travel_time'] / 60
        ot = opt['travel_time'] / 60
        
        # Stats
        ml = mode_lbl[mode]
        sl = labels[sc]
        print(f"{ml:<8} {sl:<10} {'Travel time (med)':<20} {np.median(ft):>8.2f} min  {np.median(ot):>8.2f} min")
        print(f"{'':8} {'':10} {'Travel time (mean)':<20} {np.mean(ft):>8.2f} min  {np.mean(ot):>8.2f} min")
        print(f"{'':8} {'':10} {'Cumul. WBGT (med)':<20} {np.median(f_heat):>10.2f}  {np.median(o_heat_corrected):>10.2f}")
        print(f"{'':8} {'':10} {'Cumul. WBGT (mean)':<20} {np.mean(f_heat):>10.2f}  {np.mean(o_heat_corrected):>10.2f}")
        
        # Jaccard
        def jaccard(a, b):
            inter = len(set(a) & set(b))
            union = len(set(a) | set(b))
            return inter / union if union else 0
        
        js = [jaccard(f_path.iloc[i], o_path.iloc[i]) for i in range(len(fast))]
        print(f"{'':8} {'':10} {'Jaccard (mean)':<20} {np.mean(js):>10.4f}  {np.mean(js):>10.4f}")
        print()
