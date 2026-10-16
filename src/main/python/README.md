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
| `plot_heatmap_with_network.py` | Render WBGT scenario heatmaps with the MATSim road network overlaid on a basemap. |
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
