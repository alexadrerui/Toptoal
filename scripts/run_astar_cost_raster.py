#!/usr/bin/env python3
"""Executa A* sobre raster de custo (Etapa 2)."""

from __future__ import annotations

import argparse
import heapq
import json
from pathlib import Path
from typing import Any

try:
    import numpy as np
except ImportError:  # pragma: no cover
    np = None

try:
    import rasterio
except ImportError:  # pragma: no cover
    rasterio = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Calcula rota A* em raster de custo.")
    parser.add_argument("--cost-raster", required=True, type=Path)
    parser.add_argument("--start-lon", required=True, type=float)
    parser.add_argument("--start-lat", required=True, type=float)
    parser.add_argument("--end-lon", required=True, type=float)
    parser.add_argument("--end-lat", required=True, type=float)
    parser.add_argument("--out", type=Path, default=Path("outputs/reports/astar_path.json"))
    return parser.parse_args()


def _heuristic(a: tuple[int, int], b: tuple[int, int]) -> float:
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


def _neighbors(r: int, c: int, rows: int, cols: int) -> list[tuple[int, int, float]]:
    steps = [
        (-1, 0, 1.0),
        (1, 0, 1.0),
        (0, -1, 1.0),
        (0, 1, 1.0),
        (-1, -1, 1.4142),
        (-1, 1, 1.4142),
        (1, -1, 1.4142),
        (1, 1, 1.4142),
    ]
    out: list[tuple[int, int, float]] = []
    for dr, dc, d in steps:
        nr, nc = r + dr, c + dc
        if 0 <= nr < rows and 0 <= nc < cols:
            out.append((nr, nc, d))
    return out


def astar(cost: np.ndarray, start: tuple[int, int], goal: tuple[int, int], nodata: float) -> tuple[list[tuple[int, int]], float]:
    rows, cols = cost.shape
    open_heap: list[tuple[float, tuple[int, int]]] = []
    heapq.heappush(open_heap, (0.0, start))

    came_from: dict[tuple[int, int], tuple[int, int]] = {}
    g_score = {start: 0.0}

    while open_heap:
        _, current = heapq.heappop(open_heap)
        if current == goal:
            path = [current]
            while current in came_from:
                current = came_from[current]
                path.append(current)
            path.reverse()
            return path, g_score[goal]

        cr, cc = current
        for nr, nc, dist in _neighbors(cr, cc, rows, cols):
            cell_cost = float(cost[nr, nc])
            if cell_cost == nodata:
                continue

            tentative = g_score[current] + cell_cost * dist
            neigh = (nr, nc)
            if tentative < g_score.get(neigh, float("inf")):
                came_from[neigh] = current
                g_score[neigh] = tentative
                f_score = tentative + _heuristic(neigh, goal)
                heapq.heappush(open_heap, (f_score, neigh))

    raise RuntimeError("Não foi possível encontrar rota entre origem e destino.")


def main() -> None:
    args = parse_args()
    if np is None or rasterio is None:
        raise RuntimeError("numpy/rasterio não instalados. Instale para executar A* no raster.")

    with rasterio.open(args.cost_raster) as src:
        cost = src.read(1)
        nodata = src.nodata
        start_row, start_col = src.index(args.start_lon, args.start_lat)
        end_row, end_col = src.index(args.end_lon, args.end_lat)
        transform = src.transform

    path, total_cost = astar(cost, (start_row, start_col), (end_row, end_col), nodata)

    coords = []
    for r, c in path:
        x, y = transform * (c, r)
        coords.append([float(x), float(y)])

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(
            {
                "start": [args.start_lon, args.start_lat],
                "end": [args.end_lon, args.end_lat],
                "path_cell_count": len(path),
                "total_cost": total_cost,
                "path_coords": coords,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"Rota A* salva em: {args.out} (custo total: {total_cost:.2f})")


if __name__ == "__main__":
    main()
