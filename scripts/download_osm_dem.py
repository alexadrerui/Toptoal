#!/usr/bin/env python3
"""Baixa OSM + DEM a partir de polígono GeoJSON desenhado no mapa.

Ações principais:
1) Filtrar OSM pelo próprio polígono (Overpass `poly:`) para rios/lagos/construções.
2) Baixar DEM por bbox e recortar o raster para o polígono (economia de memória).
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
OPENTOPO_URL = "https://portal.opentopography.org/API/globaldem"


SUPPORTED_DEM_RESOLUTIONS = {
    "15": "COP30",
    "30": "COP30",
    "90": "SRTMGL3",
}


def _resolve_dem_type(dem_type: str | None, dem_resolution_m: int | None) -> tuple[str, int | None]:
    if dem_resolution_m is not None:
        if str(dem_resolution_m) not in SUPPORTED_DEM_RESOLUTIONS:
            raise ValueError("--dem-resolution-m deve ser um destes valores: 15, 30, 90")
        return SUPPORTED_DEM_RESOLUTIONS[str(dem_resolution_m)], int(dem_resolution_m)

    chosen = (dem_type or "COP30").strip().upper()
    aliases = {
        "COP30": ("COP30", 30),
        "SRTMGL1": ("SRTMGL1", 30),
        "SRTMGL3": ("SRTMGL3", 90),
    }
    if chosen in aliases:
        return aliases[chosen]
    return chosen, None

try:
    import rasterio
    from rasterio.mask import mask
except ImportError:  # pragma: no cover
    rasterio = None
    mask = None


def _load_geojson_polygon(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fp:
        payload = json.load(fp)

    if payload.get("type") == "FeatureCollection":
        features = payload.get("features", [])
        if not features:
            raise ValueError("GeoJSON FeatureCollection sem features.")
        geometry = features[0].get("geometry")
    elif payload.get("type") == "Feature":
        geometry = payload.get("geometry")
    else:
        geometry = payload

    if not geometry or geometry.get("type") not in {"Polygon", "MultiPolygon"}:
        raise ValueError("GeoJSON deve conter Polygon ou MultiPolygon.")

    return geometry


def _geometry_bounds(geometry: dict[str, Any]) -> tuple[float, float, float, float]:
    coords: list[tuple[float, float]] = []

    if geometry["type"] == "Polygon":
        for ring in geometry["coordinates"]:
            coords.extend((float(lon), float(lat)) for lon, lat in ring)
    else:
        for polygon in geometry["coordinates"]:
            for ring in polygon:
                coords.extend((float(lon), float(lat)) for lon, lat in ring)

    lons = [lon for lon, _ in coords]
    lats = [lat for _, lat in coords]
    return min(lons), min(lats), max(lons), max(lats)


def _overpass_poly_string(geometry: dict[str, Any]) -> str:
    if geometry["type"] == "Polygon":
        ring = geometry["coordinates"][0]
    else:
        ring = geometry["coordinates"][0][0]

    return " ".join(f"{lat} {lon}" for lon, lat in ring)


def _build_overpass_poly_query(geometry: dict[str, Any], timeout: int = 180) -> str:
    poly = _overpass_poly_string(geometry)
    return f"""
[out:json][timeout:{timeout}];
(
  way["building"](poly:"{poly}");
  relation["building"](poly:"{poly}");

  way["waterway"](poly:"{poly}");
  relation["waterway"](poly:"{poly}");
  way["natural"="water"](poly:"{poly}");
  relation["natural"="water"](poly:"{poly}");
  way["landuse"="reservoir"](poly:"{poly}");
  relation["landuse"="reservoir"](poly:"{poly}");
);
out tags geom;
""".strip()


def fetch_osm_raw(geometry: dict[str, Any], timeout: int = 180) -> dict[str, Any]:
    query = _build_overpass_poly_query(geometry, timeout=timeout)
    request = Request(OVERPASS_URL, data=query.encode("utf-8"), method="POST")
    try:
        with urlopen(request, timeout=timeout) as response:
            if response.status != 200:
                raise RuntimeError(f"Overpass retornou status {response.status}")
            return json.loads(response.read().decode("utf-8"))
    except URLError as exc:
        raise RuntimeError(f"Falha ao consultar Overpass API: {exc}") from exc


def _elements_to_geojson(elements: list[dict[str, Any]]) -> dict[str, Any]:
    features: list[dict[str, Any]] = []
    for el in elements:
        geom = el.get("geometry")
        if not geom:
            continue

        coords = [[pt["lon"], pt["lat"]] for pt in geom]
        if len(coords) < 2:
            continue

        geometry = {
            "type": "Polygon" if coords[0] == coords[-1] else "LineString",
            "coordinates": [coords] if coords[0] == coords[-1] else coords,
        }
        features.append(
            {
                "type": "Feature",
                "properties": {
                    "id": f"{el.get('type', 'element')}/{el.get('id')}",
                    **el.get("tags", {}),
                },
                "geometry": geometry,
            }
        )
    return {"type": "FeatureCollection", "features": features}


def download_dem_bbox(
    bbox: tuple[float, float, float, float],
    output_file: Path,
    dem_type: str,
    api_key: str,
    timeout: int = 300,
) -> None:
    west, south, east, north = bbox
    params = {
        "demtype": dem_type,
        "south": south,
        "north": north,
        "west": west,
        "east": east,
        "outputFormat": "GTiff",
        "API_Key": api_key,
    }
    request = Request(f"{OPENTOPO_URL}?{urlencode(params)}", method="GET")
    try:
        with urlopen(request, timeout=timeout) as response:
            if response.status != 200:
                raise RuntimeError(f"OpenTopography retornou status {response.status}")
            output_file.write_bytes(response.read())
    except URLError as exc:
        raise RuntimeError(f"Falha ao baixar DEM do OpenTopography: {exc}") from exc


def clip_dem_to_polygon(input_tif: Path, geometry: dict[str, Any], output_tif: Path) -> None:
    if rasterio is None or mask is None:
        raise RuntimeError("rasterio não está instalado. Instale para recortar o DEM.")

    with rasterio.open(input_tif) as src:
        out_image, out_transform = mask(src, [geometry], crop=True)
        out_meta = src.meta.copy()

    out_meta.update(
        {
            "driver": "GTiff",
            "height": out_image.shape[1],
            "width": out_image.shape[2],
            "transform": out_transform,
        }
    )

    with rasterio.open(output_tif, "w", **out_meta) as dst:
        dst.write(out_image)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Baixa OSM + DEM por polígono GeoJSON.")
    parser.add_argument("--polygon", required=True, type=Path, help="GeoJSON (Polygon/MultiPolygon).")
    parser.add_argument("--out-dir", type=Path, default=Path("data/raw"), help="Diretório base de saída.")
    parser.add_argument("--dem-type", default="COP30", help="DEM OpenTopography (ex.: COP30, SRTMGL1, SRTMGL3).")
    parser.add_argument("--dem-resolution-m", type=int, default=None, help="Escolha por resolução alvo: 15, 30 ou 90 metros.")
    parser.add_argument("--opentopo-api-key", default=None, help="API key do OpenTopography.")
    parser.add_argument("--skip-dem", action="store_true", help="Baixa apenas OSM.")
    parser.add_argument("--skip-osm", action="store_true", help="Baixa apenas DEM.")
    parser.add_argument("--skip-dem-clip", action="store_true", help="Baixa DEM por bbox sem recorte por polígono.")
    parser.add_argument("--dry-run", action="store_true", help="Mostra bbox/query sem chamadas de rede.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    osm_dir = args.out_dir / "osm"
    dem_dir = args.out_dir / "dem"
    meta_dir = args.out_dir / "metadata"
    for directory in (osm_dir, dem_dir, meta_dir):
        directory.mkdir(parents=True, exist_ok=True)

    geometry = _load_geojson_polygon(args.polygon)
    bbox = _geometry_bounds(geometry)
    query_preview = _build_overpass_poly_query(geometry)

    resolved_dem_type, resolved_resolution = _resolve_dem_type(args.dem_type, args.dem_resolution_m)

    metadata = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "polygon_source": str(args.polygon),
        "bbox": {"west": bbox[0], "south": bbox[1], "east": bbox[2], "north": bbox[3]},
        "dem_type": resolved_dem_type,
        "dem_resolution_m": resolved_resolution,
        "supported_dem_resolutions_m": [15, 30, 90],
    }
    _write_json(meta_dir / "request_metadata.json", metadata)
    _write_json(meta_dir / "input_polygon.geojson", {"type": "Feature", "properties": {}, "geometry": geometry})

    if args.dry_run:
        print("[dry-run] BBOX:", metadata["bbox"])
        print("[dry-run] Overpass poly query (início):")
        print("\n".join(query_preview.splitlines()[:12]))
        return

    if args.skip_osm:
        print("[1/2] OSM ignorado (--skip-osm).")
    else:
        print("[1/2] Filtrando OSM pelo polígono desenhado...")
        osm_raw = fetch_osm_raw(geometry)
        _write_json(osm_dir / "osm_features_raw.json", osm_raw)
        _write_json(osm_dir / "osm_features.geojson", _elements_to_geojson(osm_raw.get("elements", [])))

    if args.skip_dem:
        print("[2/2] DEM ignorado (--skip-dem).")
        return

    api_key = args.opentopo_api_key or os.getenv("OPENTOPO_API_KEY")
    if not api_key:
        raise ValueError("Informe --opentopo-api-key (ou OPENTOPO_API_KEY), ou use --skip-dem.")

    dem_bbox = dem_dir / "dem_raw_bbox.tif"
    dem_clip = dem_dir / "dem_clipped_polygon.tif"

    print("[2/2] Baixando DEM por bbox...")
    download_dem_bbox(bbox, dem_bbox, resolved_dem_type, api_key)

    if args.skip_dem_clip:
        print("Recorte de DEM ignorado (--skip-dem-clip).")
        return

    print("Recortando DEM para o polígono...")
    clip_dem_to_polygon(dem_bbox, geometry, dem_clip)
    print("Concluído. Dados em:", args.out_dir)


if __name__ == "__main__":
    main()
