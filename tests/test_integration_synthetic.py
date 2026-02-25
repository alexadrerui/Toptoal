import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts import build_cost_surface
from scripts import build_grid_model


@unittest.skipIf(build_cost_surface.np is None or build_grid_model.rasterio is None, "deps geoespaciais indisponíveis")
class TestSyntheticPipeline(unittest.TestCase):
    def test_pipeline_20x20(self):
        np = build_cost_surface.np
        rasterio = build_grid_model.rasterio
        from rasterio.transform import from_origin

        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            dem = td / "dem.tif"
            osm = td / "osm.geojson"
            cost = td / "cost.tif"
            cost_report = td / "cost_report.json"
            grid = td / "grid.json"
            path = td / "path.json"
            qaqc = td / "qaqc.json"

            arr = np.zeros((20, 20), dtype=np.float32)
            for r in range(20):
                arr[r, :] = r

            profile = {
                "driver": "GTiff",
                "height": 20,
                "width": 20,
                "count": 1,
                "dtype": "float32",
                "crs": "EPSG:3857",
                "transform": from_origin(0, 20, 1, 1),
                "nodata": -9999.0,
            }
            with rasterio.open(dem, "w", **profile) as dst:
                dst.write(arr, 1)

            osm_payload = {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"highway": "residential"},
                        "geometry": {"type": "LineString", "coordinates": [[1, 19], [18, 2]]},
                    },
                    {
                        "type": "Feature",
                        "properties": {"natural": "water"},
                        "geometry": {"type": "Polygon", "coordinates": [[[8, 12], [12, 12], [12, 8], [8, 8], [8, 12]]]},
                    },
                    {
                        "type": "Feature",
                        "properties": {"building": "yes"},
                        "geometry": {"type": "Polygon", "coordinates": [[[3, 17], [5, 17], [5, 15], [3, 15], [3, 17]]]},
                    },
                ],
            }
            osm.write_text(json.dumps(osm_payload), encoding="utf-8")

            subprocess.run([
                "python", "scripts/qaqc_inputs.py",
                "--dem", str(dem),
                "--osm-geojson", str(osm),
                "--out-report", str(qaqc),
            ], check=True)

            subprocess.run([
                "python", "scripts/build_cost_surface.py",
                "--dem", str(dem),
                "--osm-geojson", str(osm),
                "--qaqc-report", str(qaqc),
                "--cost-out", str(cost),
                "--report-out", str(cost_report),
            ], check=True)

            subprocess.run([
                "python", "scripts/build_grid_model.py",
                "--dem", str(dem),
                "--cost-raster", str(cost),
                "--out", str(grid),
                "--stride", "1",
            ], check=True)

            subprocess.run([
                "python", "scripts/run_astar_graph.py",
                "--grid-model", str(grid),
                "--start-lon", "1",
                "--start-lat", "19",
                "--end-lon", "18",
                "--end-lat", "2",
                "--out", str(path),
            ], check=True)

            out = json.loads(path.read_text(encoding="utf-8"))
            self.assertGreater(out.get("path_node_count", 0), 0)
            self.assertGreater(out.get("total_cost", 0.0), 0.0)


if __name__ == "__main__":
    unittest.main()
