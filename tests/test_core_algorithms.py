import json
import tempfile
import unittest
from pathlib import Path

from scripts import build_cost_surface
from scripts import build_grid_model
from scripts import evaluate_earthwork_alternatives
from scripts import run_astar_graph
from scripts import sweep_scenarios


class TestCoreAlgorithms(unittest.TestCase):
    @unittest.skipIf(build_cost_surface.np is None, "numpy indisponível")
    def test_compute_slope_percent_flat(self):
        np = build_cost_surface.np
        class T:
            a = 5.0
            e = -5.0
        dem = np.array([[10.0, 10.0], [10.0, 10.0]], dtype=np.float32)
        slope = build_cost_surface._compute_slope_percent(dem, T)
        self.assertTrue(np.allclose(slope, 0.0))

    def test_astar_graph_minimal(self):
        nodes = [
            {"id": 0, "x": 0.0, "y": 0.0},
            {"id": 1, "x": 1.0, "y": 0.0},
            {"id": 2, "x": 2.0, "y": 0.0},
        ]
        edges = [
            {"from": 0, "to": 1, "movement_cost": 1.0},
            {"from": 1, "to": 2, "movement_cost": 1.0},
        ]
        path, total = run_astar_graph.astar_graph(nodes, edges, 0, 2)
        self.assertEqual(path, [0, 1, 2])
        self.assertAlmostEqual(total, 2.0)


    def test_weighted_multiobjective_score(self):
        weights = {
            "route_total_cost": 0.5,
            "mass_balance_imbalance_index": 0.3,
            "water_crossing_length_m": 0.2,
        }
        score = sweep_scenarios._weighted_score(0.2, 0.4, 0.6, weights)
        self.assertAlmostEqual(score, 0.34)

    def test_rank_earthwork(self):
        ev = [
            {"id": "a", "mass_balance_imbalance_index": 0.20, "estimated_cut_volume_m3": 100, "estimated_fill_volume_m3": 100},
            {"id": "b", "mass_balance_imbalance_index": 0.10, "estimated_cut_volume_m3": 120, "estimated_fill_volume_m3": 120},
        ]
        ranked = evaluate_earthwork_alternatives.rank_alternatives(ev)
        self.assertEqual(ranked[0]["id"], "b")


class TestGridEdges(unittest.TestCase):
    @unittest.skipIf(build_grid_model.rasterio is None or build_cost_surface.np is None, "deps geoespaciais indisponíveis")
    def test_generate_edges(self):
        np = build_cost_surface.np
        rasterio = build_grid_model.rasterio
        from rasterio.transform import from_origin

        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            dem = td / "dem.tif"
            arr = np.ones((3, 3), dtype=np.float32) * 100
            profile = {
                "driver": "GTiff",
                "height": 3,
                "width": 3,
                "count": 1,
                "dtype": "float32",
                "crs": "EPSG:3857",
                "transform": from_origin(0, 3, 1, 1),
                "nodata": -9999.0,
            }
            with rasterio.open(dem, "w", **profile) as dst:
                dst.write(arr, 1)

            model = build_grid_model.build_grid(dem, stride=1, cost_raster_path=None, vertical_penalty_factor=0.05)
            self.assertEqual(model["cell_count"], 9)
            self.assertGreater(model["edge_count"], 0)


if __name__ == "__main__":
    unittest.main()
