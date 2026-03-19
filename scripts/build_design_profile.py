#!/usr/bin/env python3
"""Gera perfil de projeto (greide) preliminar para alternativas de eixo."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Cria perfil de projeto por alternativa de eixo.")
    parser.add_argument("--axes-geojson", required=True, type=Path, help="GeoJSON com alternativas LineString.")
    parser.add_argument("--station-step-m", type=float, default=20.0, help="Passo de estaqueamento.")
    parser.add_argument("--start-elevation", type=float, required=True, help="Cota inicial do greide.")
    parser.add_argument("--grade-percent", type=float, default=0.5, help="Rampa longitudinal em %%.")
    parser.add_argument("--out", type=Path, default=Path("data/interim/design_profile.json"))
    return parser.parse_args()


def _line_length(coords: list[tuple[float, float]]) -> float:
    total = 0.0
    for i in range(len(coords) - 1):
        total += math.hypot(coords[i + 1][0] - coords[i][0], coords[i + 1][1] - coords[i][1])
    return total


def _load_axes(path: Path) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    feats = payload.get("features", [])
    axes: list[dict] = []
    for i, feat in enumerate(feats):
        geom = feat.get("geometry", {})
        if geom.get("type") != "LineString":
            continue
        coords = [(float(x), float(y)) for x, y in geom.get("coordinates", [])]
        if len(coords) < 2:
            continue
        axes.append(
            {
                "id": feat.get("properties", {}).get("id", f"alt_{i+1}"),
                "name": feat.get("properties", {}).get("name", f"Alternativa {i+1}"),
                "coords": coords,
            }
        )
    if not axes:
        raise ValueError("Nenhuma alternativa LineString válida encontrada.")
    return axes


def main() -> None:
    args = parse_args()
    axes = _load_axes(args.axes_geojson)

    profiles = []
    for axis in axes:
        length = _line_length(axis["coords"])
        stations = []
        d = 0.0
        while d <= length + 1e-9:
            elev = args.start_elevation + (args.grade_percent / 100.0) * d
            stations.append({"station_m": round(d, 3), "design_elevation_m": round(elev, 3)})
            d += args.station_step_m

        profiles.append({"id": axis["id"], "name": axis["name"], "length_m": round(length, 3), "stations": stations})

    out = {
        "station_step_m": args.station_step_m,
        "start_elevation": args.start_elevation,
        "grade_percent": args.grade_percent,
        "profiles": profiles,
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Perfil de projeto salvo em: {args.out}")


if __name__ == "__main__":
    main()
