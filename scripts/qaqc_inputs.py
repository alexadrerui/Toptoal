#!/usr/bin/env python3
"""QA/QC de insumos geoespaciais antes da geração da superfície de custo."""

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
except ImportError:  # pragma: no cover
    rasterio = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Executa QA/QC para DEM e OSM GeoJSON.")
    parser.add_argument("--dem", required=True, type=Path, help="DEM recortado (GeoTIFF).")
    parser.add_argument("--osm-geojson", required=True, type=Path, help="GeoJSON OSM filtrado por polígono.")
    parser.add_argument(
        "--thresholds",
        type=Path,
        default=Path("configs/qaqc_thresholds.json"),
        help="Arquivo JSON com regras de aceitação QA/QC.",
    )
    parser.add_argument("--out-report", type=Path, default=Path("outputs/reports/qaqc_report.json"), help="Relatório JSON de QA/QC.")
    return parser.parse_args()


def _load_thresholds(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {
        "max_dem_nodata_ratio": float(payload.get("max_dem_nodata_ratio", 0.15)),
        "require_projected_crs": bool(payload.get("require_projected_crs", False)),
        "min_osm_feature_count": int(payload.get("min_osm_feature_count", 1)),
        "max_invalid_geometry_ratio": float(payload.get("max_invalid_geometry_ratio", 0.05)),
        "require_thematic_layers": payload.get(
            "require_thematic_layers",
            {"roads": True, "water": True, "buildings": True},
        ),
    }


def _validate_osm_geojson(path: Path, thresholds: dict[str, Any]) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    features = payload.get("features", []) if payload.get("type") == "FeatureCollection" else []

    if len(features) < thresholds["min_osm_feature_count"]:
        return {
            "status": "fail",
            "reason": f"Poucas features OSM: {len(features)} < {thresholds['min_osm_feature_count']}",
            "feature_count": len(features),
            "building_features": 0,
            "water_features": 0,
            "road_features": 0,
            "invalid_geometries": 0,
            "invalid_geometry_ratio": 0.0,
        }

    building = 0
    water = 0
    roads = 0
    invalid_geom = 0
    allowed_types = {"Point", "MultiPoint", "LineString", "MultiLineString", "Polygon", "MultiPolygon"}

    for feat in features:
        geom = feat.get("geometry")
        props = feat.get("properties", {})

        if not geom or geom.get("type") not in allowed_types:
            invalid_geom += 1
            continue

        if "building" in props or props.get("landuse") == "residential":
            building += 1
        if "waterway" in props or props.get("natural") == "water" or props.get("landuse") == "reservoir":
            water += 1
        if "highway" in props:
            roads += 1

    invalid_ratio = invalid_geom / len(features)
    issues: list[str] = []
    status = "pass"

    if invalid_ratio > thresholds["max_invalid_geometry_ratio"]:
        status = "fail"
        issues.append(
            f"Taxa de geometria inválida alta: {invalid_ratio:.3f} > {thresholds['max_invalid_geometry_ratio']:.3f}"
        )

    req = thresholds["require_thematic_layers"]
    if req.get("roads", False) and roads == 0:
        status = "fail"
        issues.append("Camada de vias ausente.")
    if req.get("water", False) and water == 0:
        status = "fail"
        issues.append("Camada hídrica ausente.")
    if req.get("buildings", False) and building == 0:
        status = "warn" if status != "fail" else status
        issues.append("Camada de construções ausente.")

    return {
        "status": status,
        "reason": "ok" if not issues else "; ".join(issues),
        "feature_count": len(features),
        "building_features": building,
        "water_features": water,
        "road_features": roads,
        "invalid_geometries": invalid_geom,
        "invalid_geometry_ratio": invalid_ratio,
    }


def _validate_dem(path: Path, thresholds: dict[str, Any]) -> dict[str, Any]:
    if np is None or rasterio is None:
        raise RuntimeError("numpy/rasterio não instalados. Instale para executar QA/QC do DEM.")

    with rasterio.open(path) as src:
        arr = src.read(1, masked=True)
        crs = src.crs
        transform = src.transform
        width = src.width
        height = src.height

    total_cells = int(width * height)
    nodata_cells = int(np.sum(arr.mask)) if hasattr(arr, "mask") else 0
    nodata_ratio = 0.0 if total_cells == 0 else nodata_cells / total_cells

    xres = abs(transform.a)
    yres = abs(transform.e)
    square_cells = abs(xres - yres) < 1e-6
    is_projected = bool(crs and crs.is_projected)

    issues: list[str] = []
    status = "pass"

    if nodata_ratio > thresholds["max_dem_nodata_ratio"]:
        status = "fail"
        issues.append(f"NoData ratio alto: {nodata_ratio:.3f} > {thresholds['max_dem_nodata_ratio']:.3f}")

    if thresholds["require_projected_crs"] and not is_projected:
        status = "fail"
        issues.append("CRS não projetado (metros) e regra exige CRS projetado.")

    if not square_cells:
        status = "warn" if status != "fail" else status
        issues.append("Células não quadradas detectadas; pode afetar custos de movimento.")

    return {
        "status": status,
        "reason": "ok" if not issues else "; ".join(issues),
        "width": width,
        "height": height,
        "cell_size_x": xres,
        "cell_size_y": yres,
        "square_cells": square_cells,
        "crs": str(crs) if crs else None,
        "is_projected_crs": is_projected,
        "nodata_ratio": nodata_ratio,
    }


def main() -> None:
    args = parse_args()
    thresholds = _load_thresholds(args.thresholds)

    dem_report = _validate_dem(args.dem, thresholds)
    osm_report = _validate_osm_geojson(args.osm_geojson, thresholds)

    status_order = {"pass": 0, "warn": 1, "fail": 2}
    overall = "pass"
    for status in [dem_report["status"], osm_report["status"]]:
        if status_order[status] > status_order[overall]:
            overall = status

    report = {
        "overall_status": overall,
        "thresholds": thresholds,
        "dem": dem_report,
        "osm": osm_report,
        "recommendation": (
            "Prosseguir com geração de custo." if overall == "pass" else "Revisar alertas/falhas antes de gerar custo."
        ),
    }

    args.out_report.parent.mkdir(parents=True, exist_ok=True)
    args.out_report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"QA/QC salvo em: {args.out_report} (status: {overall})")

    if overall == "fail":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
