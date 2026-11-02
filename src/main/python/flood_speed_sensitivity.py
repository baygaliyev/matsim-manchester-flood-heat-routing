#!/usr/bin/env python
"""Post-hoc sensitivity of the flood case study to cycling-in-water speeds.

The paper's baseline speed curve lets cyclists ride slowly through shallow
water.  A reviewer may argue that cyclists would dismount and walk instead.
This script evaluates the same C1/C2/C3 routes under alternative speed
assumptions without rerunning MATSim:

* ``base``: published speed curves.
* ``dismount_all``: cyclists use walking speed on every flooded link.
* ``dismount_0.2``: cyclists dismount at depths >= 0.2 m.
* ``dismount_0.3``: cyclists dismount at depths >= 0.3 m.
* ``bike_slow_0.3``: cycling speed is capped at 0.78 m/s at depths >= 0.3 m.

The primary exposure metric (depth x distance) is speed-independent, so these
runs test the travel-time and delay conclusions, not the exposure ranking.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from flood_case_analysis import (
    DEFAULT_RESULTS_DIR,
    jaccard,
    load_link_table,
    parse_links,
    route_metrics,
)

DEFAULT_OUT_DIR = DEFAULT_RESULTS_DIR / "analysis"
SCENARIOS = ["base", "dismount_all", "dismount_0.2", "dismount_0.3", "bike_slow_0.3"]


def build_trips(
    results_dir: Path,
    scenario: str,
    lengths: dict[str, float],
    depths: dict[str, float],
) -> pd.DataFrame:
    records = []
    for mode in ("walk", "bike"):
        dry = pd.read_csv(results_dir / f"routes_dry_{mode}.csv")
        flood = pd.read_csv(results_dir / f"routes_flood_{mode}.csv")
        merged = dry.merge(flood, on="person", suffixes=("_c1", "_c3"), validate="one_to_one")
        for row in merged.itertuples(index=False):
            c1_links = parse_links(row.links_c1)
            c3_links = parse_links(row.links_c3)
            c1 = route_metrics(c1_links, mode, lengths, depths, flooded=False)
            c2 = route_metrics(c1_links, mode, lengths, depths, flooded=True, speed_scenario=scenario)
            c3 = route_metrics(c3_links, mode, lengths, depths, flooded=True, speed_scenario=scenario)
            records.append(
                {
                    "scenario": scenario,
                    "person": row.person,
                    "mode": mode,
                    "c1_time_s": c1["time_s"],
                    "c2_time_s": c2["time_s"],
                    "c3_time_s": c3["time_s"],
                    "c1_exp_dd": c1["exp_depth_distance"],
                    "c3_exp_dd": c3["exp_depth_distance"],
                    "c1_passable": not c1["blocked"],
                    "c2_passable": not c2["blocked"],
                    "c3_passable": not c3["blocked"],
                    "c1_footprint": c1["footprint"],
                    "c3_same_as_c1": c1_links == c3_links,
                    "c1_c3_jaccard": jaccard(c1_links, c3_links),
                    "c2_max_depth_m": c2["max_depth_m"],
                    "c3_max_depth_m": c3["max_depth_m"],
                }
            )
    return pd.DataFrame(records)


def summarize(trips: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (scenario, mode), sub in trips.groupby(["scenario", "mode"], sort=False):
        c2_pass = sub["c2_passable"]
        c3_pass = sub["c3_passable"]
        both_pass = c2_pass & c3_pass
        c2_delay = (sub["c2_time_s"] - sub["c1_time_s"])[c2_pass]
        c3_delay = (sub["c3_time_s"] - sub["c1_time_s"])[c3_pass]
        c3_recovery = (sub["c2_time_s"] - sub["c3_time_s"])[both_pass]
        c3_ratio = (c3_delay / sub.loc[c3_pass, "c1_time_s"]).replace([np.inf, -np.inf], np.nan)
        c2_ratio = (c2_delay / sub.loc[c2_pass, "c1_time_s"]).replace([np.inf, -np.inf], np.nan)
        c3_exp = sub["c3_exp_dd"][c3_pass]
        c1_exp = sub["c1_exp_dd"][c2_pass]
        rows.append(
            {
                "scenario": scenario,
                "mode": mode,
                "n": int(len(sub)),
                "c2_blocked": int((~c2_pass).sum()),
                "c3_blocked": int((~c3_pass).sum()),
                "c1_median_s": float(sub.loc[c2_pass, "c1_time_s"].median()),
                "c2_median_s": float(sub.loc[c2_pass, "c2_time_s"].median()),
                "c3_median_s": float(sub.loc[c3_pass, "c3_time_s"].median()),
                "c2_c1_median_s": float(c2_delay.median()),
                "c3_c1_median_s": float(c3_delay.median()),
                "c3_c2_median_s": float(c3_recovery.median()) if len(c3_recovery) else np.nan,
                "c2_c1_share_gt_15pct": float((c2_ratio > 0.15).mean()),
                "c2_c1_share_gt_20pct": float((c2_ratio > 0.20).mean()),
                "c3_c1_share_gt_15pct": float((c3_ratio > 0.15).mean()),
                "c3_c1_share_gt_20pct": float((c3_ratio > 0.20).mean()),
                "c1_mean_exp_dd": float(c1_exp.mean()),
                "c1_median_exp_dd": float(c1_exp.median()),
                "c3_mean_exp_dd": float(c3_exp.mean()),
                "c3_median_exp_dd": float(c3_exp.median()),
                "c3_zero_exposure_share": float((c3_exp == 0).mean()),
                "c3_same_as_c1_share": float(sub["c3_same_as_c1"].mean()),
                "mean_jaccard_c1_c3": float(sub["c1_c3_jaccard"].mean()),
            }
        )
    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results-dir", type=Path, default=DEFAULT_RESULTS_DIR)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    lengths, depths = load_link_table(args.results_dir / "link_flood_depths.csv")
    frames = [build_trips(args.results_dir, scenario, lengths, depths) for scenario in SCENARIOS]
    trips = pd.concat(frames, ignore_index=True)
    trips.to_csv(args.out_dir / "flood_speed_sensitivity_trips.csv", index=False)
    summary = summarize(trips)
    summary.to_csv(args.out_dir / "flood_speed_sensitivity_summary.csv", index=False)

    print("=== Speed sensitivity ===")
    print(summary.to_string(index=False))
    print(f"\nWrote outputs to {args.out_dir}")


if __name__ == "__main__":
    main()
