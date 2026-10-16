#!/usr/bin/env python3
"""Pre-process WBGT_2025.nc into compact binary formats for Java.

Output files (all .bin have same header: nx, ny, n_slices, x0, y0, dx, dy):
  wbgt_hourly_avg.bin       — 24 slices, per-hour-of-day averages (~6.7 MB)
  wbgt_scenario_peak.bin    — 1 slice, hottest hour
  wbgt_scenario_commute.bin — 1 slice, typical weekday 08:00
  wbgt_scenario_weekend.bin — 1 slice, weekend 12:00
  wbgt_grid.meta            — metadata
"""

import argparse
import numpy as np
import netCDF4 as nc
import os, struct
from config import wbgt_nc_file, input_dir

_ap = argparse.ArgumentParser(description=__doc__)
_ap.add_argument("--input-file", default=str(wbgt_nc_file()),
                 help="Source WBGT NetCDF file")
_ap.add_argument("--output-dir", default=str(input_dir()),
                 help="Directory to write the .bin grids and metadata")
_args = _ap.parse_args()

INPUT_FILE = _args.input_file
OUTPUT_DIR = _args.output_dir

def write_slice(path, nx, ny, n_slices, x0, y0, dx, dy, data):
    """Write a binary file with header + float32 data."""
    with open(path, "wb") as f:
        f.write(struct.pack("iii", nx, ny, n_slices))
        f.write(struct.pack("dddd", x0, y0, dx, dy))
        f.write(data.astype(np.float32).tobytes())
    print(f"  -> {path} ({os.path.getsize(path)/1e6:.1f} MB)")

def main():
    print("Reading WBGT_2025.nc ...")
    ds = nc.Dataset(INPUT_FILE, "r")
    xs = ds.variables["x"][:]
    ys = ds.variables["y"][:]
    wbgt_var = ds.variables["WBGT"]
    times = ds.variables["time"][:]

    nx, ny, nt = len(xs), len(ys), len(times)
    x0, y0 = float(xs[0]), float(ys[0])
    dx, dy = float(xs[1] - xs[0]), float(ys[1] - ys[0])
    print(f"Grid: {nx}x{ny}, {nt} timesteps")
    print(f"x0={x0:.1f}, y0={y0:.1f}, dx={dx:.1f}, dy={dy:.1f}")

    # Read full array
    print("Reading WBGT ...")
    data = wbgt_var[:,:,:].astype(np.float32)
    ds.close()
    print(f"  shape={data.shape}, range={data.min():.2f}–{data.max():.2f} °C")

    # ── 1. Per-hour-of-day averages ──
    # time index 0 = 01:00 on June 1 (Sunday). hour_of_day = (t_idx + 1) % 24
    print("Computing hourly averages ...")
    hourly_avg = np.zeros((24, ny, nx), dtype=np.float32)
    counts = np.zeros(24, dtype=np.int32)
    for t in range(nt):
        hod = (t + 1) % 24
        hourly_avg[hod] += data[t]
        counts[hod] += 1
    for h in range(24):
        if counts[h] > 0:
            hourly_avg[h] /= counts[h]
    write_slice(os.path.join(OUTPUT_DIR, "wbgt_hourly_avg.bin"),
                nx, ny, 24, x0, y0, dx, dy, hourly_avg)

    # ── 2. Peak heat: find the single hottest hour ──
    print("Finding peak heat hour ...")
    peak_idx = int(np.unravel_index(np.argmax(data), data.shape)[0])
    peak_val = float(data[peak_idx].max())
    peak_date_offset = peak_idx // 24
    peak_hod = (peak_idx + 1) % 24
    print(f"  Peak: t={peak_idx}, date_offset={peak_date_offset}d, hour={peak_hod}, value={peak_val:.2f} °C")
    write_slice(os.path.join(OUTPUT_DIR, "wbgt_scenario_peak.bin"),
                nx, ny, 1, x0, y0, dx, dy, data[peak_idx:peak_idx+1])

    # ── 3. Commute: Monday 08:00 ──
    # June 1 (Sun) = date_offset 0. June 2 (Mon) = date_offset 1.
    # 08:00 on Monday = t_idx = 24*1 + 7 = 31 (since time[0]=01:00)
    commute_idx = 31
    commute_date_offset = commute_idx // 24
    commute_hod = (commute_idx + 1) % 24
    print(f"  Commute: t={commute_idx}, date_offset={commute_date_offset}d, hour={commute_hod}")
    write_slice(os.path.join(OUTPUT_DIR, "wbgt_scenario_commute.bin"),
                nx, ny, 1, x0, y0, dx, dy, data[commute_idx:commute_idx+1])

    # ── 4. Weekend: Saturday 12:00 ──
    # June 7 (Sat) = date_offset 6. 12:00 on Saturday = t_idx = 24*6 + 11 = 155
    weekend_idx = 155
    weekend_date_offset = weekend_idx // 24
    weekend_hod = (weekend_idx + 1) % 24
    print(f"  Weekend: t={weekend_idx}, date_offset={weekend_date_offset}d, hour={weekend_hod}")
    write_slice(os.path.join(OUTPUT_DIR, "wbgt_scenario_weekend.bin"),
                nx, ny, 1, x0, y0, dx, dy, data[weekend_idx:weekend_idx+1])

    # ── Metadata ──
    with open(os.path.join(OUTPUT_DIR, "wbgt_grid.meta"), "w") as f:
        f.write(f"nx={nx}\nny={ny}\n")
        f.write(f"x0={x0}\ny0={y0}\ndx={dx}\ndy={dy}\n")
        f.write(f"wbgt_min={float(data.min()):.2f}\nwbgt_max={float(data.max()):.2f}\n")
        f.write(f"source={INPUT_FILE}\ncrs=EPSG:32630\n")
        f.write(f"scenarios:\n")
        f.write(f"  peak: t={peak_idx}, val={peak_val:.2f}\n")
        f.write(f"  commute: t={commute_idx} (Mon 08:00)\n")
        f.write(f"  weekend: t={weekend_idx} (Sat 12:00)\n")
    print(f"  -> meta written")

    print("Done.")

if __name__ == "__main__":
    main()
