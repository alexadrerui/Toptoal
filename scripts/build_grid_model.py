#!/usr/bin/env python3
"""Gera grade e arestas de movimento a partir de DEM + raster de custo.

Saída inclui:
- nós (células) com elevação e coordenadas,
- arestas entre vizinhos (8-direções) com custo de movimento:
  custo = distância_horizontal * custo_médio_superfície + penalidade_vertical
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

try:
    import rasterio
except ImportError:  # pragma: no cover
    rasterio = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Cria grade e arestas ponderadas para roteamento.")
    parser.add_argument("--dem", required=True, type=Path, help="DEM recortado (GeoTIFF).")
    parser.add_argument("--cost-raster", type=Path, default=None, help="Raster de custo de superfície (opcional).")
    parser.add_argument("--out", type=Path, default=Path("data/interim/grid_model.json"), help="Saída JSON da grade.")
    parser.add_argument("--stride", type=int, default=15, help="Amostragem da grade (15 = blocos 15x15).")
    parser.add_argument(
        "--vertical-penalty-factor",
        type=float,
        default=0.05,
        help="Peso da penalidade vertical por metro de desnível.",
    )
    return parser.parse_args()


def _neighbor_steps() -> list[tuple[int, int, float]]:
    return [
        (-1, 0, 1.0),
        (1, 0, 1.0),
        (0, -1, 1.0),
        (0, 1, 1.0),
        (-1, -1, math.sqrt(2.0)),
        (-1, 1, math.sqrt(2.0)),
        (1, -1, math.sqrt(2.0)),
        (1, 1, math.sqrt(2.0)),
    ]


def build_grid(
    dem_path: Path,
    stride: int,
    cost_raster_path: Path | None,
    vertical_penalty_factor: float,
) -> dict[str, Any]:
    if rasterio is None:
        raise RuntimeError("rasterio não está instalado. Instale para criar grade a partir do DEM.")

    if stride <= 0:
        raise ValueError("--stride deve ser > 0.")

    with rasterio.open(dem_path) as src:
        dem_arr = src.read(1, masked=True)
        transform = src.transform
        cell_size_x = abs(transform.a)
        cell_size_y = abs(transform.e)

    if abs(cell_size_x - cell_size_y) > 1e-6:
        raise ValueError("Raster com células não quadradas não suportado neste modelo simplificado.")

    cost_arr = None
    if cost_raster_path is not None:
        with rasterio.open(cost_raster_path) as csrc:
            cost_arr = csrc.read(1, masked=True)
            if cost_arr.shape != dem_arr.shape:
                raise ValueError("DEM e cost-raster devem ter mesma resolução e shape.")

    rows, cols = dem_arr.shape
    cells: list[dict[str, Any]] = []
    node_index: dict[tuple[int, int], int] = {}

    node_id = 0
    for r in range(0, rows, stride):
        for c in range(0, cols, stride):
            v = dem_arr[r, c]
            if getattr(v, "mask", False):
                continue

            x, y = transform * (c, r)
            base_cost = None
            if cost_arr is not None:
                cv = cost_arr[r, c]
                if not getattr(cv, "mask", False):
                    base_cost = float(cv)

            cell = {
                "id": node_id,
                "row": r,
                "col": c,
                "x": float(x),
                "y": float(y),
                "elevation": float(v),
            }
            if base_cost is not None:
                cell["base_cost"] = base_cost

            cells.append(cell)
            node_index[(r, c)] = node_id
            node_id += 1

    edges: list[dict[str, Any]] = []
    step_m = cell_size_x * stride

    for cell in cells:
        r = int(cell["row"])
        c = int(cell["col"])
        z_from = float(cell["elevation"])
        base_from = float(cell.get("base_cost", 1.0))

        for dr, dc, d_factor in _neighbor_steps():
            nr = r + dr * stride
            nc = c + dc * stride
            to_id = node_index.get((nr, nc))
            if to_id is None:
                continue

            to_cell = cells[to_id]
            z_to = float(to_cell["elevation"])
            base_to = float(to_cell.get("base_cost", 1.0))

            horizontal = step_m * d_factor
            vertical = abs(z_to - z_from)
            thematic = (base_from + base_to) / 2.0
            movement_cost = horizontal * thematic + vertical_penalty_factor * vertical

            edges.append(
                {
                    "from": int(cell["id"]),
                    "to": int(to_id),
                    "horizontal_distance_m": float(horizontal),
                    "vertical_delta_m": float(vertical),
                    "thematic_cost_mean": float(thematic),
                    "movement_cost": float(movement_cost),
                }
            )

    return {
        "stride": stride,
        "cell_size_m": float(step_m),
        "vertical_penalty_factor": float(vertical_penalty_factor),
        "cell_count": len(cells),
        "edge_count": len(edges),
        "cells": cells,
        "edges": edges,
    }


def main() -> None:
    args = parse_args()
    model = build_grid(args.dem, args.stride, args.cost_raster, args.vertical_penalty_factor)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(model, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Grid salvo em: {args.out} (células: {model['cell_count']}, arestas: {model['edge_count']})")


if __name__ == "__main__":
    main()
