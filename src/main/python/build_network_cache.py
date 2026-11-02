#!/usr/bin/env python
"""Cache MATSim node and link geometry as Parquet for fast map rendering.

The flood network XML is ~3.9 GB.  Parsing it once and caching node coordinates
and link endpoints makes the map and route scripts fast enough to iterate on.
"""

from __future__ import annotations

import argparse
import time
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[5]
DEFAULT_ZIP = PROJECT_ROOT / "data" / "input" / "network_with_flood_data.zip"
DEFAULT_XML = "network_with_flood_data.xml"
DEFAULT_OUT_DIR = PROJECT_ROOT / "results" / "network_cache"


def build_cache(zip_path: Path, xml_name: str, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    nodes: dict[str, tuple[float, float]] = {}
    links: list[tuple[str, str, str, float | None]] = []
    started = time.time()

    with zipfile.ZipFile(zip_path, "r") as zf:
        with zf.open(xml_name) as handle:
            for event, elem in ET.iterparse(handle, events=("end",)):
                if elem.tag == "node":
                    nodes[elem.get("id")] = (float(elem.get("x")), float(elem.get("y")))
                elif elem.tag == "link":
                    length = elem.get("length")
                    links.append(
                        (
                            elem.get("id"),
                            elem.get("from"),
                            elem.get("to"),
                            float(length) if length is not None else None,
                        )
                    )
                elem.clear()
                if len(links) % 250_000 == 0 and len(links):
                    print(f"  parsed {len(links):,} links, {len(nodes):,} nodes, {time.time()-started:.0f}s")

    print(f"Parsed {len(nodes):,} nodes and {len(links):,} links in {time.time()-started:.0f}s")

    node_df = pd.DataFrame(
        [(int(node_id), x, y) for node_id, (x, y) in nodes.items()],
        columns=["node_id", "x", "y"],
    )
    link_df = pd.DataFrame(links, columns=["link_id", "from_node", "to_node", "length"])
    link_df["from_node"] = link_df["from_node"].astype("int64")
    link_df["to_node"] = link_df["to_node"].astype("int64")

    node_df.to_parquet(out_dir / "network_nodes.parquet", index=False)
    link_df.to_parquet(out_dir / "network_links.parquet", index=False)

    print(f"Node bounds: x [{node_df.x.min():.1f}, {node_df.x.max():.1f}], y [{node_df.y.min():.1f}, {node_df.y.max():.1f}]")
    print(f"Wrote {out_dir / 'network_nodes.parquet'} and {out_dir / 'network_links.parquet'}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zip", type=Path, default=DEFAULT_ZIP)
    parser.add_argument("--xml-name", default=DEFAULT_XML)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args()
    build_cache(args.zip, args.xml_name, args.out_dir)


if __name__ == "__main__":
    main()
