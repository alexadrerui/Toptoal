#!/usr/bin/env python3
"""Gera um GeoJSON de área piloto a partir de bbox."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Cria GeoJSON poligonal de área piloto por bbox.")
    parser.add_argument("--name", default="pilot_area", help="Nome da área piloto.")
    parser.add_argument("--west", type=float, required=True)
    parser.add_argument("--south", type=float, required=True)
    parser.add_argument("--east", type=float, required=True)
    parser.add_argument("--north", type=float, required=True)
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("data/external/pilot_area.geojson"),
        help="Arquivo de saída GeoJSON.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not (args.west < args.east and args.south < args.north):
        raise ValueError("BBox inválida: esperado west < east e south < north.")

    polygon = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"name": args.name},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [args.west, args.south],
                            [args.east, args.south],
                            [args.east, args.north],
                            [args.west, args.north],
                            [args.west, args.south],
                        ]
                    ],
                },
            }
        ],
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(polygon, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Área piloto salva em: {args.out}")


if __name__ == "__main__":
    main()
