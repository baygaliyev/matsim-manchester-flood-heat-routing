#!/usr/bin/env python
"""Recompute flood case-study metrics from MATSim route outputs.

The MATSim exports contain the dry route (Case 1), the adaptive route
(Case 3), and link-level flood depths.  Case 2 is the dry route evaluated on
the flooded network.  This script reconstructs all three cases from the link
sequences so that exposure can be expressed as depth x distance as well as the
legacy depth x time metric.

Outputs are written to ``results/analysis`` by default.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[5]
DEFAULT_RESULTS_DIR = PROJECT_ROOT / "results"
DEFAULT_OUT_DIR = DEFAULT_RESULTS_DIR / "analysis"

IMPASSABLE_DEPTH = 0.6
IMPASSABLE_SPEED = 0.001  # m/s, matches ManchesterFloodRouting.java

WALK_KEYS = np.array([0.0, 0.1, 0.2, 0.3])
WALK_SPEEDS = np.array([1.27, 1.03, 0.85, 0.78])
BIKE_KEYS = np.array([0.0, 0.1, 0.2, 0.3])
BIKE_SPEEDS = np.array([4.20, 2.04, 1.76, 1.31])


def parse_links(value: str) -> list[str]:
    """Parse a MATSim link-list cell such as ``[12out, 13rtn]``."""
    return re.findall(r"[^\s,\[\]]+", str(value))


def flood_speed(mode: str, depth: np.ndarray, scenario: str = "base") -> np.ndarray:
    """Depth-dependent speed lookup matching the Java implementation.

    ``scenario`` supports post-hoc sensitivity checks for cyclists who dismount
    in water instead of riding through it.
    """
    depth = np.asarray(depth, dtype=float)
    if mode == "walk":
        keys, speeds = WALK_KEYS, WALK_SPEEDS
    elif mode == "bike":
        keys, speeds = BIKE_KEYS, BIKE_SPEEDS
    else:
        raise ValueError(f"unknown mode: {mode}")

    idx = np.searchsorted(keys, depth, side="right") - 1
    idx = np.clip(idx, 0, len(keys) - 1)
    speed = speeds[idx]

    if mode == "bike" and scenario != "base":
        walk_idx = np.searchsorted(WALK_KEYS, depth, side="right") - 1
        walk_idx = np.clip(walk_idx, 0, len(WALK_KEYS) - 1)
        walk_speed = WALK_SPEEDS[walk_idx]
        if scenario == "dismount_all":
            mask = depth > 1e-9
        elif scenario == "dismount_0.2":
            mask = depth >= 0.2 - 1e-9
        elif scenario == "dismount_0.3":
            mask = depth >= 0.3 - 1e-9
        elif scenario == "bike_slow_0.3":
            mask = depth >= 0.3 - 1e-9
            walk_speed = np.full_like(depth, 0.78)
        else:
            raise ValueError(f"unknown speed scenario: {scenario}")
        speed = np.where(mask, walk_speed, speed)

    speed = np.where(depth >= IMPASSABLE_DEPTH - 1e-9, IMPASSABLE_SPEED, speed)
    return speed


def route_metrics(
    link_ids: list[str],
    mode: str,
    lengths: dict[str, float],
    depths: dict[str, float],
    flooded: bool,
    speed_scenario: str = "base",
) -> dict[str, float]:
    """Compute time and exposure metrics for one link sequence."""
    missing = [link for link in link_ids if link not in lengths]
    if missing:
        raise KeyError(f"{len(missing)} route links missing from link table: {missing[:5]}")

    length = np.array([lengths[link] for link in link_ids], dtype=float)
    depth = np.array([depths[link] for link in link_ids], dtype=float)

    if flooded:
        speed = flood_speed(mode, depth, scenario=speed_scenario)
        time = float(np.sum(length / speed))
        exp_dt = float(np.sum(depth * length / speed))
    else:
        dry_speed = 1.27 if mode == "walk" else 4.20
        speed = np.full_like(length, dry_speed)
        time = float(np.sum(length / speed))
        exp_dt = 0.0

    blocked = bool(np.any(depth >= IMPASSABLE_DEPTH - 1e-9))
    return {
        "n_links": int(len(link_ids)),
        "length_m": float(np.sum(length)),
        "time_s": time,
        "exp_depth_distance": float(np.sum(depth * length)),
        "exp_depth_time": exp_dt,
        "flooded_length_m": float(np.sum(length[depth > 0])),
        "max_depth_m": float(np.max(depth)) if len(depth) else 0.0,
        "n_flooded_links": int(np.sum(depth > 0)),
        "n_blocked_links": int(np.sum(depth >= IMPASSABLE_DEPTH - 1e-9)),
        "blocked": blocked,
        "footprint": bool(np.any(depth > 0)),
        "mean_speed_mps": float(np.sum(length) / time) if time > 0 else np.nan,
    }


def jaccard(a: list[str], b: list[str]) -> float:
    sa, sb = set(a), set(b)
    if not sa and not sb:
        return 1.0
    return len(sa & sb) / len(sa | sb)


def load_link_table(path: Path) -> tuple[dict[str, float], dict[str, float]]:
    links = pd.read_csv(path, dtype={"link_id": str})
    lengths = dict(zip(links["link_id"], links["length"].astype(float)))
    depths = dict(zip(links["link_id"], links["flood_depth"].astype(float)))
    return lengths, depths


def summarize_travel_times(trips: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for mode in ("walk", "bike"):
        sub = trips[trips["mode"] == mode]
        for scenario, time_col, pass_col in (
            ("C1", "c1_time_s", "c1_passable"),
            ("C2", "c2_time_s", "c2_passable"),
            ("C3", "c3_time_s", "c3_passable"),
        ):
            for subset, mask in (
                ("all", pd.Series(True, index=sub.index)),
                ("passable", sub[pass_col]),
                ("footprint", sub["c1_footprint"]),
                ("footprint_passable", sub["c1_footprint"] & sub[pass_col]),
            ):
                values = sub.loc[mask, time_col].dropna()
                if values.empty:
                    continue
                rows.append(
                    {
                        "mode": mode,
                        "scenario": scenario,
                        "subset": subset,
                        "n": int(len(values)),
                        "median_s": float(values.median()),
                        "mean_s": float(values.mean()),
                        "p90_s": float(values.quantile(0.90)),
                        "max_s": float(values.max()),
                    }
                )
    return pd.DataFrame(rows)


def summarize_delays(trips: pd.DataFrame) -> pd.DataFrame:
    rows = []
    comparisons = (
        ("C2-C1", "c2_time_s", "c1_time_s", "c2_passable"),
        ("C3-C1", "c3_time_s", "c1_time_s", "c3_passable"),
        ("C3-C2", "c2_time_s", "c3_time_s", "c2_passable & c3_passable"),
    )
    for mode in ("walk", "bike"):
        sub = trips[trips["mode"] == mode]
        for label, a_col, b_col, pass_expr in comparisons:
            # C3-C2 recovery: positive means adaptive is faster than uninformed.
            delta = sub[a_col] - sub[b_col]
            pass_mask = sub.eval(pass_expr) if isinstance(pass_expr, str) else pass_expr
            for subset, mask in (
                ("passable", pass_mask),
                ("footprint_passable", sub["c1_footprint"] & pass_mask),
            ):
                values = delta[mask].dropna()
                if values.empty:
                    continue
                base = sub.loc[mask, "c1_time_s"]
                ratio = values / base.replace(0, np.nan)
                rows.append(
                    {
                        "mode": mode,
                        "comparison": label,
                        "subset": subset,
                        "n": int(len(values)),
                        "median_s": float(values.median()),
                        "mean_s": float(values.mean()),
                        "p90_s": float(values.quantile(0.90)),
                        "share_gt_15pct": float((ratio > 0.15).mean()),
                        "share_gt_20pct": float((ratio > 0.20).mean()),
                        "share_gt_30pct": float((ratio > 0.30).mean()),
                    }
                )
    return pd.DataFrame(rows)


def summarize_exposure(trips: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for mode in ("walk", "bike"):
        sub = trips[trips["mode"] == mode]
        for scenario, dd_col, dt_col, pass_col in (
            ("C1", "c1_exp_depth_distance", "c1_exp_depth_time", "c1_passable"),
            ("C2", "c2_exp_depth_distance", "c2_exp_depth_time", "c2_passable"),
            ("C3", "c3_exp_depth_distance", "c3_exp_depth_time", "c3_passable"),
        ):
            for subset, mask in (
                ("all", pd.Series(True, index=sub.index)),
                ("passable", sub[pass_col]),
                ("footprint", sub["c1_footprint"]),
            ):
                s = sub.loc[mask]
                if s.empty:
                    continue
                rows.append(
                    {
                        "mode": mode,
                        "scenario": scenario,
                        "subset": subset,
                        "n": int(len(s)),
                        "mean_exp_dd": float(s[dd_col].mean()),
                        "median_exp_dd": float(s[dd_col].median()),
                        "mean_exp_dt": float(s[dt_col].mean()),
                        "median_exp_dt": float(s[dt_col].median()),
                        "mean_flooded_length_m": float(s[f"{scenario.lower()}_flooded_length_m"].mean()),
                        "median_flooded_length_m": float(s[f"{scenario.lower()}_flooded_length_m"].median()),
                        "mean_max_depth_m": float(s[f"{scenario.lower()}_max_depth_m"].mean()),
                        "share_zero_exposure": float((s[dd_col] == 0).mean()),
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

    all_trips = []
    for mode in ("walk", "bike"):
        dry = pd.read_csv(args.results_dir / f"routes_dry_{mode}.csv")
        flood = pd.read_csv(args.results_dir / f"routes_flood_{mode}.csv")
        if len(dry) != len(flood):
            raise ValueError(f"{mode}: dry/flood row count mismatch")
        merged = dry.merge(flood, on="person", suffixes=("_c1", "_c3"), validate="one_to_one")
        if not (merged["origin_c1"].astype(str) == merged["origin_c3"].astype(str)).all():
            raise ValueError(f"{mode}: origin mismatch between dry and flood routes")

        for row in merged.itertuples(index=False):
            c1_links = parse_links(row.links_c1)
            c3_links = parse_links(row.links_c3)
            c1 = route_metrics(c1_links, mode, lengths, depths, flooded=False)
            c2 = route_metrics(c1_links, mode, lengths, depths, flooded=True)
            c3 = route_metrics(c3_links, mode, lengths, depths, flooded=True)

            all_trips.append(
                {
                    "person": row.person,
                    "mode": mode,
                    "origin": int(row.origin_c1),
                    "destination": int(row.destination_c1),
                    "c1_time_s": c1["time_s"],
                    "c2_time_s": c2["time_s"],
                    "c3_time_s": c3["time_s"],
                    "c1_time_csv_s": float(row.travel_time_c1),
                    "c3_time_csv_s": float(row.travel_time_c3),
                    "c1_exp_depth_distance": c1["exp_depth_distance"],
                    "c2_exp_depth_distance": c2["exp_depth_distance"],
                    "c3_exp_depth_distance": c3["exp_depth_distance"],
                    "c1_exp_depth_time": c1["exp_depth_time"],
                    "c2_exp_depth_time": c2["exp_depth_time"],
                    "c3_exp_depth_time": c3["exp_depth_time"],
                    "c1_length_m": c1["length_m"],
                    "c2_length_m": c2["length_m"],
                    "c3_length_m": c3["length_m"],
                    "c1_flooded_length_m": c1["flooded_length_m"],
                    "c2_flooded_length_m": c2["flooded_length_m"],
                    "c3_flooded_length_m": c3["flooded_length_m"],
                    "c1_max_depth_m": c1["max_depth_m"],
                    "c2_max_depth_m": c2["max_depth_m"],
                    "c3_max_depth_m": c3["max_depth_m"],
                    "c1_n_flooded_links": c1["n_flooded_links"],
                    "c2_n_flooded_links": c2["n_flooded_links"],
                    "c3_n_flooded_links": c3["n_flooded_links"],
                    "c1_n_blocked_links": c1["n_blocked_links"],
                    "c2_n_blocked_links": c2["n_blocked_links"],
                    "c3_n_blocked_links": c3["n_blocked_links"],
                    "c1_passable": not c1["blocked"],
                    "c2_passable": not c2["blocked"],
                    "c3_passable": not c3["blocked"],
                    "c1_footprint": c1["footprint"],
                    "c2_footprint": c2["footprint"],
                    "c3_footprint": c3["footprint"],
                    "c1_jaccard_c3": jaccard(c1_links, c3_links),
                    "c3_same_as_c1": c1_links == c3_links,
                    "c2_same_as_c1": True,
                }
            )

    trips = pd.DataFrame(all_trips)
    trips["c2_delay_s"] = trips["c2_time_s"] - trips["c1_time_s"]
    trips["c3_delay_s"] = trips["c3_time_s"] - trips["c1_time_s"]
    trips["recovery_s"] = trips["c2_time_s"] - trips["c3_time_s"]
    trips["c2_delay_pct"] = trips["c2_delay_s"] / trips["c1_time_s"]
    trips["c3_delay_pct"] = trips["c3_delay_s"] / trips["c1_time_s"]

    trips.to_csv(args.out_dir / "flood_trips_metrics.csv", index=False)
    summarize_travel_times(trips).to_csv(args.out_dir / "flood_travel_time_summary.csv", index=False)
    summarize_delays(trips).to_csv(args.out_dir / "flood_delay_summary.csv", index=False)
    summarize_exposure(trips).to_csv(args.out_dir / "flood_exposure_summary.csv", index=False)

    link_summary = {
        "network_links": int(len(lengths)),
        "flooded_links": int(sum(d > 0 for d in depths.values())),
        "links_ge_0_3m": int(sum(d >= 0.3 - 1e-9 for d in depths.values())),
        "links_ge_0_6m": int(sum(d >= 0.6 - 1e-9 for d in depths.values())),
        "links_ge_0_9m": int(sum(d >= 0.9 - 1e-9 for d in depths.values())),
        "links_ge_1_2m": int(sum(d >= 1.2 - 1e-9 for d in depths.values())),
    }
    link_summary["flooded_share"] = link_summary["flooded_links"] / link_summary["network_links"]
    link_summary["blocked_share_of_flooded"] = (
        link_summary["links_ge_0_6m"] / link_summary["flooded_links"] if link_summary["flooded_links"] else 0.0
    )
    (args.out_dir / "flood_link_summary.json").write_text(json.dumps(link_summary, indent=2), encoding="utf-8")

    trip_summary = []
    for mode in ("walk", "bike"):
        sub = trips[trips["mode"] == mode]
        trip_summary.append(
            {
                "mode": mode,
                "n": int(len(sub)),
                "c1_footprint": int(sub["c1_footprint"].sum()),
                "c1_footprint_share": float(sub["c1_footprint"].mean()),
                "c2_blocked": int((~sub["c2_passable"]).sum()),
                "c2_blocked_share": float((~sub["c2_passable"]).mean()),
                "c3_blocked": int((~sub["c3_passable"]).sum()),
                "c3_blocked_share": float((~sub["c3_passable"]).mean()),
                "c1_zero_exposure": int((sub["c1_exp_depth_distance"] == 0).sum()),
                "c3_zero_exposure": int((sub["c3_exp_depth_distance"] == 0).sum()),
                "c3_same_as_c1": int(sub["c3_same_as_c1"].sum()),
                "mean_jaccard_c1_c3": float(sub["c1_jaccard_c3"].mean()),
                "median_jaccard_c1_c3": float(sub["c1_jaccard_c3"].median()),
                "max_abs_time_diff_c1_csv": float((sub["c1_time_s"] - sub["c1_time_csv_s"]).abs().max()),
                "c3_csv_gt_2x_deterministic": int((sub["c3_time_csv_s"] > 2 * sub["c3_time_s"]).sum()),
                "c3_csv_gt_10000s": int((sub["c3_time_csv_s"] > 10000).sum()),
                "median_c3_csv_to_deterministic_ratio": float(
                    (sub["c3_time_csv_s"] / sub["c3_time_s"]).median()
                ),
            }
        )
    pd.DataFrame(trip_summary).to_csv(args.out_dir / "flood_trip_summary.csv", index=False)

    print("=== Flood case analysis ===")
    print(pd.DataFrame(trip_summary).to_string(index=False))
    print("\n=== Link summary ===")
    print(json.dumps(link_summary, indent=2))
    print("\n=== Travel times (passable) ===")
    tt = pd.read_csv(args.out_dir / "flood_travel_time_summary.csv")
    print(tt[tt["subset"] == "passable"].to_string(index=False))
    print("\n=== Delays (passable) ===")
    dd = pd.read_csv(args.out_dir / "flood_delay_summary.csv")
    print(dd[dd["subset"] == "passable"].to_string(index=False))
    print("\n=== Exposure (passable) ===")
    ee = pd.read_csv(args.out_dir / "flood_exposure_summary.csv")
    print(ee[ee["subset"] == "passable"].to_string(index=False))
    print(f"\nWrote outputs to {args.out_dir}")


if __name__ == "__main__":
    main()
