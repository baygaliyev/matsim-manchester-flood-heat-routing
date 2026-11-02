#!/usr/bin/env python
"""Detour-tolerance analysis for the 2,000-traveller flood weight sweep.

For each traveller, the dry fastest route (weight = 1) is the baseline.  A
candidate route is acceptable when its dry travel time is within a tolerance
tau of the baseline time.  Among acceptable routes we select the one with the
lowest flood exposure.  Exposure is reported as depth x distance (primary) and
depth x time (appendix).

The sweep CSV is malformed: every line is wrapped in an outer quote and the
path list is embedded verbatim.  The parser below repairs each line before
feeding it to ``csv.reader``.
"""

from __future__ import annotations

import argparse
import ast
import csv
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[5]
DEFAULT_DATA = PROJECT_ROOT / "data" / "flood_routes_2000_travelers.csv"
DEFAULT_LINKS = PROJECT_ROOT / "results" / "link_flood_depths.csv"
DEFAULT_OUT_DIR = PROJECT_ROOT / "results" / "analysis"

IMPASSABLE_DEPTH = 0.6
IMPASSABLE_SPEED = 0.001




def parse_line(line: str) -> list[str]:
    """Repair one malformed sweep line and parse it as CSV."""
    line = line.rstrip("\n").rstrip("\r")
    if line.startswith('"'):
        line = line[1:]
    if line.endswith('"'):
        line = line[:-1]
    line = line.replace('""', '"')
    return next(csv.reader([line]))


def speed_for_depth(mode: str, depth: float) -> float:
    if depth >= IMPASSABLE_DEPTH - 1e-9:
        return IMPASSABLE_SPEED
    if mode == "walk":
        if depth >= 0.3 - 1e-9:
            return 0.78
        if depth >= 0.2 - 1e-9:
            return 0.85
        if depth >= 0.1 - 1e-9:
            return 1.03
        return 1.27
    if depth >= 0.3 - 1e-9:
        return 1.31
    if depth >= 0.2 - 1e-9:
        return 1.76
    if depth >= 0.1 - 1e-9:
        return 2.04
    return 4.20


def load_shortest_links(path: Path) -> tuple[dict[tuple[int, int], tuple[float, float]], dict[str, float]]:
    """Map (from_node, to_node) to the shortest link's (length, depth)."""
    links = pd.read_csv(path, dtype={"link_id": str})
    pair_best: dict[tuple[int, int], tuple[float, float]] = {}
    lengths: dict[str, float] = {}
    for row in links.itertuples(index=False):
        key = (int(row.from_node), int(row.to_node))
        candidate = (float(row.length), float(row.flood_depth))
        current = pair_best.get(key)
        if current is None or candidate[0] < current[0]:
            pair_best[key] = candidate
        lengths[row.link_id] = float(row.length)
    return pair_best, lengths


def path_exposure(
    path: list[int],
    mode: str,
    pair_best: dict[tuple[int, int], tuple[float, float]],
) -> tuple[float, float, int]:
    """Return depth x distance, depth x time, and missing-pair count."""
    exp_dd = 0.0
    exp_dt = 0.0
    missing = 0
    for a, b in zip(path[:-1], path[1:]):
        pair = pair_best.get((a, b))
        if pair is None:
            missing += 1
            continue
        length, depth = pair
        exp_dd += depth * length
        if depth > 0:
            exp_dt += depth * length / speed_for_depth(mode, depth)
    return exp_dd, exp_dt, missing


def summarize(trips: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (mode, tau, metric), sub in trips.groupby(["mode", "tau", "metric"], sort=False):
        exposed = sub[sub["base_exp"] > 0]
        improved = sub[sub["improved"]]
        improved_exposed = improved[improved["base_exp"] > 0]
        all_reduction = sub["exposure_reduction"].fillna(0.0)
        rows.append(
            {
                "mode": mode,
                "tau": tau,
                "metric": metric,
                "n": int(len(sub)),
                "n_exposed": int(len(exposed)),
                "n_improved": int(len(improved)),
                "share_improved_all": float(len(improved) / len(sub)),
                "share_improved_exposed": float(len(improved_exposed) / len(exposed)) if len(exposed) else np.nan,
                "median_reduction_improved": float(improved["exposure_reduction"].median())
                if len(improved)
                else np.nan,
                "mean_reduction_improved": float(improved["exposure_reduction"].mean())
                if len(improved)
                else np.nan,
                "p90_reduction_improved": float(improved["exposure_reduction"].quantile(0.90))
                if len(improved)
                else np.nan,
                "median_time_penalty_improved": float(improved["time_penalty"].median())
                if len(improved)
                else np.nan,
                "mean_time_penalty_improved": float(improved["time_penalty"].mean())
                if len(improved)
                else np.nan,
                "p90_time_penalty_improved": float(improved["time_penalty"].quantile(0.90))
                if len(improved)
                else np.nan,
                "median_reduction_all": float(all_reduction.median()),
                "median_time_penalty_all": float(sub["time_penalty"].median()),
                "share_any_reduction": float((sub["exposure_reduction"].fillna(0) > 1e-9).mean()),
            }
        )
    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--links", type=Path, default=DEFAULT_LINKS)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--tolerances", type=float, nargs="+", default=[0.15, 0.20])
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    pair_best, _ = load_shortest_links(args.links)

    records: list[dict[str, object]] = []
    cache: dict[str, tuple[float, float, int]] = {}
    with args.data.open(encoding="utf-8", errors="replace", newline="") as handle:
        header = handle.readline().strip().split(",")
        for line in handle:
            raw = dict(zip(header, parse_line(line)))
            path = ast.literal_eval(raw["path"])
            mode = raw["mode"]
            key = (raw["path"], mode)
            if key not in cache:
                cache[key] = path_exposure(path, mode, pair_best)
            exp_dd, exp_dt, missing = cache[key]
            records.append(
                {
                    "person": raw["person"],
                    "mode": mode,
                    "weight": float(raw["weight"]),
                    "time_s": float(raw["fastestTime"]),
                    "exp_dd": exp_dd,
                    "exp_dt": exp_dt,
                    "missing_pairs": missing,
                }
            )

    sweep = pd.DataFrame(records)
    if sweep["missing_pairs"].sum():
        raise RuntimeError(f"{int(sweep['missing_pairs'].sum())} path links could not be mapped")

    if (sweep.groupby(["person", "mode"])["weight"].apply(lambda s: (s == 1.0).sum()) != 1).any():
        raise RuntimeError("each traveller must have exactly one weight=1 baseline row")

    output = []
    for tolerance in args.tolerances:
        for metric, base_col in (("dd", "exp_dd"), ("dt", "exp_dt")):
            for (person, mode), group in sweep.groupby(["person", "mode"], sort=False):
                baseline = group[group["weight"] == 1.0].iloc[0]
                candidates = group[group["time_s"] <= baseline["time_s"] * (1.0 + tolerance)]
                best = candidates.sort_values([base_col, "time_s", "weight"]).iloc[0]
                base_exp = float(baseline[base_col])
                opt_exp = float(best[base_col])
                improvement = base_exp - opt_exp
                output.append(
                    {
                        "person": person,
                        "mode": mode,
                        "tau": tolerance,
                        "metric": metric,
                        "base_time_s": float(baseline["time_s"]),
                        "base_exp": base_exp,
                        "opt_time_s": float(best["time_s"]),
                        "opt_exp": opt_exp,
                        "opt_weight": float(best["weight"]),
                        "time_penalty": float(best["time_s"] / baseline["time_s"] - 1.0),
                        "exposure_reduction": float(improvement / base_exp) if base_exp > 0 else np.nan,
                        "improved": bool(improvement > 1e-9),
                    }
                )

    trips = pd.DataFrame(output)
    trips.to_csv(args.out_dir / "flood_detour_tolerance_trips.csv", index=False)
    summary = summarize(trips)
    summary.to_csv(args.out_dir / "flood_detour_tolerance_summary.csv", index=False)

    print("=== Detour tolerance ===")
    print(summary.to_string(index=False))
    print(f"\nWrote outputs to {args.out_dir}")


if __name__ == "__main__":
    main()
