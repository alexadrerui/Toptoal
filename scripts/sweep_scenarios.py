#!/usr/bin/env python3
"""Varredura de cenários de parâmetros com ranking multiobjetivo.

Objetivos considerados:
- custo total da rota,
- índice de equilíbrio de massas,
- extensão em água/ponte (aprox. por células de água no caminho).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from pathlib import Path

DEFAULT_WEIGHTS = {
    "route_total_cost": 1.0,
    "mass_balance_imbalance_index": 1.0,
    "water_crossing_length_m": 1.0,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Executa N cenários e ranqueia alternativas de parâmetros.")
    parser.add_argument("--scenarios", required=True, type=Path, help="JSON com lista de cenários e overrides de custo.")
    parser.add_argument("--dem", required=True, type=Path)
    parser.add_argument("--osm-geojson", required=True, type=Path)
    parser.add_argument("--start-lon", required=True, type=float)
    parser.add_argument("--start-lat", required=True, type=float)
    parser.add_argument("--end-lon", required=True, type=float)
    parser.add_argument("--end-lat", required=True, type=float)
    parser.add_argument("--base-params", type=Path, default=Path("configs/cost_parameters.json"))
    parser.add_argument("--out-report", type=Path, default=Path("outputs/reports/scenario_sweep_report.json"))
    return parser.parse_args()


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _normalize(values: list[float]) -> list[float]:
    if not values:
        return []
    vmin = min(values)
    vmax = max(values)
    if vmax == vmin:
        return [0.0 for _ in values]
    return [(v - vmin) / (vmax - vmin) for v in values]


def _resolve_weights(payload: dict) -> dict[str, float]:
    weights = dict(DEFAULT_WEIGHTS)
    weights.update(payload.get("weights", {}))
    denom = sum(max(0.0, float(v)) for v in weights.values())
    if denom <= 0:
        return dict(DEFAULT_WEIGHTS)
    return {k: max(0.0, float(v)) / denom for k, v in weights.items()}


def _weighted_score(route: float, mass: float, water: float, weights: dict[str, float]) -> float:
    return (
        route * weights["route_total_cost"]
        + mass * weights["mass_balance_imbalance_index"]
        + water * weights["water_crossing_length_m"]
    )


def main() -> None:
    args = parse_args()
    scenarios_payload = _load_json(args.scenarios)
    scenarios = scenarios_payload.get("scenarios", [])
    if not scenarios:
        raise ValueError("Arquivo de cenários vazio.")

    weights = _resolve_weights(scenarios_payload)
    base_params = _load_json(args.base_params)
    results = []

    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)

        for sc in scenarios:
            sid = sc.get("id", "scenario")
            overrides = sc.get("overrides", {})
            params = dict(base_params)
            params.update(overrides)

            params_file = tmpdir / f"{sid}_params.json"
            cost_tif = tmpdir / f"{sid}_cost.tif"
            cost_report = tmpdir / f"{sid}_cost_report.json"
            grid_json = tmpdir / f"{sid}_grid.json"
            graph_report = tmpdir / f"{sid}_graph_path.json"

            params_file.write_text(json.dumps(params, ensure_ascii=False, indent=2), encoding="utf-8")

            subprocess.run(
                [
                    "python",
                    "scripts/build_cost_surface.py",
                    "--dem",
                    str(args.dem),
                    "--osm-geojson",
                    str(args.osm_geojson),
                    "--params",
                    str(params_file),
                    "--cost-out",
                    str(cost_tif),
                    "--report-out",
                    str(cost_report),
                ],
                check=True,
            )

            subprocess.run(
                [
                    "python",
                    "scripts/build_grid_model.py",
                    "--dem",
                    str(args.dem),
                    "--cost-raster",
                    str(cost_tif),
                    "--out",
                    str(grid_json),
                    "--stride",
                    str(sc.get("stride", 15)),
                    "--vertical-penalty-factor",
                    str(sc.get("vertical_penalty_factor", 0.05)),
                ],
                check=True,
            )

            subprocess.run(
                [
                    "python",
                    "scripts/run_astar_graph.py",
                    "--grid-model",
                    str(grid_json),
                    "--start-lon",
                    str(args.start_lon),
                    "--start-lat",
                    str(args.start_lat),
                    "--end-lon",
                    str(args.end_lon),
                    "--end-lat",
                    str(args.end_lat),
                    "--out",
                    str(graph_report),
                ],
                check=True,
            )

            graph = _load_json(graph_report)
            c_report = _load_json(cost_report)
            water_cost = float(params.get("water_cost", 15))
            water_path_cells = sum(1 for c in graph.get("path_base_costs", []) if float(c) >= water_cost)
            water_length_m = water_path_cells * float(params.get("grid_resolution_m", 5))

            results.append(
                {
                    "id": sid,
                    "route_total_cost": float(graph.get("total_cost", 0.0)),
                    "mass_balance_imbalance_index": float(c_report.get("mass_balance", {}).get("mass_balance_imbalance_index", 1.0)),
                    "water_crossing_length_m": water_length_m,
                }
            )

    costs = _normalize([r["route_total_cost"] for r in results])
    masses = _normalize([r["mass_balance_imbalance_index"] for r in results])
    waters = _normalize([r["water_crossing_length_m"] for r in results])

    for i, r in enumerate(results):
        r["multiobjective_score"] = _weighted_score(costs[i], masses[i], waters[i], weights)

    ranked = sorted(results, key=lambda x: x["multiobjective_score"])
    out = {
        "objectives": ["route_total_cost", "mass_balance_imbalance_index", "water_crossing_length_m"],
        "weights": weights,
        "results": results,
        "ranking": [r["id"] for r in ranked],
        "recommended": ranked[0]["id"] if ranked else None,
    }

    args.out_report.parent.mkdir(parents=True, exist_ok=True)
    args.out_report.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Varredura de cenários salva em: {args.out_report}")


if __name__ == "__main__":
    main()
