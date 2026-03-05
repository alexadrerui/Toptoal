#!/usr/bin/env python3
"""Estimativa preliminar de corte/aterro para alternativas de eixo.

Suporta duas abordagens para cota de formação:
1) sem perfil de projeto: usa cota local do terreno + espessura de pavimento;
2) com perfil de projeto: usa greide fornecido por estação (recomendado).
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Iterable

try:
    import numpy as np
except ImportError:  # pragma: no cover
    np = None

try:
    import rasterio
except ImportError:  # pragma: no cover
    rasterio = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Calcula corte/aterro por alternativa de eixo com seção parametrizada.")
    parser.add_argument("--dem", required=True, type=Path, help="DEM recortado (GeoTIFF).")
    parser.add_argument("--axes-geojson", required=True, type=Path, help="GeoJSON com alternativas (LineString).")
    parser.add_argument("--params", type=Path, default=Path("configs/cross_section_parameters.json"), help="Parâmetros da seção transversal.")
    parser.add_argument("--design-profile", type=Path, default=None, help="Perfil de projeto (greide) por alternativa.")
    parser.add_argument("--out-report", type=Path, default=Path("outputs/reports/earthwork_alternatives_report.json"), help="Relatório de saída.")
    return parser.parse_args()


def _load_axes(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("type") == "FeatureCollection":
        features = payload.get("features", [])
    elif payload.get("type") == "Feature":
        features = [payload]
    else:
        raise ValueError("GeoJSON de alternativas deve ser Feature ou FeatureCollection.")

    alternatives: list[dict[str, Any]] = []
    for i, feat in enumerate(features):
        geom = feat.get("geometry", {})
        gtype = geom.get("type")
        if gtype not in {"LineString", "MultiLineString"}:
            continue

        if gtype == "LineString":
            coords = geom.get("coordinates", [])
        else:
            parts = geom.get("coordinates", [])
            coords = [pt for part in parts for pt in part]

        if len(coords) < 2:
            continue

        alternatives.append({
            "id": feat.get("properties", {}).get("id", f"alt_{i+1}"),
            "name": feat.get("properties", {}).get("name", f"Alternativa {i+1}"),
            "coords": [(float(x), float(y)) for x, y in coords],
        })

    if not alternatives:
        raise ValueError("Nenhuma alternativa válida (LineString/MultiLineString) encontrada.")
    return alternatives


def _load_params(path: Path) -> dict[str, float]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {
        "platform_width_m": float(payload.get("platform_width_m", 12.0)),
        "pavement_thickness_m": float(payload.get("pavement_thickness_m", 0.25)),
        "side_slope_cut_hv": float(payload.get("side_slope_cut_hv", 1.5)),
        "side_slope_fill_hv": float(payload.get("side_slope_fill_hv", 2.0)),
        "station_step_m": float(payload.get("station_step_m", 20.0)),
        "cross_section_half_width_m": float(payload.get("cross_section_half_width_m", 30.0)),
        "sample_spacing_m": float(payload.get("sample_spacing_m", 2.5)),
    }


def _load_design_profile(path: Path | None) -> dict[str, list[dict[str, float]]]:
    if path is None:
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    out: dict[str, list[dict[str, float]]] = {}
    for p in payload.get("profiles", []):
        out[p.get("id")] = p.get("stations", [])
    return out


def _segment_length(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(b[0] - a[0], b[1] - a[1])


def _line_length(coords: list[tuple[float, float]]) -> float:
    return sum(_segment_length(coords[i], coords[i + 1]) for i in range(len(coords) - 1))


def _interpolate_along(coords: list[tuple[float, float]], dist: float) -> tuple[float, float]:
    remaining = dist
    for i in range(len(coords) - 1):
        a = coords[i]
        b = coords[i + 1]
        seg = _segment_length(a, b)
        if seg == 0:
            continue
        if remaining <= seg:
            t = remaining / seg
            return (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]))
        remaining -= seg
    return coords[-1]


def _tangent_along(coords: list[tuple[float, float]], dist: float, eps: float = 1.0) -> tuple[float, float]:
    total = _line_length(coords)
    d0 = max(0.0, dist - eps)
    d1 = min(total, dist + eps)
    p0 = _interpolate_along(coords, d0)
    p1 = _interpolate_along(coords, d1)
    vx, vy = p1[0] - p0[0], p1[1] - p0[1]
    norm = math.hypot(vx, vy)
    if norm == 0:
        return (1.0, 0.0)
    return (vx / norm, vy / norm)


def _sample_dem(src: Any, coords: Iterable[tuple[float, float]]) -> np.ndarray:
    values = []
    nodata = src.nodata
    for val in src.sample(coords):
        z = float(val[0])
        if nodata is not None and z == nodata:
            values.append(np.nan)
        else:
            values.append(z)
    return np.array(values, dtype=np.float64)


def _formation_elevation(
    src: Any,
    center: tuple[float, float],
    pavement_thickness: float,
    station_m: float,
    design_stations: list[dict[str, float]] | None,
) -> float:
    if design_stations:
        # Interpola por estação no greide
        if station_m <= design_stations[0]["station_m"]:
            return float(design_stations[0]["design_elevation_m"])
        if station_m >= design_stations[-1]["station_m"]:
            return float(design_stations[-1]["design_elevation_m"])

        for i in range(len(design_stations) - 1):
            a = design_stations[i]
            b = design_stations[i + 1]
            if a["station_m"] <= station_m <= b["station_m"]:
                span = b["station_m"] - a["station_m"]
                t = 0.0 if span == 0 else (station_m - a["station_m"]) / span
                return float(a["design_elevation_m"] + t * (b["design_elevation_m"] - a["design_elevation_m"]))

    center_z = _sample_dem(src, [center])[0]
    if np.isnan(center_z):
        return float("nan")
    return float(center_z + pavement_thickness)


def _cross_section_area(
    src: Any,
    center: tuple[float, float],
    tangent: tuple[float, float],
    platform_half_width: float,
    half_width: float,
    sample_spacing: float,
    formation_center: float,
    side_slope_cut_hv: float,
    side_slope_fill_hv: float,
) -> tuple[float, float]:
    tx, ty = tangent
    nx, ny = -ty, tx

    offsets = np.arange(-half_width, half_width + sample_spacing, sample_spacing, dtype=np.float64)
    sample_points = [(center[0] + nx * d, center[1] + ny * d) for d in offsets]
    ground = _sample_dem(src, sample_points)

    if np.isnan(formation_center):
        return (0.0, 0.0)

    design = np.full_like(offsets, formation_center, dtype=np.float64)
    abs_off = np.abs(offsets)
    beyond = abs_off > platform_half_width
    extra = abs_off[beyond] - platform_half_width

    if extra.size:
        ground_out = ground[beyond]
        cut_case = ground_out >= formation_center
        fill_case = ~cut_case

        design_out = np.full_like(extra, formation_center)
        design_out[cut_case] = formation_center + (extra[cut_case] / max(side_slope_cut_hv, 0.01))
        design_out[fill_case] = formation_center - (extra[fill_case] / max(side_slope_fill_hv, 0.01))
        design[beyond] = design_out

    valid = ~np.isnan(ground)
    if not np.any(valid):
        return (0.0, 0.0)

    diff = design[valid] - ground[valid]
    fill_area = float(np.sum(np.clip(diff, 0.0, None)) * sample_spacing)
    cut_area = float(np.sum(np.clip(-diff, 0.0, None)) * sample_spacing)
    return (cut_area, fill_area)


def _evaluate_alternative(
    src: Any,
    coords: list[tuple[float, float]],
    params: dict[str, float],
    design_stations: list[dict[str, float]] | None,
) -> dict[str, Any]:
    line_len = _line_length(coords)
    station_step = params["station_step_m"]
    stations = np.arange(0.0, line_len + station_step, station_step)

    platform_half = params["platform_width_m"] / 2.0
    total_cut = 0.0
    total_fill = 0.0

    for st in stations:
        stf = float(st)
        center = _interpolate_along(coords, stf)
        tangent = _tangent_along(coords, stf)
        formation_center = _formation_elevation(
            src,
            center,
            params["pavement_thickness_m"],
            stf,
            design_stations,
        )
        cut_area, fill_area = _cross_section_area(
            src=src,
            center=center,
            tangent=tangent,
            platform_half_width=platform_half,
            half_width=params["cross_section_half_width_m"],
            sample_spacing=params["sample_spacing_m"],
            formation_center=formation_center,
            side_slope_cut_hv=params["side_slope_cut_hv"],
            side_slope_fill_hv=params["side_slope_fill_hv"],
        )
        total_cut += cut_area * station_step
        total_fill += fill_area * station_step

    ratio = 1.0 if (total_cut == 0 and total_fill == 0) else (float("inf") if total_fill == 0 else total_cut / total_fill)
    imbalance = 0.0 if (total_cut + total_fill) == 0 else abs(total_cut - total_fill) / (total_cut + total_fill)

    return {
        "length_m": float(line_len),
        "station_count": int(len(stations)),
        "estimated_cut_volume_m3": float(total_cut),
        "estimated_fill_volume_m3": float(total_fill),
        "cut_fill_ratio": float(ratio),
        "mass_balance_imbalance_index": float(imbalance),
    }


def rank_alternatives(evaluations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        evaluations,
        key=lambda x: (x["mass_balance_imbalance_index"], x["estimated_cut_volume_m3"] + x["estimated_fill_volume_m3"]),
    )


def main() -> None:
    args = parse_args()
    if np is None or rasterio is None:
        raise RuntimeError("numpy/rasterio não instalados. Instale para avaliação de corte/aterro.")

    params = _load_params(args.params)
    alternatives = _load_axes(args.axes_geojson)
    profiles = _load_design_profile(args.design_profile)

    with rasterio.open(args.dem) as src:
        evaluations = []
        for alt in alternatives:
            design_stations = profiles.get(alt["id"])
            metrics = _evaluate_alternative(src, alt["coords"], params, design_stations)
            evaluations.append({"id": alt["id"], "name": alt["name"], **metrics})

    ranked = rank_alternatives(evaluations)
    report = {
        "params": params,
        "design_profile_used": bool(args.design_profile),
        "alternatives": evaluations,
        "ranking_mass_balance": [item["id"] for item in ranked],
        "recommended_by_mass_balance": ranked[0]["id"] if ranked else None,
    }

    args.out_report.parent.mkdir(parents=True, exist_ok=True)
    args.out_report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Relatório de corte/aterro salvo em: {args.out_report}")


if __name__ == "__main__":
    main()
