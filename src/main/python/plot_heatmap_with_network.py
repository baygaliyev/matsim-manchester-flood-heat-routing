#!/usr/bin/env python3
"""Generate WBGT heatmap maps with the MATSim road network overlay.

Outputs (written to --out-dir, one file per --formats entry, default png+pdf):
    heatmap_wbgt_3panel.png|.pdf        one 1x3 overview figure
    heatmap_with_network_<scenario>.*    one map per scenario (identical canvas)

Layout / visual fixes over the previous version:
  * every panel is placed on a fixed, computed rectangle (see _map_size /
    build_fixed_layout) with a reserved colourbar slot, so all panels keep the
    same size and aspect ratio regardless of what is drawn;
  * colourbars live in their own axes (fig.colorbar(..., cax=cax)) and can never
    resize panel (c);
  * the WBGT raster is masked to the Greater Manchester boundary geometry with
    rasterio instead of being drawn as a raw rectangle (fallback: matplotlib);
  * the map extent is locked to the boundary bounds + --pad-frac padding and the
    basemap is fetched only for that extent, so no stray tiles / white margins;
  * normalisation is configurable: --norm per-panel (default) uses a robust
    percentile range per time slice so cooler hours keep their local spatial
    structure, --norm pooled uses one shared scale with a single colourbar;
  * the basemap defaults to Esri World Gray Canvas (no API key, no watermark);
    CartoDB now serves "API KEY REQUIRED" placeholder tiles to keyless clients,
    so verify any other --provider before publishing;
  * consistent typography: "Easting (m)" under every panel, northing label on
    the first panel only, equal aspect, uniform title/tick fonts.

Boundary sources (first match wins):
  1. --boundary <file.shp|.geojson|.gpkg>
  2. <input-dir>/boundary_greater_manchester.geojson (cache)
  3. Nominatim download of the Greater Manchester boundary (cached, --no-download
     to disable)
  4. concave hull of the MATSim network (--hull-ratio), offline fallback
"""

import argparse
import json
import os
import struct
import sys
import urllib.parse
import urllib.request
import zipfile
import xml.etree.ElementTree as ET

import contextily as ctx
import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import shapely
from matplotlib.collections import LineCollection
from matplotlib.colors import LinearSegmentedColormap, Normalize
from pyproj import Transformer
from shapely.geometry import LineString

from config import figures_dir, input_dir

EXAWARO_CMAP = LinearSegmentedColormap.from_list(
    "exawaro",
    ["white", "yellow", "gold", "orange", "darkorange", "r", "red", "darkred", "black"],
)
DEFAULT_CMAP = "magma"
DEFAULT_PROVIDER = "Esri.WorldGrayCanvas"

BOUNDARY_CACHE_NAME = "boundary_greater_manchester.geojson"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "matsim-wbgt-figure/1.0 (Manchester heat/flood routing research)"

# Fixed canvas geometry (inches) - recomputed for every figure, never responsive
# to what is actually drawn, so panels cannot change size between files.
MARGIN_LEFT = 0.70     # northing tick labels
MARGIN_RIGHT = 0.12    # canvas edge
MARGIN_BOTTOM = 0.55   # easting tick labels
MARGIN_TOP = 0.16      # above the panels
TITLE_SPACE = 0.34     # extra above the panels when titles are drawn
CAX_WIDTH = 0.38       # colourbar body
CAX_GAP = 0.14         # map -> colourbar gap
CAX_LABELS = 0.55      # colourbar tick labels + unit
PANEL_GAP = 0.35       # between panels of the 3-panel figure
FIG_W_COMBINED = 16.0  # width of the 3-panel overview

SCENARIOS = [
    ("peak", "Peak (17:00, 30 Sep)"),
    ("commute", "Commute (Mon 08:00)"),
    ("weekend", "Weekend (Sat 12:00)"),
]


# --------------------------------------------------------------------------- data

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


# ----------------------------------------------------------------------- boundary

def download_boundary(cache_path):
    """Fetch the Greater Manchester administrative boundary from Nominatim."""
    query = urllib.parse.urlencode({
        "q": "Greater Manchester, United Kingdom",
        "format": "jsonv2",
        "polygon_geojson": 1,
        "limit": 1,
        "featuretype": "administrative",
    })
    req = urllib.request.Request(f"{NOMINATIM_URL}?{query}", headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        results = json.load(resp)
    if not results or results[0].get("geojson") is None:
        raise RuntimeError("Nominatim returned no polygon")
    feature = {
        "type": "Feature",
        "properties": {
            "name": results[0].get("display_name", "Greater Manchester"),
            "source": f"OpenStreetMap / Nominatim {results[0].get('osm_type')} {results[0].get('osm_id')}",
        },
        "geometry": results[0]["geojson"],
    }
    with open(cache_path, "w", encoding="utf-8") as fh:
        json.dump(feature, fh)
    return cache_path


def _union(gdf):
    return gdf.union_all() if hasattr(gdf, "union_all") else gdf.unary_union


def resolve_boundary(gdf_net, args, base):
    """Return (geometry in the network CRS, human-readable source description)."""
    path = args.boundary
    if path is None:
        cache = os.path.join(base, BOUNDARY_CACHE_NAME)
        if os.path.exists(cache):
            path = cache
        elif not args.no_download:
            try:
                path = download_boundary(cache)
                print(f"  Downloaded boundary -> {cache}")
            except Exception as exc:  # noqa: BLE001 - offline / rate-limited is fine
                print(f"  WARNING: boundary download failed ({exc}); using network hull instead")
    if path:
        gdf = gpd.read_file(path)
        if gdf.crs is None:
            raise SystemExit(f"boundary file {path} has no CRS; cannot align it with the network")
        gdf = gdf.to_crs(gdf_net.crs)
        return _union(gdf), path

    geom = shapely.union_all(np.asarray(gdf_net.geometry.values, dtype=object))
    hull = shapely.concave_hull(geom, ratio=args.hull_ratio)
    if hull.geom_type != "Polygon":
        hull = geom.convex_hull
    print(f"  WARNING: no boundary file; using concave hull of the network (ratio={args.hull_ratio})")
    return hull, f"network concave hull (ratio={args.hull_ratio})"


def boundary_mask(boundary, nx, ny, x0, y0, dx, dy):
    """Boolean array (ny, nx): True where the cell centre falls inside `boundary`."""
    try:
        from affine import Affine
        from rasterio.features import geometry_mask
    except ImportError:
        return _boundary_mask_matplotlib(boundary, nx, ny, x0, y0, dx, dy)
    transform = Affine(dx, 0.0, x0, 0.0, -dy, y0)  # origin upper-left, dy positive
    return geometry_mask([boundary], out_shape=(ny, nx), transform=transform,
                         invert=True, all_touched=False)


def _boundary_mask_matplotlib(boundary, nx, ny, x0, y0, dx, dy):
    from matplotlib.path import Path

    xs = x0 + (np.arange(nx) + 0.5) * dx
    ys = y0 - (np.arange(ny) + 0.5) * dy
    xx, yy = np.meshgrid(xs, ys)
    pts = np.column_stack([xx.ravel(), yy.ravel()])

    parts = list(getattr(boundary, "geoms", [boundary]))
    inside = np.zeros(ny * nx, dtype=bool)
    for part in parts:
        if part.is_empty:
            continue
        ext = Path(np.asarray(part.exterior.coords)).contains_points(pts)
        holes = np.zeros_like(ext)
        for ring in part.interiors:
            holes |= Path(np.asarray(ring.coords)).contains_points(pts)
        inside |= (ext & ~holes)
    return inside.reshape(ny, nx)


# ------------------------------------------------------------------ norms / layout

def parse_percentiles(text):
    try:
        lo, hi = (float(v) for v in text.split(","))
    except ValueError:
        raise SystemExit(f"--percentiles expects e.g. '2,98', got {text!r}")
    return lo, hi


def build_norms(grids, mode, percentiles):
    """Return (one norm per panel, (lo, hi) of the scale shown by the colourbar)."""
    if mode == "pooled":
        values = np.concatenate([g.compressed() for g in grids])
        lo, hi = (float(v) for v in np.percentile(values, percentiles))
        norm = Normalize(vmin=lo, vmax=hi)
        return [norm] * len(grids), (lo, hi)

    norms = []
    spans = []
    for grid in grids:
        values = grid.compressed()
        lo, hi = (float(v) for v in np.percentile(values, percentiles))
        if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
            lo, hi = float(values.min()), float(values.max())
        norms.append(Normalize(vmin=lo, vmax=hi))
        spans.append((lo, hi))
    return norms, (min(s[0] for s in spans), max(s[1] for s in spans))


def _map_size(fig_w, fig_h, limits, n_panels, per_panel_cax, with_titles):
    """Map box size (inches) shared by every panel of one figure."""
    ratio = (limits[2] - limits[0]) / (limits[3] - limits[1])
    n_cax = n_panels if per_panel_cax else 1
    block = CAX_GAP + CAX_WIDTH + CAX_LABELS
    avail_w = fig_w - MARGIN_LEFT - MARGIN_RIGHT
    avail_h = fig_h - MARGIN_BOTTOM - MARGIN_TOP - (TITLE_SPACE if with_titles else 0.0)
    map_w = (avail_w - n_cax * block - (n_panels - 1) * PANEL_GAP) / n_panels
    map_w = min(map_w, avail_h * ratio)
    return map_w, map_w / ratio


def individual_figsize(limits, per_panel_cax, with_titles):
    """Canvas for one scenario map: exactly one map + its colourbar slot."""
    fig_w = FIG_W_COMBINED / 3.0
    _, map_h = _map_size(fig_w, 1e3, limits, 1, per_panel_cax, with_titles)
    fig_h = MARGIN_BOTTOM + MARGIN_TOP + map_h + (TITLE_SPACE if with_titles else 0.0)
    return fig_w, fig_h


def build_fixed_layout(fig, limits, n_panels, per_panel_cax, with_titles):
    """Place panels on fixed, computed rectangles.

    Nothing here depends on what gets drawn (colourbar present or not, how wide
    its tick labels are), so every panel keeps exactly the same box - the bug
    that used to squash panel (c).
    """
    fig_w, fig_h = fig.get_size_inches()
    map_w, map_h = _map_size(fig_w, fig_h, limits, n_panels, per_panel_cax, with_titles)
    block = CAX_GAP + CAX_WIDTH + CAX_LABELS
    n_cax = n_panels if per_panel_cax else 1
    used = n_panels * map_w + n_cax * block + (n_panels - 1) * PANEL_GAP
    x = MARGIN_LEFT + (fig_w - MARGIN_LEFT - MARGIN_RIGHT - used) / 2.0
    y = MARGIN_BOTTOM + (fig_h - MARGIN_BOTTOM - MARGIN_TOP
                         - (TITLE_SPACE if with_titles else 0.0) - map_h) / 2.0

    panels, caxes = [], []
    for i in range(n_panels):
        ax = fig.add_axes([x / fig_w, y / fig_h, map_w / fig_w, map_h / fig_h])
        panels.append(ax)
        x += map_w
        if per_panel_cax:
            caxes.append(fig.add_axes([(x + CAX_GAP) / fig_w, y / fig_h,
                                       CAX_WIDTH / fig_w, map_h / fig_h]))
            x += block
        if i < n_panels - 1:
            x += PANEL_GAP
    if not per_panel_cax:
        caxes.append(fig.add_axes([(x + CAX_GAP) / fig_w, y / fig_h,
                                   CAX_WIDTH / fig_w, map_h / fig_h]))

    for ax in panels[1:]:
        ax.sharex(panels[0])
        ax.sharey(panels[0])
    return panels, caxes


def resolve_cmap(name):
    """Colormap by matplotlib name, or the legacy 'exawaro' custom map."""
    if name == "exawaro":
        return EXAWARO_CMAP
    try:
        return plt.get_cmap(name)
    except ValueError:
        raise SystemExit(f"unknown colormap {name!r} (try 'magma', 'inferno', 'viridis', 'exawaro')")


def resolve_provider(name):
    """Dotted contextily provider name -> provider dict (None = no basemap)."""
    if not name or name.lower() in {"none", "off", "no"}:
        return None
    src = ctx.providers
    for part in name.split("."):
        try:
            src = getattr(src, part)
        except AttributeError:
            raise SystemExit(f"unknown basemap provider {name!r} "
                             f"(try 'Esri.WorldGrayCanvas', 'OpenStreetMap.Mapnik', 'none')")
    if not isinstance(src, dict) or "url" not in src:
        raise SystemExit(f"{name!r} is not a tile provider (it has no 'url')")
    return src


def draw_map(ax, grid, norm, extent, net_segments, crs, show_basemap, basemap_source,
             raster_alpha, cmap):
    if show_basemap:
        try:
            ctx.add_basemap(ax, crs=crs, source=basemap_source, zorder=1)
        except Exception as exc:  # noqa: BLE001 - tiles may be unreachable
            print(f"  WARNING: basemap unavailable ({exc})")
    image = ax.imshow(grid, extent=extent, origin="upper", cmap=cmap, norm=norm,
                      aspect="equal", alpha=raster_alpha, zorder=2)
    # dark lines stay readable over the whole magma ramp (cool regions are
    # lightened by the 30% basemap showing through the raster)
    net = LineCollection(net_segments, colors="0.1", linewidths=0.16, alpha=0.6, zorder=3)
    net.set_rasterized(True)  # keeps the PDF export small and fast
    ax.add_collection(net, autolim=False)
    return image


def lock_extent(panels, limits):
    """Fix the map window before anything is drawn (basemap tiles are fetched
    for exactly this extent)."""
    xmin, ymin, xmax, ymax = limits
    for ax in panels:
        ax.set_xlim(xmin, xmax)
        ax.set_ylim(ymin, ymax)
        ax.set_aspect("equal")


def style_axes(panels, titles, show_titles):
    for index, ax in enumerate(panels):
        # northing labels only on the first panel, easting label on every panel
        ax.tick_params(labelsize=8, labelleft=(index == 0), labelbottom=True)
        ax.set_xlabel("Easting (m)", fontsize=9)
    panels[0].set_ylabel("Northing (m)", fontsize=9)
    if show_titles:
        for ax, title in zip(panels, titles):
            ax.set_title(title, fontsize=11, pad=10)


def add_colorbar(fig, cax, image, show):
    """Draw the colourbar, or leave the reserved slot blank.

    The slot stays in the layout even when no colourbar is drawn, so every
    per-scenario canvas keeps exactly the same panel size.
    """
    if not show:
        cax.set_axis_off()
        return
    fig.colorbar(image, cax=cax)
    cax.set_ylabel("WBGT (\u00b0C)", fontsize=9)
    cax.tick_params(labelsize=8)


def save_figure(fig, out_base, formats, dpi, tight=False):
    """Write every requested format.

    tight=True crops whitespace (used for the standalone 3-panel figure only);
    the per-scenario maps must keep their exact canvas so all three files have
    identical map rectangles.
    """
    written = []
    for fmt in formats:
        path = f"{out_base}.{fmt}"
        fig.savefig(path, dpi=dpi, bbox_inches="tight" if tight else None)
        written.append(path)
    return written


# ------------------------------------------------------------------------- input

def parse_args():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input-dir", default=str(input_dir()),
                    help="Directory with the WBGT *.bin grids, wbgt_grid.meta and the network zip")
    ap.add_argument("--zip", dest="zip_path", default=None,
                    help="Network archive (.zip) containing the network XML "
                         "(default: <input-dir>/network_with_flood_data.zip)")
    ap.add_argument("--xml-name", default="network_with_flood_data.xml",
                    help="XML file name inside the zip")
    ap.add_argument("--out-dir", default=str(figures_dir()),
                    help="Directory to write the figures (png/pdf per --formats)")
    ap.add_argument("--boundary", default=None,
                    help="Vector file with the Greater Manchester boundary "
                         "(default: cached geojson, else Nominatim download, else network hull)")
    ap.add_argument("--no-download", action="store_true",
                    help="Never fetch the boundary; fall back to the network hull if no cache exists")
    ap.add_argument("--hull-ratio", type=float, default=0.05,
                    help="Concave-hull ratio used when no boundary file is available (default 0.05)")
    ap.add_argument("--norm", choices=("per-panel", "pooled"), default="per-panel",
                    help="per-panel: robust range per slice (default, keeps local structure); "
                         "pooled: one shared scale and a single colourbar")
    ap.add_argument("--percentiles", default="2,98",
                    help="Robust normalisation range as LO,HI percentiles (default 2,98)")
    ap.add_argument("--pad-frac", type=float, default=0.03,
                    help="Map padding as a fraction of the boundary width (default 0.03)")
    ap.add_argument("--raster-alpha", type=float, default=0.7,
                    help="Transparency of the WBGT overlay above the basemap (default 0.7)")
    ap.add_argument("--cmap", default=DEFAULT_CMAP,
                    help="Colormap for the WBGT field (default 'magma': dark = cooler, "
                         "bright yellow = hotter; 'exawaro' = legacy white->red->black)")
    ap.add_argument("--provider", default=DEFAULT_PROVIDER,
                    help="contextily tile provider (dotted name) or 'none'. Default "
                         f"{DEFAULT_PROVIDER} is key-free and watermark-free; CartoDB "
                         "providers now serve placeholder tiles without an API key")
    ap.add_argument("--formats", default="png,pdf",
                    help="Comma-separated output formats (default png,pdf)")
    ap.add_argument("--titles", choices=("auto", "on", "off"), default="auto",
                    help="auto: titles on the 3-panel overview, off for the per-scenario "
                         "maps (the paper supplies its own subcaptions)")
    ap.add_argument("--individual-colorbar", choices=("auto", "all", "never"), default="auto",
                    help="Colourbars on the per-scenario maps: auto = all in per-panel "
                         "norm mode, only the last one in pooled mode")
    ap.add_argument("--dpi", type=int, default=300)
    ap.add_argument("--no-basemap", action="store_true")
    ap.add_argument("--no-combined", action="store_true", help="Skip heatmap_wbgt_3panel.*")
    ap.add_argument("--no-individual", action="store_true",
                    help="Skip the per-scenario heatmap_with_network_*.* files")
    return ap.parse_args()


def main():
    args = parse_args()
    base = args.input_dir
    if args.zip_path is None:
        args.zip_path = os.path.join(base, "network_with_flood_data.zip")
    out_dir = args.out_dir
    os.makedirs(out_dir, exist_ok=True)
    percentiles = parse_percentiles(args.percentiles)
    formats = [f.strip().lower() for f in args.formats.split(",") if f.strip()]
    if not formats:
        raise SystemExit("--formats must list at least one of: png, pdf, svg")
    cmap = resolve_cmap(args.cmap)

    meta_file = os.path.join(base, "wbgt_grid.meta")
    transformer = Transformer.from_crs("EPSG:27700", "EPSG:32630", always_xy=True)

    # --- grids -----------------------------------------------------------------
    raws, shape = [], None
    for scenario, _ in SCENARIOS:
        g, nx, ny, x0, y0, dx, dy = read_wbgt_binary(
            os.path.join(base, f"wbgt_scenario_{scenario}.bin"), meta_file)
        shape = (nx, ny, x0, y0, dx, dy)
        raws.append(g)
    nx, ny, x0, y0, dx, dy = shape
    extent = [x0, x0 + nx * dx, y0 - ny * dy, y0]

    # --- network + boundary ----------------------------------------------------
    print("Loading network from zip (single pass)...")
    lines = load_network_lines(args.zip_path, args.xml_name, transformer)
    print(f"Loaded {len(lines)} link lines")
    gdf_net = gpd.GeoDataFrame(geometry=lines, crs="EPSG:32630")
    # (N, 2, 2) segment array: LineCollection draws this ~40x faster than
    # geopandas' own plot() over 1M geometries
    net_segments = np.stack([np.asarray(geom.coords) for geom in gdf_net.geometry], axis=0)
    crs_str = str(gdf_net.crs)

    boundary, boundary_src = resolve_boundary(gdf_net, args, base)
    print(f"  Boundary source: {boundary_src}")

    inside = boundary_mask(boundary, nx, ny, x0, y0, dx, dy)
    grids = []
    for (scenario, _), raw in zip(SCENARIOS, raws):
        valid = (raw > 0) & inside
        if not valid.any():
            raise SystemExit(f"boundary does not intersect the WBGT grid for {scenario!r}")
        grids.append(np.ma.masked_where(~valid, raw))

    bx0, by0, bx1, by1 = boundary.bounds
    pad = args.pad_frac * max(bx1 - bx0, by1 - by0)
    limits = (bx0 - pad, by0 - pad, bx1 + pad, by1 + pad)

    norms, span = build_norms(grids, args.norm, percentiles)
    print(f"  Normalisation: {args.norm} "
          f"({'shared ' if args.norm == 'pooled' else 'per-panel '}range "
          f"{span[0]:.2f}..{span[1]:.2f} \u00b0C)")

    # --- basemap availability --------------------------------------------------
    basemap_source = resolve_provider(args.provider)
    show_basemap = (not args.no_basemap) and basemap_source is not None
    if show_basemap:
        print(f"  Basemap: {args.provider} "
              f"(credit: {basemap_source.get('attribution', 'custom')})")
        # probe once so we do not repeat failed tile fetches for every panel
        probe = plt.figure(figsize=(2, 2))
        probe_ax = probe.add_subplot()
        probe_ax.set_xlim(limits[0], limits[2])
        probe_ax.set_ylim(limits[1], limits[3])
        probe_ax.set_aspect("equal")
        try:
            ctx.add_basemap(probe_ax, crs=str(gdf_net.crs), source=basemap_source)
        except Exception as exc:  # noqa: BLE001
            print(f"  WARNING: basemap disabled ({exc})")
            show_basemap = False
        plt.close(probe)

    labels = [label for _, label in SCENARIOS]
    per_panel_cax = args.norm == "per-panel"
    draw_cbar = {
        "all": [True] * 3,
        "never": [False] * 3,
        "auto": [True] * 3 if per_panel_cax else [False, False, True],
    }[args.individual_colorbar]

    def titles_on(kind):
        if args.titles == "on":
            return True
        if args.titles == "off":
            return False
        return kind == "combined"

    # --- 3-panel overview ------------------------------------------------------
    if not args.no_combined:
        show_titles = titles_on("combined")
        fig = plt.figure(figsize=(FIG_W_COMBINED, 5.0))
        panels, caxes = build_fixed_layout(fig, limits, 3, per_panel_cax, show_titles)
        lock_extent(panels, limits)
        images = [draw_map(ax, grid, norm, extent, net_segments, crs_str, show_basemap,
                           basemap_source, args.raster_alpha, cmap)
                  for ax, grid, norm in zip(panels, grids, norms)]
        style_axes(panels, labels, show_titles)
        if per_panel_cax:
            for cax, image in zip(caxes, images):
                add_colorbar(fig, cax, image, show=True)
        else:
            add_colorbar(fig, caxes[0], images[-1], show=True)
        for path in save_figure(fig, os.path.join(out_dir, "heatmap_wbgt_3panel"),
                                formats, args.dpi, tight=True):
            print(f"  Wrote {path}")
        plt.close(fig)

    # --- one identical canvas per scenario -------------------------------------
    if not args.no_individual:
        show_titles = titles_on("individual")
        fig_w, fig_h = individual_figsize(limits, per_panel_cax, show_titles)
        for idx, ((scenario, label), grid, norm) in enumerate(zip(SCENARIOS, grids, norms)):
            fig = plt.figure(figsize=(fig_w, fig_h))
            panels, caxes = build_fixed_layout(fig, limits, 1, per_panel_cax, show_titles)
            lock_extent(panels, limits)
            image = draw_map(panels[0], grid, norm, extent, net_segments, crs_str,
                             show_basemap, basemap_source, args.raster_alpha, cmap)
            style_axes(panels, [label], show_titles)
            add_colorbar(fig, caxes[0], image, show=draw_cbar[idx])
            for path in save_figure(fig, os.path.join(out_dir, f"heatmap_with_network_{scenario}"),
                                    formats, args.dpi, tight=False):
                print(f"  Wrote {path}")
            plt.close(fig)


if __name__ == "__main__":
    main()
