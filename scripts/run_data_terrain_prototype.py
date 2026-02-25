#!/usr/bin/env python3
"""Orquestra protótipo da etapa Dados e Terreno para corredor ~50 km."""

from __future__ import annotations

import argparse
import json
import math
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Executa protótipo Dados e Terreno em corredor ~50 km.")
    parser.add_argument(
        "--polygon",
        type=Path,
        default=Path("data/external/pilot_corridor_50km_sp.geojson"),
        help="Polígono GeoJSON da área piloto.",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("data/raw/prototype_50km"),
        help="Diretório de saída da ingestão OSM+DEM.",
    )
    parser.add_argument("--dem-type", type=str, default="COP30")
    parser.add_argument("--stride", type=int, default=2, help="Stride da grade de processamento.")
    parser.add_argument(
        "--assumed-dem-resolution-m",
        type=float,
        default=30.0,
        help="Resolução DEM assumida para estimativa da grade (metros).",
    )
    parser.add_argument(
        "--run-download",
        action="store_true",
        help="Executa download real (sem --dry-run).",
    )
    parser.add_argument(
        "--report-out",
        type=Path,
        default=Path("outputs/reports/data_terrain_prototype_50km.json"),
    )
    return parser.parse_args()


def _extract_bbox(polygon_geojson: Path) -> tuple[float, float, float, float]:
    payload = json.loads(polygon_geojson.read_text(encoding="utf-8"))
    features = payload.get("features", [])
    if not features:
        raise ValueError("GeoJSON sem features.")
    geom = features[0].get("geometry", {})
    if geom.get("type") != "Polygon":
        raise ValueError("Protótipo espera Polygon no GeoJSON.")
    coords = geom.get("coordinates", [[]])[0]
    xs = [float(pt[0]) for pt in coords]
    ys = [float(pt[1]) for pt in coords]
    return min(xs), min(ys), max(xs), max(ys)


def _haversine_km(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    r = 6371.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    dp = math.radians(lat2 - lat1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _run_ingestion(polygon: Path, out_dir: Path, dem_type: str, run_download: bool) -> dict[str, str]:
    cmd = [
        "python",
        "scripts/download_osm_dem.py",
        "--polygon",
        str(polygon),
        "--out-dir",
        str(out_dir),
        "--dem-type",
        dem_type,
    ]
    mode = "download"
    if not run_download:
        cmd.append("--dry-run")
        mode = "dry-run"

    proc = subprocess.run(cmd, capture_output=True, text=True)
    return {
        "mode": mode,
        "command": " ".join(cmd),
        "return_code": str(proc.returncode),
        "stdout": proc.stdout.strip(),
        "stderr": proc.stderr.strip(),
    }


def main() -> None:
    args = parse_args()
    if args.stride <= 0:
        raise ValueError("--stride deve ser > 0")

    west, south, east, north = _extract_bbox(args.polygon)
    mid_lat = (south + north) / 2.0
    length_km = _haversine_km(west, mid_lat, east, mid_lat)
    width_km = _haversine_km(west, south, west, north)

    effective_grid_m = args.assumed_dem_resolution_m * args.stride
    length_cells = max(1, int((length_km * 1000.0) / effective_grid_m))
    width_cells = max(1, int((width_km * 1000.0) / effective_grid_m))

    ingestion = _run_ingestion(args.polygon, args.out_dir, args.dem_type, args.run_download)

    report = {
        "prototype": "dados_terreno_50km",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "polygon": str(args.polygon),
        "bbox": {"west": west, "south": south, "east": east, "north": north},
        "estimated_corridor": {
            "length_km": length_km,
            "width_km": width_km,
        },
        "processing_grid": {
            "stride": args.stride,
            "assumed_dem_resolution_m": args.assumed_dem_resolution_m,
            "effective_grid_size_m": effective_grid_m,
            "estimated_cells_length": length_cells,
            "estimated_cells_width": width_cells,
            "estimated_cell_count": length_cells * width_cells,
        },
        "ingestion": ingestion,
    }

    args.report_out.parent.mkdir(parents=True, exist_ok=True)
    args.report_out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Protótipo Dados e Terreno registrado em: {args.report_out}")


if __name__ == "__main__":
    main()
