#!/usr/bin/env python3
"""Gera custo de superfície com lógica de terra, água e construções.

Regras base (Etapa 2):
- Terra plana/baixa declividade (<= 30%): custo 1
- Terra com declividade > 30%: custo 10
- Construções/residências: custo 10
- Água (rios/lagos/reservatórios): custo 15
- Vias existentes (highway): custo reduzido (prioridade de reaproveitamento)

A água não é barreira infinita: isso permite ao A* avaliar ponte (atravessar)
versus contorno (desviar) pela menor soma de custo total.
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
    parser.add_argument("--osm-geojson", required=True, type=Path, help="GeoJSON OSM filtrado por polígono.")
    parser.add_argument("--cost-out", type=Path, default=Path("data/interim/cost_surface.tif"), help="Saída raster de custo.")
    parser.add_argument(
        "--report-out",
        type=Path,
        default=Path("data/interim/cost_surface_report.json"),
        help="Relatório JSON com estatísticas e equilíbrio de massas.",
    )
    parser.add_argument(
        "--params",
        type=Path,
        default=Path("configs/cost_parameters.json"),
        help="JSON de parâmetros de custo.",
    )
    parser.add_argument(
        "--target-elevation",
        type=float,
        default=None,
        help="Cota de referência para equilíbrio de massas. Se omitida, usa mediana do DEM.",
    )
    parser.add_argument(
        "--qaqc-report",
        type=Path,
        default=None,
        help="Relatório QA/QC (JSON). Se informado e status=fail, interrompe execução.",
    )
    return parser.parse_args()


def _load_params(path: Path) -> dict[str, float]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {
        "terrain_cost_flat": float(payload.get("terrain_cost_flat", 1)),
        "terrain_cost_steep": float(payload.get("terrain_cost_steep_gt_30_percent", 10)),
        "building_cost": float(payload.get("building_cost", 10)),
        "water_cost": float(payload.get("water_cost", 15)),
        "existing_road_cost": float(payload.get("existing_road_cost", 0.6)),
    }


def _load_osm_shapes(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    features = payload.get("features", [])
    building_shapes: list[dict[str, Any]] = []
    water_shapes: list[dict[str, Any]] = []
    road_shapes: list[dict[str, Any]] = []

    for feature in features:
        props = feature.get("properties", {})
        geom = feature.get("geometry")
        if not geom:
            continue

        geom_type = geom.get("type")

        has_building = "building" in props or props.get("landuse") == "residential"
        if has_building and geom_type in {"Polygon", "MultiPolygon"}:
            building_shapes.append(geom)

        is_water = (
            "waterway" in props
            or props.get("natural") == "water"
            or props.get("landuse") == "reservoir"
            or props.get("water") is not None
        )
        if is_water and geom_type in {"Polygon", "MultiPolygon", "LineString", "MultiLineString"}:
            water_shapes.append(geom)

        is_road = "highway" in props
        if is_road and geom_type in {"LineString", "MultiLineString", "Polygon", "MultiPolygon"}:
            road_shapes.append(geom)

    return building_shapes, water_shapes, road_shapes


def _compute_slope_percent(dem: np.ndarray, transform: Any) -> np.ndarray:
    xres = abs(transform.a)
    yres = abs(transform.e)
    if xres == 0 or yres == 0:
        raise ValueError("Resolução espacial inválida no raster.")

    dz_dy, dz_dx = np.gradient(dem, yres, xres)
    return np.sqrt(dz_dx**2 + dz_dy**2) * 100.0


def _mass_balance_metrics(dem: np.ndarray, nodata_mask: np.ndarray, target_elevation: float) -> dict[str, float]:
    valid = ~nodata_mask
    diff = dem[valid] - target_elevation

    cut = float(np.sum(np.clip(diff, 0, None)))
    fill = float(np.sum(np.clip(-diff, 0, None)))
    ratio = 1.0 if (fill == 0 and cut == 0) else (float("inf") if fill == 0 else cut / fill)
    imbalance = 0.0 if (cut + fill) == 0 else abs(cut - fill) / (cut + fill)

    return {
        "target_elevation": float(target_elevation),
        "estimated_cut_volume_index": cut,
        "estimated_fill_volume_index": fill,
        "cut_fill_ratio": ratio,
        "mass_balance_imbalance_index": float(imbalance),
    }


def _raster_mask(shapes: list[dict[str, Any]], out_shape: tuple[int, int], transform: Any) -> np.ndarray:
    if not shapes:
        return np.zeros(out_shape, dtype="uint8")
    return rasterize([(shape, 1) for shape in shapes], out_shape=out_shape, transform=transform, fill=0, dtype="uint8")


def main() -> None:
    args = parse_args()

    if np is None:
        raise RuntimeError("numpy não está instalado. Instale para gerar custo de superfície.")
    if rasterio is None or rasterize is None:
        raise RuntimeError("rasterio não está instalado. Instale para gerar custo de superfície.")

    params = _load_params(args.params)

    if args.qaqc_report is not None:
        qaqc = json.loads(args.qaqc_report.read_text(encoding="utf-8"))
        if qaqc.get("overall_status") == "fail":
            raise RuntimeError("QA/QC com status FAIL. Corrija os insumos antes de gerar custo.")

    with rasterio.open(args.dem) as src:
        dem_masked = src.read(1, masked=True)
        dem = dem_masked.filled(np.nan).astype(np.float32)
        transform = src.transform
        profile = src.profile.copy()

    nodata_mask = np.isnan(dem)
    slope_percent = _compute_slope_percent(np.nan_to_num(dem, nan=0.0), transform)

    # Custo base de terreno por declividade.
    cost = np.where(slope_percent > 30.0, params["terrain_cost_steep"], params["terrain_cost_flat"]).astype(np.float32)
    cost[nodata_mask] = np.nan

    building_shapes, water_shapes, road_shapes = _load_osm_shapes(args.osm_geojson)
    building_mask = _raster_mask(building_shapes, cost.shape, transform)
    water_mask = _raster_mask(water_shapes, cost.shape, transform)
    road_mask = _raster_mask(road_shapes, cost.shape, transform)

    # Prioridade de decisão: desviar da água, mas ainda permitir ponte se vantajoso.
    cost = np.where(water_mask == 1, params["water_cost"], cost)

    # Construções continuam com alta penalidade.
    cost = np.where(building_mask == 1, params["building_cost"], cost)

    # Prioriza vias existentes (menor custo), sem sobrescrever água/construções.
    road_priority_mask = (road_mask == 1) & (water_mask == 0) & (building_mask == 0)
    cost = np.where(road_priority_mask, np.minimum(cost, params["existing_road_cost"]), cost)
    cost[nodata_mask] = np.nan

    valid_slope = slope_percent[~nodata_mask]
    high_slope_cells = int(np.sum(valid_slope > 30.0))
    low_slope_cells = int(np.sum(valid_slope <= 30.0))

    water_cells = int(np.sum((water_mask == 1) & (~nodata_mask)))
    building_cells = int(np.sum((building_mask == 1) & (~nodata_mask)))
    road_cells = int(np.sum((road_mask == 1) & (~nodata_mask)))
    prioritized_road_cells = int(np.sum(road_priority_mask & (~nodata_mask)))

    target_elevation = float(np.nanmedian(dem)) if args.target_elevation is None else float(args.target_elevation)
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
            "slope_lte_30_percent": params["terrain_cost_flat"],
            "slope_gt_30_percent": params["terrain_cost_steep"],
            "building_or_residential": params["building_cost"],
            "water": params["water_cost"],
            "existing_road": params["existing_road_cost"],
        },
        "bridge_logic": {
            "water_cell_equivalence": "1 célula de água (5m) ~ 15 células de terra plana (75m)",
            "decision_note": "A* escolhe ponte quando o desvio terrestre acumulado ultrapassa custo equivalente da travessia aquática.",
        },
        "stats": {
            "low_slope_cells": low_slope_cells,
            "high_slope_cells": high_slope_cells,
            "building_shapes_count": len(building_shapes),
            "water_shapes_count": len(water_shapes),
            "road_shapes_count": len(road_shapes),
            "building_cells": building_cells,
            "water_cells": water_cells,
            "road_cells": road_cells,
            "prioritized_road_cells": prioritized_road_cells,
        },
        "mass_balance": mass_balance,
    }
    args.report_out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Custo de superfície salvo em: {args.cost_out}")
    print(f"Relatório salvo em: {args.report_out}")


if __name__ == "__main__":
    main()
