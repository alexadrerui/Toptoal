#!/usr/bin/env python3
"""Executa A* sobre grafo de arestas exportado pelo grid_model.json."""

from __future__ import annotations

import argparse
import heapq
import json
import math
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Calcula rota A* usando nodes+edges do grid_model.json.")
    parser.add_argument("--grid-model", required=True, type=Path, help="Arquivo grid_model.json com cells + edges.")
    parser.add_argument("--start-lon", required=True, type=float)
    parser.add_argument("--start-lat", required=True, type=float)
    parser.add_argument("--end-lon", required=True, type=float)
    parser.add_argument("--end-lat", required=True, type=float)
    parser.add_argument("--out", type=Path, default=Path("outputs/reports/astar_graph_path.json"))
    return parser.parse_args()


def _euclidean(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _nearest_node_id(nodes: list[dict[str, Any]], lon: float, lat: float) -> int:
    best_id = -1
    best_dist = float("inf")
    for n in nodes:
        d = _euclidean((lon, lat), (float(n["x"]), float(n["y"])))
        if d < best_dist:
            best_dist = d
            best_id = int(n["id"])
    if best_id < 0:
        raise RuntimeError("Não foi possível encontrar nó mais próximo para origem/destino.")
    return best_id


def astar_graph(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    start_id: int,
    goal_id: int,
) -> tuple[list[int], float]:
    pos = {int(n["id"]): (float(n["x"]), float(n["y"])) for n in nodes}
    adj: dict[int, list[tuple[int, float]]] = {nid: [] for nid in pos}

    for e in edges:
        u = int(e["from"])
        v = int(e["to"])
        w = float(e["movement_cost"])
        if u in adj:
            adj[u].append((v, w))

    open_heap: list[tuple[float, int]] = [(0.0, start_id)]
    came_from: dict[int, int] = {}
    g_score: dict[int, float] = {start_id: 0.0}
    closed_set: set[int] = set()

    while open_heap:
        _, current = heapq.heappop(open_heap)

        if current in closed_set:
            continue

        if current == goal_id:
            path = [current]
            while current in came_from:
                current = came_from[current]
                path.append(current)
            path.reverse()
            return path, g_score[goal_id]

        closed_set.add(current)

        for neigh, weight in adj.get(current, []):
            if neigh in closed_set:
                continue
            tentative = g_score[current] + weight
            if tentative < g_score.get(neigh, float("inf")):
                came_from[neigh] = current
                g_score[neigh] = tentative
                h = _euclidean(pos[neigh], pos[goal_id])
                heapq.heappush(open_heap, (tentative + h, neigh))

    raise RuntimeError("Não foi possível encontrar rota no grafo.")


def main() -> None:
    args = parse_args()
    model = json.loads(args.grid_model.read_text(encoding="utf-8"))
    nodes = model.get("cells", [])
    edges = model.get("edges", [])

    start_id = _nearest_node_id(nodes, args.start_lon, args.start_lat)
    goal_id = _nearest_node_id(nodes, args.end_lon, args.end_lat)

    path_ids, total_cost = astar_graph(nodes, edges, start_id, goal_id)
    node_map = {int(n["id"]): n for n in nodes}
    coords = [[float(node_map[n]["x"]), float(node_map[n]["y"])] for n in path_ids]
    base_costs = [float(node_map[n].get("base_cost", 1.0)) for n in path_ids]

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(
            {
                "start": [args.start_lon, args.start_lat],
                "end": [args.end_lon, args.end_lat],
                "start_node": start_id,
                "end_node": goal_id,
                "path_node_count": len(path_ids),
                "path_node_ids": path_ids,
                "path_coords": coords,
                "path_base_costs": base_costs,
                "total_cost": total_cost,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"Rota A* (grafo) salva em: {args.out} (custo total: {total_cost:.2f})")


if __name__ == "__main__":
    main()
