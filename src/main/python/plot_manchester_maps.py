#!/usr/bin/env python3
"""Deprecated entry point for the Manchester WBGT maps.

The WBGT figure is now produced by ``plot_heatmap_with_network.py``, which
clips the raster to the Greater Manchester boundary, uses a per-panel robust
colour scale (so cooler periods are not rendered as a flat block), reserves a
dedicated colourbar axis per panel, and locks every panel to one shared extent.

This module is kept only as a redirect so older commands keep working and can
never regenerate the legacy ``heatmap_manchester_*`` flat-blue figures.

Run ``python plot_heatmap_with_network.py --help`` for the current options.
"""

import sys

import plot_heatmap_with_network as _current


if __name__ == "__main__":
    print(
        "plot_manchester_maps.py is deprecated; "
        "delegating to plot_heatmap_with_network.py",
        file=sys.stderr,
    )
    _current.main()
