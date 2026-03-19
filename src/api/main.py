"""FastAPI mínimo para pipeline de traçado viário."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from scripts import download_osm_dem
from scripts import run_astar_graph

app = FastAPI(title="Toptoal Backend API", version="0.1.0")


class IngestDryRunRequest(BaseModel):
    polygon_path: str = Field(..., description="Caminho para GeoJSON Polygon/MultiPolygon.")
    dem_type: str = "COP30"
    dem_resolution_m: int | None = Field(default=None, description="15, 30 ou 90.")


class RouteGraphRequest(BaseModel):
    grid_model_path: str
    start_lon: float
    start_lat: float
    end_lon: float
    end_lat: float


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/ingest/dry-run")
def ingest_dry_run(payload: IngestDryRunRequest) -> dict:
    polygon_path = Path(payload.polygon_path)
    if not polygon_path.exists():
        raise HTTPException(status_code=404, detail=f"Polygon não encontrado: {polygon_path}")

    try:
        geometry = download_osm_dem._load_geojson_polygon(polygon_path)
        bbox = download_osm_dem._geometry_bounds(geometry)
        query = download_osm_dem._build_overpass_poly_query(geometry)
        dem_type, dem_resolution = download_osm_dem._resolve_dem_type(payload.dem_type, payload.dem_resolution_m)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "polygon_source": str(polygon_path),
        "bbox": {"west": bbox[0], "south": bbox[1], "east": bbox[2], "north": bbox[3]},
        "dem": {
            "requested_dem_type": payload.dem_type,
            "requested_resolution_m": payload.dem_resolution_m,
            "resolved_dem_type": dem_type,
            "resolved_resolution_m": dem_resolution,
            "supported_resolutions_m": [15, 30, 90],
        },
        "overpass_query_preview": query.splitlines()[:12],
    }


@app.post("/route/graph")
def route_graph(payload: RouteGraphRequest) -> dict:
    grid_path = Path(payload.grid_model_path)
    if not grid_path.exists():
        raise HTTPException(status_code=404, detail=f"Grid model não encontrado: {grid_path}")

    try:
        model = json.loads(grid_path.read_text(encoding="utf-8"))
        nodes = model.get("cells", [])
        edges = model.get("edges", [])
        start_id = run_astar_graph._nearest_node_id(nodes, payload.start_lon, payload.start_lat)
        end_id = run_astar_graph._nearest_node_id(nodes, payload.end_lon, payload.end_lat)
        path_ids, total_cost = run_astar_graph.astar_graph(nodes, edges, start_id, end_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    node_map = {int(n["id"]): n for n in nodes}
    coords = [[float(node_map[n]["x"]), float(node_map[n]["y"])] for n in path_ids]
    return {
        "start": [payload.start_lon, payload.start_lat],
        "end": [payload.end_lon, payload.end_lat],
        "start_node": start_id,
        "end_node": end_id,
        "path_node_count": len(path_ids),
        "path_node_ids": path_ids,
        "path_coords": coords,
        "total_cost": float(total_cost),
    }
