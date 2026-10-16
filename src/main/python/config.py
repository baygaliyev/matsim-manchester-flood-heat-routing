"""Shared path configuration for the Manchester flood/heat analysis scripts.

Every path can be overridden with an environment variable (see below) or with a
command-line flag in the individual scripts. Defaults are relative to this
repository, so the code runs from a fresh clone once the data has been placed
under ``input/`` and the MATSim run outputs under ``output/``.

Environment variables
---------------------
MATSIM_INPUT_DIR    Directory holding the WBGT ``*.bin`` grids, ``wbgt_grid.meta``
                    and ``network_with_flood_data.zip`` (default: ``<repo>/input``)
MATSIM_OUTPUT_DIR   Directory holding the MATSim run folders ``results_heat_*``
                    (default: ``<repo>/output``)
MATSIM_FIGURES_DIR  Where generated maps are written
                    (default: ``<repo>/output/figures``)
WBGT_NC_FILE        Source NetCDF consumed by ``preprocess_wbgt.py``
                    (default: ``<MATSIM_INPUT_DIR>/WBGT_2025.nc``)
"""

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

DEFAULT_INPUT_DIR = REPO_ROOT / "input"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "output"
DEFAULT_FIGURES_DIR = DEFAULT_OUTPUT_DIR / "figures"


def input_dir():
    return Path(os.environ.get("MATSIM_INPUT_DIR", DEFAULT_INPUT_DIR))


def output_dir():
    return Path(os.environ.get("MATSIM_OUTPUT_DIR", DEFAULT_OUTPUT_DIR))


def figures_dir():
    return Path(os.environ.get("MATSIM_FIGURES_DIR", DEFAULT_FIGURES_DIR))


def wbgt_nc_file():
    return Path(os.environ.get("WBGT_NC_FILE", input_dir() / "WBGT_2025.nc"))
