#!/usr/bin/env python
"""Plot example C1 (dry) and C3 (adaptive) routes over the flood map.

Two panels show one walking and one cycling trip. Routes are drawn from the
MATSim link sequences and node coordinates in the network cache; flooded links
in the local window are coloured by depth.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import geopandas as gpd
import matplotlib.lines as mlines
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.cm import ScalarMappable
from matplotlib.colors import LinearSegmentedColormap, Normalize
from matplotlib.ticker import FuncFormatter
from shapely.geometry import LineString

PROJECT_ROOT = Path(__file__).resolve().parents[5]
DEFAULT_RESULTS = PROJECT_ROOT / "results"
DEFAULT_CACHE = PROJECT_ROOT / "results" / "network_cache"
DEFAULT_METRICS = DEFAULT_RESULTS / "analysis" / "flood_trips_metrics.csv"
DEFAULT_OUT_DIR = PROJECT_ROOT / "writing" / "aliyev_saadi_flood_routing" / "figures"


DEPTH_CMAP = LinearSegmentedColormap.from_list(
    "flood_depth",
    ["#ffffcc", "#a1dab4", "#41b6c4", "#2c7fb8", "#253494"],
)


def parse_links(value: str) -> list[str]:
    import re

    return re.findall(r"[^\s,\[\]]+", str(value))


def load_geometry(cache_dir: Path):
    nodes = pd.read_parquet(cache_dir / "network_nodes.parquet").set_index("node_id")
    links = pd.read_parquet(cache_dir / "network_links.parquet").set_index("link_id")
    return links, nodes["x"], nodes["y"]


def line_for_link(link_id: str, links, node_x, node_y) -> LineString | None:
    try:
        row = links.loc[link_id]
        a, b = int(row["from_node"]), int(row["to_node"])
        return LineString([(node_x.loc[a], node_y.loc[a]), (node_x.loc[b], node_y.loc[b])])
    except KeyError:
        return None


def gdf_for_links(link_ids, links, node_x, node_y) -> gpd.GeoDataFrame:
    geoms = []
    kept = []
    for link_id in link_ids:
        geom = line_for_link(link_id, links, node_x, node_y)
        if geom is not None:
            geoms.append(geom)
            kept.append(link_id)
    return gpd.GeoDataFrame({"link_id": kept}, geometry=geoms, crs="EPSG:27700")


def pick_example(metrics: pd.DataFrame, mode: str, person: int | None) -> int:
    if person is not None:
        return person
    s = metrics[(metrics["mode"] == mode) & metrics["c1_passable"] & metrics["c3_passable"]].copy()
    s = s[s["c1_footprint"] & (s["c1_exp_depth_distance"] > 0)]
    s = s[s["c3_exp_depth_distance"] < 0.5 * s["c1_exp_depth_distance"]]
    s = s[s["c3_delay_pct"] <= 0.20]
    s = s[(s["c1_jaccard_c3"] < 0.85) & (s["c1_time_s"].between(300, 1800))]
    depth_floor = 0.2 if mode == "walk" else 0.3
    s = s[s["c1_max_depth_m"] >= depth_floor - 1e-9]
    if s.empty:
        raise RuntimeError(f"no suitable {mode} example found")
    median_exp = s["c1_exp_depth_distance"].median()
    s = s.assign(
        score=(np.log(s["c1_exp_depth_distance"] / median_exp)).abs()
        + (s["c1_jaccard_c3"] - 0.60).abs()
    )
    return int(s.sort_values("score").iloc[0]["person"])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metrics", type=Path, default=DEFAULT_METRICS)
    parser.add_argument("--results-dir", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--walk-person", type=int, default=None)
    parser.add_argument("--bike-person", type=int, default=None)
    parser.add_argument("--formats", nargs="+", default=["png", "pdf", "jpg"])
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    metrics_df = pd.read_csv(args.metrics)
    walk_person = pick_example(metrics_df, "walk", args.walk_person)
    bike_person = pick_example(metrics_df, "bike", args.bike_person)
    print(f"Example walk person: {walk_person}, bike person: {bike_person}")

    links, node_x, node_y = load_geometry(args.cache_dir)
    depth_table = pd.read_csv(args.results_dir / "link_flood_depths.csv", dtype={"link_id": str})
    depths = dict(zip(depth_table["link_id"], depth_table["flood_depth"]))

    fig, axes = plt.subplots(1, 2, figsize=(8.0, 5.2))
    map_config = {
        "walk": {
            "title": "(a) Walking",
            "xlim": (380300, 381700),
            "ylim": (403600, 405900),
        },
        "bike": {
            "title": "(b) Cycling",
            "xlim": (384300, 386200),
            "ylim": (386000, 392800),
        },
    }

    for ax, mode, person in zip(axes, ["walk", "bike"], [walk_person, bike_person]):
        cfg = map_config[mode]
        ax.set_title(cfg["title"], loc="left", fontsize=11, fontweight="bold", pad=8)

        dry = pd.read_csv(args.results_dir / f"routes_dry_{mode}.csv")
        flood = pd.read_csv(args.results_dir / f"routes_flood_{mode}.csv")
        drow = dry[dry["person"] == person].iloc[0]
        frow = flood[flood["person"] == person].iloc[0]
        c1_links = parse_links(drow["links"])
        c3_links = parse_links(frow["links"])
        c1_gdf = gdf_for_links(c1_links, links, node_x, node_y)
        c3_gdf = gdf_for_links(c3_links, links, node_x, node_y)

        from_nodes = links["from_node"].to_numpy()
        to_nodes = links["to_node"].to_numpy()
        x1n = node_x.reindex(from_nodes).to_numpy()
        y1n = node_y.reindex(from_nodes).to_numpy()
        x2n = node_x.reindex(to_nodes).to_numpy()
        y2n = node_y.reindex(to_nodes).to_numpy()
        keep = (
            (np.maximum(x1n, x2n) >= cfg["xlim"][0] - 200)
            & (np.minimum(x1n, x2n) <= cfg["xlim"][1] + 200)
            & (np.maximum(y1n, y2n) >= cfg["ylim"][0] - 200)
            & (np.minimum(y1n, y2n) <= cfg["ylim"][1] + 200)
        )
        idx = np.flatnonzero(keep)
        local_gdf = gpd.GeoDataFrame(
            {"link_id": links.index.to_numpy()[idx]},
            geometry=[LineString([(x1n[i], y1n[i]), (x2n[i], y2n[i])]) for i in idx],
            crs="EPSG:27700",
        )
        local_gdf["flood_depth"] = local_gdf["link_id"].map(depths).fillna(0.0)
        local_gdf.plot(ax=ax, color="#d0d7de", linewidth=0.4, alpha=0.6, zorder=1)
        flooded = local_gdf[local_gdf["flood_depth"] > 0]
        if len(flooded):
            flooded.plot(
                ax=ax,
                column="flood_depth",
                cmap=DEPTH_CMAP,
                linewidth=1.2,
                vmin=0.01,
                vmax=0.6,
                alpha=0.95,
                zorder=2,
            )

        c1_gdf.plot(ax=ax, color="#f39c12", linewidth=2.4, linestyle=(0, (5, 2)), alpha=0.95, zorder=3)
        c3_gdf.plot(ax=ax, color="#1f4e78", linewidth=2.4, alpha=0.95, zorder=4)
        start = c1_gdf.geometry.iloc[0].coords[0]
        end = c1_gdf.geometry.iloc[-1].coords[-1]
        ax.scatter([start[0]], [start[1]], s=55, marker="o", color="#27ae60", edgecolor="white", zorder=5)
        ax.scatter([end[0]], [end[1]], s=65, marker="*", color="#e74c3c", edgecolor="white", zorder=5)

        ax.set_xlim(cfg["xlim"])
        ax.set_ylim(cfg["ylim"])
        ax.set_aspect("equal")
        ax.xaxis.set_major_locator(plt.MaxNLocator(nbins=3))
        ax.yaxis.set_major_locator(plt.MaxNLocator(nbins=5))
        ax.xaxis.set_major_formatter(FuncFormatter(lambda x, _: f"{x / 1000:.1f}"))
        ax.yaxis.set_major_formatter(FuncFormatter(lambda y, _: f"{y / 1000:.1f}"))
        ax.set_xlabel("Easting (km)", fontsize=9.5)
        ax.set_ylabel("Northing (km)", fontsize=9.5)
        ax.tick_params(axis="both", labelsize=8.5)

    route_handles = [
        mlines.Line2D([], [], color="#f39c12", linewidth=2.4, linestyle=(0, (5, 2)), label="C1 dry route"),
        mlines.Line2D([], [], color="#1f4e78", linewidth=2.4, label="C3 adaptive route"),
        mlines.Line2D([], [], color="#27ae60", marker="o", linestyle="None", markersize=6, label="Origin"),
        mlines.Line2D([], [], color="#e74c3c", marker="*", linestyle="None", markersize=7, label="Destination"),
    ]
    fig.legend(
        handles=route_handles,
        loc="upper center",
        bbox_to_anchor=(0.5, 1.02),
        ncol=4,
        frameon=True,
        fontsize=8.5,
    )

    sm = ScalarMappable(norm=Normalize(0.0, 0.6), cmap=DEPTH_CMAP)
    cax = fig.add_axes([0.22, 0.04, 0.56, 0.022])
    cbar = fig.colorbar(sm, cax=cax, orientation="horizontal")
    cbar.set_label("Flood depth (m)", fontsize=9)
    cbar.ax.tick_params(labelsize=8)

    fig.tight_layout(rect=(0, 0.08, 1, 0.95))
    fig.subplots_adjust(wspace=0.15)
    for fmt in args.formats:
        path = args.out_dir / f"flood_routes_map.{fmt}"
        if fmt == "jpg":
            fig.savefig(path, dpi=300, bbox_inches="tight", format="jpg")
        else:
            fig.savefig(path, dpi=300, bbox_inches="tight")
        print(f"Saved {path}")
    plt.close(fig)


if __name__ == "__main__":
    main()
