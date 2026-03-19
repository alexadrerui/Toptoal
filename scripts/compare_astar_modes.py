#!/usr/bin/env python3
"""Compara resultados entre A* raster e A* grafo."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compara relatórios do A* raster e A* grafo.")
    parser.add_argument("--raster-report", required=True, type=Path)
    parser.add_argument("--graph-report", required=True, type=Path)
    parser.add_argument("--out", type=Path, default=Path("outputs/reports/astar_compare_report.json"))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    raster = json.loads(args.raster_report.read_text(encoding="utf-8"))
    graph = json.loads(args.graph_report.read_text(encoding="utf-8"))

    raster_cost = float(raster.get("total_cost", 0.0))
    graph_cost = float(graph.get("total_cost", 0.0))
    delta = graph_cost - raster_cost
    rel = 0.0 if raster_cost == 0 else delta / raster_cost

    report = {
        "raster_total_cost": raster_cost,
        "graph_total_cost": graph_cost,
        "delta_cost_graph_minus_raster": delta,
        "relative_delta": rel,
        "raster_path_count": int(raster.get("path_cell_count", 0)),
        "graph_path_count": int(graph.get("path_node_count", 0)),
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Comparação salva em: {args.out}")


if __name__ == "__main__":
    main()
