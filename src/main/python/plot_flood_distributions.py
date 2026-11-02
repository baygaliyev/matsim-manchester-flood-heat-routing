#!/usr/bin/env python
"""Plot travel-time and exposure distributions for the flood case study."""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[5]
DEFAULT_METRICS = PROJECT_ROOT / "results" / "analysis" / "flood_trips_metrics.csv"
DEFAULT_OUT_DIR = PROJECT_ROOT / "writing" / "aliyev_saadi_flood_routing" / "figures"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metrics", type=Path, default=DEFAULT_METRICS)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--formats", nargs="+", default=["png", "pdf", "jpg"])
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    m = pd.read_csv(args.metrics)
    fig, axes = plt.subplots(2, 2, figsize=(11.0, 7.6))
    colors = {"C1": "#7f7f7f", "C2": "#d62728", "C3": "#1f77b4"}
    labels = {"C1": "C1 dry route / dry", "C2": "C2 dry route / flood", "C3": "C3 adaptive / flood"}

    plt.rcParams.update({"font.size": 9})

    for ax, mode in zip(axes[0], ["walk", "bike"]):
        sub = m[m["mode"] == mode]
        passable = sub["c1_passable"] & sub["c3_passable"]
        for scenario, col in [("C1", "c1_time_s"), ("C2", "c2_time_s"), ("C3", "c3_time_s")]:
            data = sub.loc[passable, col] / 60.0
            data = data[(data >= 0) & (data <= 60)]
            ax.hist(
                data,
                bins=40,
                histtype="step",
                linewidth=1.8,
                color=colors[scenario],
                label=labels[scenario],
                density=False,
            )
        ax.set_title(
            f"({['a','b'][['walk','bike'].index(mode)]}) {mode.capitalize()} travel time (passable)",
            loc="left",
            fontsize=12,
        )
        ax.set_xlabel("Travel time (min)", fontsize=10)
        ax.set_ylabel("Count", fontsize=10)
        ax.tick_params(labelsize=9)
        ax.legend(fontsize=8, frameon=True, facecolor="white", framealpha=0.85, loc="upper right")

    for ax, mode in zip(axes[1], ["walk", "bike"]):
        sub = m[m["mode"] == mode]
        passable = sub["c1_passable"] & sub["c3_passable"]
        for scenario, col in [
            ("C1", "c1_exp_depth_distance"),
            ("C2", "c2_exp_depth_distance"),
            ("C3", "c3_exp_depth_distance"),
        ]:
            data = sub.loc[passable, col]
            data = data[data >= 0]
            ax.hist(
                data,
                bins=40,
                histtype="step",
                linewidth=1.8,
                color=colors[scenario],
                label=labels[scenario],
            )
        ax.set_yscale("log")
        ax.set_title(
            f"({['c','d'][['walk','bike'].index(mode)]}) {mode.capitalize()} exposure depth×distance (passable)",
            loc="left",
            fontsize=12,
        )
        ax.set_xlabel("Exposure (m²)", fontsize=10)
        ax.set_ylabel("Count", fontsize=10)
        ax.tick_params(labelsize=9)
        ax.legend(fontsize=8, frameon=True, facecolor="white", framealpha=0.85, loc="upper right")

    fig.tight_layout()
    for fmt in args.formats:
        path = args.out_dir / f"flood_distributions.{fmt}"
        if fmt == "jpg":
            fig.savefig(path, dpi=300, bbox_inches="tight", format="jpg")
        else:
            fig.savefig(path, dpi=300, bbox_inches="tight")
        print(f"Saved {path}")
    plt.close(fig)


if __name__ == "__main__":
    main()
