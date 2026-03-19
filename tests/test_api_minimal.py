import json
import tempfile
import unittest
from pathlib import Path

try:
    from fastapi.testclient import TestClient
except ImportError:  # pragma: no cover
    TestClient = None

if TestClient is not None:
    from src.api.main import app


@unittest.skipIf(TestClient is None, "fastapi/testclient indisponível")
class TestApiMinimal(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_health(self):
        resp = self.client.get("/health")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json().get("status"), "ok")

    def test_ingest_dry_run(self):
        with tempfile.TemporaryDirectory() as td:
            poly = Path(td) / "poly.geojson"
            poly.write_text(
                json.dumps(
                    {
                        "type": "Feature",
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [[[-46.8, -23.6], [-46.7, -23.6], [-46.7, -23.5], [-46.8, -23.5], [-46.8, -23.6]]],
                        },
                        "properties": {},
                    }
                ),
                encoding="utf-8",
            )

            resp = self.client.post(
                "/ingest/dry-run",
                json={"polygon_path": str(poly), "dem_resolution_m": 30},
            )
            self.assertEqual(resp.status_code, 200)
            body = resp.json()
            self.assertIn("bbox", body)
            self.assertEqual(body["dem"]["resolved_resolution_m"], 30)

    def test_route_graph(self):
        with tempfile.TemporaryDirectory() as td:
            grid = Path(td) / "grid.json"
            model = {
                "cells": [
                    {"id": 0, "x": 0.0, "y": 0.0},
                    {"id": 1, "x": 1.0, "y": 0.0},
                    {"id": 2, "x": 2.0, "y": 0.0},
                ],
                "edges": [
                    {"from": 0, "to": 1, "movement_cost": 1.0},
                    {"from": 1, "to": 2, "movement_cost": 1.0},
                ],
            }
            grid.write_text(json.dumps(model), encoding="utf-8")

            resp = self.client.post(
                "/route/graph",
                json={
                    "grid_model_path": str(grid),
                    "start_lon": 0.0,
                    "start_lat": 0.0,
                    "end_lon": 2.0,
                    "end_lat": 0.0,
                },
            )
            self.assertEqual(resp.status_code, 200)
            body = resp.json()
            self.assertEqual(body["path_node_ids"], [0, 1, 2])
            self.assertAlmostEqual(body["total_cost"], 2.0)


if __name__ == "__main__":
    unittest.main()
