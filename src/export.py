"""探索結果のGeoJSONエクスポート（SPEC.md §6.2）。

候補経路を LineString（properties: reward, length 等）の FeatureCollection
として output/ に保存する。座標順は GeoJSON 仕様どおり (経度, 緯度)。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import networkx as nx

from src.route import RouteCandidate, route_latlngs


def candidates_to_geojson(
    G: nx.MultiGraph, candidates: list[RouteCandidate]
) -> dict:
    features = []
    for i, c in enumerate(candidates):
        coords = [[lng, lat] for lat, lng in route_latlngs(G, c.nodes, c.edges)]
        if len(coords) == 1:  # s=t の直行など。LineString は2点以上必要
            coords = coords * 2
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": coords},
                "properties": {
                    "candidate": i + 1,
                    "reward": c.reward,
                    "length": round(c.length, 1),
                    "collected_edges": [list(r.edge_id) for r in c.collected],
                },
            }
        )
    return {"type": "FeatureCollection", "features": features}


def export_candidates(
    G: nx.MultiGraph,
    candidates: list[RouteCandidate],
    output_dir: str | Path,
    basename: str | None = None,
) -> Path:
    """候補経路を output_dir に GeoJSON として保存し、保存先パスを返す。"""
    if not candidates:
        raise ValueError("エクスポートする候補経路がありません")
    name = basename or f"routes_{datetime.now():%Y%m%d_%H%M%S}"
    path = Path(output_dir) / f"{name}.geojson"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(candidates_to_geojson(G, candidates), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path
