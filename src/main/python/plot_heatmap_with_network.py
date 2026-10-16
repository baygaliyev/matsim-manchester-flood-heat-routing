#!/usr/bin/env python3
"""Generate WBGT heatmap with MATSim road network overlay (single-pass stream from zip)."""
import struct, os, zipfile, argparse
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap
import contextily as ctx
import xml.etree.ElementTree as ET
from pyproj import Transformer
from shapely.geometry import LineString
import geopandas as gpd
from config import input_dir, figures_dir

EXAWARO_CMAP = LinearSegmentedColormap.from_list(
    "exawaro",
    ["white", "yellow", "gold", "orange", "darkorange", "r", "red", "darkred", "black"],
)


def read_wbgt_binary(bin_path, meta_path):
    with open(meta_path) as f:
        meta = dict(line.strip().split("=", 1) for line in f if "=" in line and not line.startswith("scenario"))
    nx = int(meta["nx"]); ny = int(meta["ny"])
    x0 = float(meta["x0"]); y0 = float(meta["y0"])
    dx = float(meta["dx"]); dy = abs(float(meta["dy"]))
    with open(bin_path, "rb") as f:
        hdr = f.read(44)
        nx_h, ny_h, ns = struct.unpack("iii", hdr[:12])
    data = np.fromfile(bin_path, dtype=np.float32, offset=44)
    data = data.reshape((ns, ny_h, nx_h))
    return data[0], nx, ny, x0, y0, dx, dy


def load_network_lines(zip_path, xml_name, transformer):
    """Single-pass stream: store nodes, emit links as LineStrings."""
    with zipfile.ZipFile(zip_path, "r") as zf:
        with zf.open(xml_name) as f:
            nodes = {}
            lines = []
            count = 0
            for event, elem in ET.iterparse(f, events=("end",)):
                if elem.tag == "node":
                    nodes[elem.get("id")] = (float(elem.get("x")), float(elem.get("y")))
                elif elem.tag == "link":
                    fid, tid = elem.get("from"), elem.get("to")
                    if fid in nodes and tid in nodes:
                        x1, y1 = nodes[fid]
                        x2, y2 = nodes[tid]
                        xt1, yt1 = transformer.transform(x1, y1)
                        xt2, yt2 = transformer.transform(x2, y2)
                        lines.append(LineString([(xt1, yt1), (xt2, yt2)]))
                        count += 1
                elem.clear()
            print(f"  Nodes: {len(nodes)}, Links: {count}")
            return lines


def parse_args():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input-dir", default=str(input_dir()),
                    help="Directory with the WBGT *.bin grids and the network zip")
    ap.add_argument("--zip", dest="zip_path",
                    default=str(input_dir() / "network_with_flood_data.zip"),
                    help="Network archive (.zip) containing the network XML")
    ap.add_argument("--xml-name", default="network_with_flood_data.xml",
                    help="XML file name inside the zip")
    ap.add_argument("--out-dir", default=str(figures_dir()),
                    help="Directory to write the PNG maps")
    return ap.parse_args()


def main():
    args = parse_args()
    base = args.input_dir
    zip_path = args.zip_path
    xml_name = args.xml_name
    meta_file = os.path.join(base, "wbgt_grid.meta")
    out_dir = args.out_dir
    os.makedirs(out_dir, exist_ok=True)

    transformer = Transformer.from_crs("EPSG:27700", "EPSG:32630", always_xy=True)

    scenarios_def = [
        ("peak", "WBGT (\u00b0C) \u2013 Peak (17:00, 30 Sep)"),
        ("commute", "WBGT (\u00b0C) \u2013 Commute (Mon 08:00)"),
        ("weekend", "WBGT (\u00b0C) \u2013 Weekend (Sat 12:00)"),
    ]

    # Global vmin/vmax
    vmin, vmax = float("inf"), float("-inf")
    for scenario, _ in scenarios_def:
        g, _, _, _, _, _, _ = read_wbgt_binary(os.path.join(base, f"wbgt_scenario_{scenario}.bin"), meta_file)
        gm = np.ma.masked_where(g <= 0, g)
        vmin = min(vmin, float(gm.min()))
        vmax = max(vmax, float(gm.max()))

    print("Loading network from zip (single pass)...")
    lines = load_network_lines(zip_path, xml_name, transformer)
    print(f"Loaded {len(lines)} link lines")
    gdf_net = gpd.GeoDataFrame(geometry=lines, crs="EPSG:32630")
    nx_min, ny_min, nx_max, ny_max = gdf_net.total_bounds
    pad = 2000

    for idx, (scenario, label) in enumerate(scenarios_def):
        bin_path = os.path.join(base, f"wbgt_scenario_{scenario}.bin")
        grid, nx, ny, x0, y0, dx, dy = read_wbgt_binary(bin_path, meta_file)
        grid = np.ma.masked_where(grid <= 0, grid)
        extent = [x0, x0 + nx * dx, y0 - ny * dy, y0]

        fig, ax = plt.subplots(1, 1, figsize=(8, 7))
        im = ax.imshow(grid, extent=extent, origin="upper", cmap=EXAWARO_CMAP,
                       vmin=vmin, vmax=vmax, aspect="auto")

        gdf_net.plot(ax=ax, color="gray", linewidth=0.12, alpha=0.35)

        ctx.add_basemap(ax, crs="EPSG:32630", source=ctx.providers.CartoDB.Positron, alpha=0.3)
        ax.set_xlim(nx_min - pad, nx_max + pad)
        ax.set_ylim(ny_min - pad, ny_max + pad)
        # ax.set_title(label, fontsize=11)
        if idx == 1:
            ax.set_xlabel("Easting (m)")
        else:
            ax.set_xlabel("")
        if idx == 0:
            ax.set_ylabel("Northing (m)")
        else:
            ax.set_ylabel("")
            ax.tick_params(labelleft=False)
        if idx == 2:
            plt.colorbar(im, ax=ax, label="WBGT (\u00b0C)", shrink=0.8)
        plt.tight_layout()
        out_path = os.path.join(out_dir, f"heatmap_with_network_{scenario}.png")
        plt.savefig(out_path, dpi=150, bbox_inches="tight")
        print(f"  Wrote {out_path}")
        plt.close()


if __name__ == "__main__":
    main()
