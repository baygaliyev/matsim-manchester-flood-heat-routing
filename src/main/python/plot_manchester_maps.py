#!/usr/bin/env python3
"""Generate flood depth map and WBGT heat map for Manchester paper."""

import struct, os, sys, argparse
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
from matplotlib.patches import Polygon
import contextily as ctx
from config import input_dir, figures_dir

def read_wbgt_binary(bin_path, meta_path):
    with open(meta_path) as f:
        meta = dict(line.strip().split("=", 1) for line in f if "=" in line and not line.startswith("scenario"))
    nx = int(meta["nx"]); ny = int(meta["ny"])
    x0 = float(meta["x0"]); y0 = float(meta["y0"])
    dx = float(meta["dx"]); dy = float(meta["dy"].split("\n")[0])
    with open(bin_path, "rb") as f:
        hdr = f.read(44)
        nx_h, ny_h, ns = struct.unpack("iii", hdr[:12])
        x0_h, y0_h, dx_h, dy_h = struct.unpack("dddd", hdr[12:44])
    data = np.fromfile(bin_path, dtype=np.float32, offset=44)
    data = data.reshape((ns, ny_h, nx_h))
    return data, nx, ny, x0, y0, abs(dx), abs(dy)

def plot_wbgt_map(bin_path, meta_path, output_png, title="WBGT (°C) – Peak Scenario",
                  vmin=None, vmax=None, show_cbar=True, show_ylabel=True):
    data, nx, ny, x0, y0, dx, dy = read_wbgt_binary(bin_path, meta_path)
    grid = data[0]  # single slice
    grid = np.ma.masked_where(grid <= 0, grid)

    extent = [x0, x0 + nx * dx, y0 - ny * dy, y0]
    fig, ax = plt.subplots(1, 1, figsize=(8, 7))
    if vmin is None: vmin = float(grid.min())
    if vmax is None: vmax = float(grid.max())
    im = ax.imshow(grid, extent=extent, origin="upper", cmap="RdYlBu_r",
                   vmin=vmin, vmax=vmax, aspect="auto")
    if show_cbar:
        plt.colorbar(im, ax=ax, label="WBGT (°C)", shrink=0.8)
    ctx.add_basemap(ax, crs="EPSG:32630", source=ctx.providers.Esri.WorldGrayCanvas, alpha=0.5)
    ax.set_title(title)
    ax.set_xlabel("Easting (m)")
    if show_ylabel:
        ax.set_ylabel("Northing (m)")
    else:
        ax.set_ylabel("")
        ax.tick_params(labelleft=False)
    plt.tight_layout()
    plt.savefig(output_png, dpi=150, bbox_inches="tight")
    print(f"  Wrote {output_png}")
    plt.close()

def plot_flood_map(csv_path, network_path, output_png, max_depth=1.2):
    """Plot flood depths on network links (requires flood CSV + network shape)."""
    import pandas as pd
    import geopandas as gpd

    depths = pd.read_csv(csv_path)
    links = gpd.read_file(network_path)
    merged = links.merge(depths, on="link_id", how="left")
    merged["flood_depth"] = merged["flood_depth"].fillna(0.0)

    fig, ax = plt.subplots(1, 1, figsize=(8, 7))
    merged.plot(column="flood_depth", ax=ax, cmap="Blues", linewidth=0.3,
                legend=True, vmin=0, vmax=max_depth,
                legend_kwds={"label": "Flood depth (m)", "shrink": 0.8})
    ctx.add_basemap(ax, crs="EPSG:32630", source=ctx.providers.Esri.WorldGrayCanvas, alpha=0.5)
    ax.set_title("Surface Water Flood Depth – RoFSW")
    ax.set_xlabel("Easting (m)"); ax.set_ylabel("Northing (m)")
    plt.tight_layout()
    plt.savefig(output_png, dpi=300, bbox_inches="tight")
    print(f"  Wrote {output_png}")
    plt.close()


if __name__ == "__main__":
    _ap = argparse.ArgumentParser(description=__doc__)
    _ap.add_argument("--input-dir", default=str(input_dir()),
                     help="Directory with the WBGT *.bin grids and wbgt_grid.meta")
    _ap.add_argument("--out-dir", default=str(figures_dir()),
                     help="Directory to write the PNG maps")
    _args = _ap.parse_args()

    base = _args.input_dir
    wbgt_bin = os.path.join(base, "wbgt_scenario_peak.bin")
    meta = os.path.join(base, "wbgt_grid.meta")

    out_dir = _args.out_dir
    os.makedirs(out_dir, exist_ok=True)

    print("=== WBGT Heat Map ===")
    scenarios = [("peak", "Peak (17:00, 30 Sep)"), ("commute", "Commute (Mon 08:00)"), ("weekend", "Weekend (Sat 12:00)")]
    # Compute global vmin/vmax across all scenarios
    vmin, vmax = float('inf'), float('-inf')
    grids = []
    for scenario, _ in scenarios:
        data, _, _, _, _, _, _ = read_wbgt_binary(os.path.join(base, f"wbgt_scenario_{scenario}.bin"), meta)
        g = data[0]
        g = np.ma.masked_where(g <= 0, g)
        grids.append(g)
        vmin = min(vmin, float(g.min()))
        vmax = max(vmax, float(g.max()))
    for idx, (scenario, label) in enumerate(scenarios):
        bin_path = os.path.join(base, f"wbgt_scenario_{scenario}.bin")
        plot_wbgt_map(bin_path, meta, os.path.join(out_dir, f"heatmap_manchester_{scenario}.png"),
                      title=f"WBGT (°C) – {label}",
                      vmin=vmin, vmax=vmax,
                      show_cbar=(idx == 2),
                      show_ylabel=(idx == 0))

    print("\n=== Flood Depth Map ===")
    print("(Requires link_flood_depths.csv + network shapefile from remote)")
    print("Run on remote after Java flood routing completes.")
