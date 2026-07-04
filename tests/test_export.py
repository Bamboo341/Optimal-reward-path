"""GeoJSONエクスポートのテスト（SPEC.md §6.2）。"""

import json

import pytest

from src.export import candidates_to_geojson, export_candidates
from src.solver import solve
from tests.test_solver import grid_graph, line_graph, reward


@pytest.fixture
def grid_candidates():
    G = grid_graph(3)
    cands = solve(G, [reward(0, 1, 3), reward(3, 6, 7)], s=0, t=8, limit=600.0, k=3)
    return G, cands


class TestCandidatesToGeojson:
    def test_feature_collection_structure(self, grid_candidates):
        G, cands = grid_candidates
        gj = candidates_to_geojson(G, cands)

        assert gj["type"] == "FeatureCollection"
        assert len(gj["features"]) == len(cands)
        for i, (feat, cand) in enumerate(zip(gj["features"], cands)):
            assert feat["type"] == "Feature"
            assert feat["geometry"]["type"] == "LineString"
            assert len(feat["geometry"]["coordinates"]) >= 2
            props = feat["properties"]
            assert props["candidate"] == i + 1
            assert props["reward"] == cand.reward
            assert props["length"] == pytest.approx(cand.length, abs=0.1)

    def test_coordinates_are_lng_lat(self, grid_candidates):
        G, cands = grid_candidates
        gj = candidates_to_geojson(G, cands)
        first = gj["features"][0]["geometry"]["coordinates"][0]
        # 経路の始点 = 出発ノード0。GeoJSON は (経度, 緯度) 順
        assert first == [G.nodes[0]["x"], G.nodes[0]["y"]]

    def test_degenerate_route_s_equals_t(self):
        # s=t・報酬なし → ノード1点の経路でも有効な LineString を出力する
        G = line_graph(3)
        cands = solve(G, [], s=0, t=0, limit=100.0)
        gj = candidates_to_geojson(G, cands)
        coords = gj["features"][0]["geometry"]["coordinates"]
        assert len(coords) >= 2


class TestExportCandidates:
    def test_writes_file_and_returns_path(self, grid_candidates, tmp_path):
        G, cands = grid_candidates
        path = export_candidates(G, cands, tmp_path, basename="test_routes")

        assert path == tmp_path / "test_routes.geojson"
        gj = json.loads(path.read_text(encoding="utf-8"))
        assert gj["type"] == "FeatureCollection"
        assert len(gj["features"]) == len(cands)

    def test_default_basename_is_timestamped(self, grid_candidates, tmp_path):
        G, cands = grid_candidates
        path = export_candidates(G, cands, tmp_path)
        assert path.name.startswith("routes_")
        assert path.suffix == ".geojson"
        assert path.exists()

    def test_creates_output_dir(self, grid_candidates, tmp_path):
        G, cands = grid_candidates
        path = export_candidates(G, cands, tmp_path / "nested" / "out")
        assert path.exists()

    def test_empty_candidates_raise(self, tmp_path):
        G = grid_graph(3)
        with pytest.raises(ValueError, match="候補経路がありません"):
            export_candidates(G, [], tmp_path)
