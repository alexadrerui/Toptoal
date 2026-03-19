#!/usr/bin/env python3
"""Gera uma estrutura de grade (células) a partir de um DEM recortado.

Objetivo: preparar formato matemático simples para o algoritmo de caminho.
Cada célula representa um "quadrado" navegável com custo base derivado da elevação.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

try:
    import rasterio
except ImportError:  # pragma: no cover
    rasterio = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Cria grid de estudo a partir do DEM recortado.")
    parser.add_argument("--dem", required=True, type=Path, help="DEM recortado (GeoTIFF).")
    parser.add_argument("--out", type=Path, default=Path("data/interim/grid_model.json"), help="Saída JSON da grade.")
    parser.add_argument("--stride", type=int, default=2, help="Amostragem da grade (2 = usa blocos 2x2).")
    return parser.parse_args()


def build_grid(dem_path: Path, stride: int) -> dict[str, Any]:
    if rasterio is None:
        raise RuntimeError("rasterio não está instalado. Instale para criar grade a partir do DEM.")

    with rasterio.open(dem_path) as src:
        arr = src.read(1, masked=True)
        transform = src.transform

        cells: list[dict[str, Any]] = []
        rows, cols = arr.shape
        cell_id = 0

        for r in range(0, rows, stride):
            for c in range(0, cols, stride):
                value = arr[r, c]
                if getattr(value, "mask", False):
                    continue

                lon, lat = transform * (c, r)
                cells.append(
                    {
                        "id": cell_id,
                        "row": r,
                        "col": c,
                        "x": lon,
                        "y": lat,
                        "elevation": float(value),
                    }
                )
                cell_id += 1

    return {
        "stride": stride,
        "cell_count": len(cells),
        "cells": cells,
    }


def main() -> None:
    args = parse_args()
    model = build_grid(args.dem, args.stride)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(model, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Grid salvo em: {args.out} (células: {model['cell_count']})")


if __name__ == "__main__":
    main()
