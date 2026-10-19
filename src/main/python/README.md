# Python analysis scripts

Post-processing for the Manchester flood/heat routing runs produced by the Java
classes in `src/main/java/org/matsim/manchester/`.

## Setup

```sh
pip install -r requirements.txt      # from the repository root
```

## Paths

All scripts resolve their input/output directories through `config.py`, which
uses environment variables with sensible repository-relative defaults:

| Variable | Default | Meaning |
| --- | --- | --- |
| `MATSIM_INPUT_DIR` | `<repo>/input` | WBGT `*.bin` grids, `wbgt_grid.meta`, `network_with_flood_data.zip`. |
| `MATSIM_OUTPUT_DIR` | `<repo>/output` | MATSim run folders `results_heat_*`. |
| `MATSIM_FIGURES_DIR` | `<repo>/output/figures` | Where generated maps are written. |
| `WBGT_NC_FILE` | `<MATSIM_INPUT_DIR>/WBGT_2025.nc` | NetCDF source for `preprocess_wbgt.py`. |

Every script also accepts the corresponding `--input-dir` / `--output-dir` /
`--out-dir` flags, which take precedence over the environment variables.

## Scripts

| Script | Purpose |
| --- | --- |
| `config.py` | Shared path resolution (imported by the other scripts). |
| `preprocess_wbgt.py` | Convert a WBGT NetCDF grid into the compact `.bin` slices the Java heat router reads. |
| `heat_analysis_local.py` | Merge fastest vs. heat-optimal routes and emit LaTeX tables for travel time, cumulative WBGT, and Jaccard overlap. |
| `heat_analysis_final.py` | Concise console summary (travel time, WBGT, Jaccard) with the weekend-bike correction applied. |
| `diagnose_weekend_bike_bug.py` | Inspect trips with identical path but differing heat exposure (weekend bike case). |
| `diagnose_bug_deep.py` | Deeper diagnosis: link-level comparison, factor analysis, ratio by travel-time bin. |
| `plot_heatmap_with_network.py` | Render WBGT scenario heatmaps clipped to the Greater Manchester boundary, with the MATSim road network over a basemap. Emits a 1x3 overview (`heatmap_wbgt_3panel`) plus one identically-sized map per scenario (`heatmap_with_network_*`), each with a dedicated colourbar slot so panels never change size. Writes png and pdf by default. |
| `plot_manchester_maps.py` | WBGT maps for the paper (and a stub for the flood-depth map). |

## Notebooks

`heat_analysis_manchester.ipynb` and `flood_exawaro_manchester.ipynb` are the
original Google Colab notebooks (they mount `/content/drive` and read from a
`phd_data/` folder). They are kept for reference; the standalone scripts above
supersede them for local/CI use.

## Example

```sh
export MATSIM_OUTPUT_DIR=/path/to/run_output
python heat_analysis_local.py
python plot_heatmap_with_network.py --input-dir /path/to/input --out-dir /path/to/figures
```

`plot_heatmap_with_network.py` options worth knowing:

| Flag | Effect |
| --- | --- |
| `--norm per-panel` (default) | Robust 2–98 percentile range per time slice, one colourbar per panel — keeps local structure in the cooler commute/weekend slices. |
| `--norm pooled` | One shared scale across the three slices with a single colourbar (`--percentiles 2,98` tunes the range). |
| `--cmap magma` (default) | Colormap of the WBGT field (dark = cooler, bright yellow = hotter); `exawaro` keeps the legacy white→red→black ramp. |
| `--provider Esri.WorldGrayCanvas` (default) | contextily tile provider, or `none`. CartoDB providers now serve "API KEY REQUIRED" placeholder tiles to keyless clients, so don't use them for publication figures. |
| `--formats png,pdf` (default) | Output formats; the 1x3 overview is saved with `bbox_inches=tight`, the per-scenario maps without it so all three canvases stay pixel-identical. |
| `--boundary FILE` | Greater Manchester boundary (shp/geojson/gpkg). Default: cached `boundary_greater_manchester.geojson` in `--input-dir`, else a one-off Nominatim download, else a concave hull of the network. |
| `--no-basemap`, `--titles`, `--pad-frac`, `--raster-alpha`, `--dpi` | Basemap off; title policy (`auto`/`on`/`off`); map padding; overlay transparency; export resolution (default 300). |
