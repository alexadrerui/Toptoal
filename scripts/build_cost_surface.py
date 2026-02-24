#!/usr/bin/env python3
"""Gera custo de superfície e indicadores de equilíbrio de massas.

Regras iniciais (simples e objetivas):
- Declividade <= 30%  -> custo 1
- Declividade > 30%   -> custo 10
- Construções/residências -> custo 10 (penalidade máxima local)

Além disso, calcula um indicador simplificado de equilíbrio de massas
(corte vs aterro) para apoiar decisões de traçado.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

try:
    import numpy as np
except ImportError:  # pragma: no cover
    np = None

try:
    import rasterio
    from rasterio.features import rasterize
except ImportError:  # pragma: no cover
    rasterio = None
    rasterize = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Monta raster de custo de superfície e relatório de massas.")
    parser.add_argument("--dem", required=True, type=Path, help="DEM recortado (GeoTIFF).")
    parser.add_argument(
        "--osm-geojson",
        required=True,
        type=Path,
        help="GeoJSON OSM com feições filtradas por polígono.",
    )
    parser.add_argument(
        "--cost-out",
        type=Path,
        default=Path("data/interim/cost_surface.tif"),
        help="Saída do raster de custo.",
    )
    parser.add_argument(
        "--report-out",
        type=Path,
        default=Path("data/interim/cost_surface_report.json"),
        help="Saída do relatório JSON.",
    )
    parser.add_argument(
        "--target-elevation",
        type=float,
        default=None,
        help="Cota de referência para equilíbrio de massas. Se omitido, usa mediana do DEM.",
    )
    return parser.parse_args()


def _load_osm_building_shapes(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    features = payload.get("features", [])
    building_shapes: list[dict[str, Any]] = []

    for feature in features:
        props = feature.get("properties", {})
        geom = feature.get("geometry")
        if not geom:
            continue

        has_building = "building" in props
        is_residential = props.get("building") == "residential" or props.get("landuse") == "residential"
        if not (has_building or is_residential):
            continue

        if geom.get("type") == "Polygon":
            building_shapes.append(geom)

    return building_shapes


def _compute_slope_percent(dem: np.ndarray, transform: Any) -> np.ndarray:
    xres = abs(transform.a)
    yres = abs(transform.e)
    if xres == 0 or yres == 0:
        raise ValueError("Resolução espacial inválida no raster.")

    dz_dy, dz_dx = np.gradient(dem, yres, xres)
    slope_percent = np.sqrt(dz_dx**2 + dz_dy**2) * 100.0
    return slope_percent


def _mass_balance_metrics(dem: np.ndarray, nodata_mask: np.ndarray, target_elevation: float) -> dict[str, float]:
    valid = ~nodata_mask
    diff = dem[valid] - target_elevation

    cut = float(np.sum(np.clip(diff, 0, None)))
    fill = float(np.sum(np.clip(-diff, 0, None)))

    if fill == 0.0 and cut == 0.0:
        ratio = 1.0
    elif fill == 0.0:
        ratio = float("inf")
    else:
        ratio = cut / fill

    imbalance = 0.0 if (cut + fill) == 0 else abs(cut - fill) / (cut + fill)

    return {
        "target_elevation": float(target_elevation),
        "estimated_cut_volume_index": cut,
        "estimated_fill_volume_index": fill,
        "cut_fill_ratio": ratio,
        "mass_balance_imbalance_index": float(imbalance),
    }


def main() -> None:
    args = parse_args()

    if np is None:
        raise RuntimeError("numpy não está instalado. Instale para gerar custo de superfície.")
    if rasterio is None or rasterize is None:
        raise RuntimeError("rasterio não está instalado. Instale para gerar custo de superfície.")

    with rasterio.open(args.dem) as src:
        dem_masked = src.read(1, masked=True)
        dem = dem_masked.filled(np.nan).astype(np.float32)
        transform = src.transform
        profile = src.profile.copy()

    nodata_mask = np.isnan(dem)
    slope_percent = _compute_slope_percent(np.nan_to_num(dem, nan=0.0), transform)

    # Regra solicitada para declividade.
    cost = np.where(slope_percent > 30.0, 10.0, 1.0).astype(np.float32)
    cost[nodata_mask] = np.nan

    # Penaliza construções/residências com custo 10.
    building_shapes = _load_osm_building_shapes(args.osm_geojson)
    building_count = len(building_shapes)
    if building_shapes:
        building_mask = rasterize(
            [(shape, 1) for shape in building_shapes],
            out_shape=cost.shape,
            transform=transform,
            fill=0,
            dtype="uint8",
        )
        cost = np.where(building_mask == 1, 10.0, cost)

    valid_slope = slope_percent[~nodata_mask]
    high_slope_cells = int(np.sum(valid_slope > 30.0))
    low_slope_cells = int(np.sum(valid_slope <= 30.0))

    if args.target_elevation is None:
        target_elevation = float(np.nanmedian(dem))
    else:
        target_elevation = float(args.target_elevation)

    mass_balance = _mass_balance_metrics(dem, nodata_mask, target_elevation)

    args.cost_out.parent.mkdir(parents=True, exist_ok=True)
    args.report_out.parent.mkdir(parents=True, exist_ok=True)

    out_nodata = -9999.0
    cost_to_write = np.where(np.isnan(cost), out_nodata, cost).astype(np.float32)

    profile.update(dtype="float32", count=1, nodata=out_nodata, compress="lzw")
    with rasterio.open(args.cost_out, "w", **profile) as dst:
        dst.write(cost_to_write, 1)

    report = {
        "rules": {
            "slope_lte_30_percent": 1,
            "slope_gt_30_percent": 10,
            "building_or_residential": 10,
        },
        "stats": {
            "low_slope_cells": low_slope_cells,
            "high_slope_cells": high_slope_cells,
            "building_shapes_count": building_count,
        },
        "mass_balance": mass_balance,
    }
    args.report_out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Custo de superfície salvo em: {args.cost_out}")
    print(f"Relatório salvo em: {args.report_out}")


if __name__ == "__main__":
    main()
