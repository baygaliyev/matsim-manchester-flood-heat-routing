#!/usr/bin/env python
"""Plot the RoFSW flood extent, assigned link depths, and threshold panel.

The main figure has two panels:
(a) flooded links coloured by assigned depth, with the RoFSW High-risk polygons
    outlined and a schematic inset locating the 24 x 28 km footprint inside the
    79 x 64 km network;
(b) counts of flooded links in the depth classes used by the speed curves, with
    the 0.3 m and 0.6 m thresholds marked.

RoFSW shapefiles are read with pyogrio; network geometry comes from the parquet
cache built by ``build_network_cache.py``.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import contextily as ctx
import geopandas as gpd
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import LinearSegmentedColormap
from shapely.geometry import LineString

PROJECT_ROOT = Path(__file__).resolve().parents[5]
DEFAULT_RESULTS = PROJECT_ROOT / "results"
DEFAULT_INPUT = PROJECT_ROOT / "data" / "input"
DEFAULT_OUT_DIR = PROJECT_ROOT / "writing" / "aliyev_saadi_flood_routing" / "figures"
DEFAULT_CACHE = PROJECT_ROOT / "results" / "network_cache"
DEFAULT_ROFSW = DEFAULT_INPUT / "Risk of Flooding from Surface Water.zip"
DEFAULT_LINK_DEPTHS = DEFAULT_RESULTS / "link_flood_depths.csv"


DEPTH_CMAP = LinearSegmentedColormap.from_list(
    "flood_depth",
    ["#ffffcc", "#a1dab4", "#41b6c4", "#2c7fb8", "#253494"],
)


def load_network(cache_dir: Path) -> gpd.GeoDataFrame:
    nodes = pd.read_parquet(cache_dir / "network_nodes.parquet").set_index("node_id")
    links = pd.read_parquet(cache_dir / "network_links.parquet")
    x1 = nodes.loc[links["from_node"], "x"].to_numpy()
    y1 = nodes.loc[links["from_node"], "y"].to_numpy()
    x2 = nodes.loc[links["to_node"], "x"].to_numpy()
    y2 = nodes.loc[links["to_node"], "y"].to_numpy()
    geoms = [LineString([(a, b), (c, d)]) for a, b, c, d in zip(x1, y1, x2, y2)]
    return gpd.GeoDataFrame(
        links[["link_id", "from_node", "to_node"]].copy(),
        geometry=geoms,
        crs="EPSG:27700",
    )


def load_rofsw(zip_path: Path) -> gpd.GeoDataFrame:
    path = f"/vsizip/{zip_path}/rofswPolygon.shp"
    gdf = gpd.read_file(path)
    if gdf.crs is None:
        gdf = gdf.set_crs("EPSG:27700")
    elif gdf.crs.to_epsg() != 27700:
        gdf = gdf.to_crs("EPSG:27700")
    return gdf


def depth_class_counts(depths: pd.Series) -> pd.DataFrame:
    bins = [
        ("0.1-0.2 m", 0.1, 0.2),
        ("0.2-0.3 m", 0.2, 0.3),
        ("0.3-0.6 m", 0.3, 0.6),
        (">= 0.6 m", 0.6, np.inf),
    ]
    rows = []
    for label, lower, upper in bins:
        count = int(((depths >= lower - 1e-9) & (depths < upper - 1e-9)).sum())
        rows.append({"class": label, "count": count})
    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--link-depths", type=Path, default=DEFAULT_LINK_DEPTHS)
    parser.add_argument("--rofsw", type=Path, default=DEFAULT_ROFSW)
    parser.add_argument("--formats", nargs="+", default=["png", "pdf", "jpg"])
    parser.add_argument("--no-basemap", action="store_true")
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    print("Loading network...")
    net = load_network(args.cache_dir)
    depths = pd.read_csv(args.link_depths, dtype={"link_id": str})[["link_id", "flood_depth"]]
    net = net.merge(depths, on="link_id", how="left").fillna({"flood_depth": 0.0})
    net_flood = net[net["flood_depth"] > 0].copy()
    print(f"Flooded network links to plot: {len(net_flood):,}")

    print("Loading RoFSW...")
    rofsw = load_rofsw(args.rofsw)
    rofsw_high = rofsw[rofsw["risk_band"].str.lower() == "high"]
    print(f"RoFSW High polygons: {len(rofsw_high):,}")

    fxmin, fymin, fxmax, fymax = rofsw_high.total_bounds
    pad = 1200

    fig, (ax, axb) = plt.subplots(
        1,
        2,
        figsize=(13.2, 6.2),
        gridspec_kw={"width_ratios": [1.55, 1.0]},
    )

    # (a) depth map
    ax.set_facecolor("#f7f7f7")
    net.plot(ax=ax, color="#d0d0d0", linewidth=0.08, alpha=0.45)
    net_flood.plot(
        ax=ax,
        column="flood_depth",
        cmap=DEPTH_CMAP,
        linewidth=0.55,
        alpha=0.95,
        vmin=0.01,
        vmax=0.6,
    )
    rofsw_high.boundary.plot(ax=ax, color="#b2182b", linewidth=0.35, alpha=0.7)
    ax.set_xlim(fxmin - pad, fxmax + pad)
    ax.set_ylim(fymin - pad, fymax + pad)
    ax.set_xlabel("Easting (m)")
    ax.set_ylabel("Northing (m)")
    ax.set_title("(a) Assigned flood depths (1-in-30 High-risk extent)", loc="left")
    ax.set_aspect("equal")

    # Colourbar aligned to panel (a)
    import matplotlib.cm as cm
    import matplotlib.colors as mcolors
    from mpl_toolkits.axes_grid1 import make_axes_locatable

    norm = mcolors.Normalize(vmin=0.0, vmax=0.6)
    sm = cm.ScalarMappable(norm=norm, cmap=DEPTH_CMAP)
    divider = make_axes_locatable(ax)
    cax = divider.append_axes("bottom", size="5%", pad=0.5)
    cb = fig.colorbar(sm, cax=cax, orientation="horizontal")
    cb.set_label("Flood depth (m)", fontsize=10)
    cb.ax.tick_params(labelsize=9)

    if not args.no_basemap:
        try:
            ctx.add_basemap(ax, crs="EPSG:27700", source=ctx.providers.Esri.WorldGrayCanvas, alpha=0.55)
        except Exception as exc:
            print(f"Basemap unavailable: {exc}")

    # (b) threshold panel
    counts = depth_class_counts(net_flood["flood_depth"])
    colors = ["#ffffcc", "#a1dab4", "#41b6c4", "#253494"]
    bars = axb.barh(
        counts["class"],
        counts["count"],
        color=colors,
        edgecolor="#333333",
        linewidth=0.5,
    )
    axb.set_xlabel("Number of flooded links")
    axb.set_title("(b) Depth classes and thresholds", loc="left")
    axb.grid(axis="x", color="#dddddd", linewidth=0.6)
    axb.set_axisbelow(True)
    max_count = counts["count"].max()
    for bar, count in zip(bars, counts["count"]):
        axb.text(
            count + max_count * 0.01,
            bar.get_y() + bar.get_height() / 2,
            f"{count:,} ({100 * count / len(net):.2f}% of network)",
            va="center",
            fontsize=8,
        )
    axb.set_xlim(0, 58000)
    axb.invert_yaxis()

    fig.tight_layout(rect=(0, 0.1, 1, 1))
    for fmt in args.formats:
        path = args.out_dir / f"flood_extent_map.{fmt}"
        if fmt == "jpg":
            fig.savefig(path, dpi=300, bbox_inches="tight", format="jpg")
        else:
            fig.savefig(path, dpi=300, bbox_inches="tight")
        print(f"Saved {path}")
    plt.close(fig)


if __name__ == "__main__":
    main()
