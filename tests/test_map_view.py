import folium
import pytest

from src.rewards import RewardEdge
from src.solver import solve
from src.ui.map_view import (
    create_base_map,
    edges_geojson,
    graph_center,
    reward_feature_group,
    route_feature_group,
)
from tests.test_solver import grid_graph, reward


def _polylines(fg) -> list[folium.PolyLine]:
    return [c for c in fg._children.values() if isinstance(c, folium.PolyLine)]


def _markers(fg) -> list[folium.Marker]:
    return [c for c in fg._children.values() if type(c) is folium.Marker]


def test_graph_center(undirected_graph):
    lat, lng = graph_center(undirected_graph)
    assert lat == pytest.approx(34.9905)
    assert lng == pytest.approx(135.7585)


class TestBaseMap:
    def test_without_overlay_has_no_geojson(self, undirected_graph):
        m = create_base_map(undirected_graph)
        assert not any(
            isinstance(c, folium.GeoJson) for c in m._children.values()
        )

    def test_with_overlay_adds_geojson(self, undirected_graph):
        m = create_base_map(undirected_graph, selectable_overlay=True)
        assert any(isinstance(c, folium.GeoJson) for c in m._children.values())

    def test_edges_geojson_covers_all_edges(self, undirected_graph):
        gj = edges_geojson(undirected_graph)
        assert gj["type"] == "FeatureCollection"
        assert len(gj["features"]) == undirected_graph.number_of_edges()
        # 座標は (経度, 緯度) 順
        lng, lat = gj["features"][0]["geometry"]["coordinates"][0]
        assert 135 < lng < 136 and 34 < lat < 35


class TestRewardFeatureGroup:
    def test_draws_reward_edges_red_with_tooltip(self, undirected_graph):
        rewards = [
            RewardEdge(u=1, v=2, key=0, reward=50, road_name="四条通"),
            RewardEdge(u=2, v=3, key=0, reward=30),
        ]
        fg = reward_feature_group(undirected_graph, rewards)

        lines = _polylines(fg)
        assert len(lines) == 2
        assert all(line.options["color"] == "red" for line in lines)
        tooltips = " ".join(
            t.text
            for line in lines
            for t in line._children.values()
            if isinstance(t, folium.Tooltip)
        )
        assert "四条通 / 報酬: 50" in tooltips
        assert "報酬: 30" in tooltips

    def test_preview_edge_is_blue(self, undirected_graph):
        fg = reward_feature_group(undirected_graph, [], preview_edge=(1, 4, 0))
        lines = _polylines(fg)
        assert len(lines) == 1
        assert lines[0].options["color"] == "blue"

    def test_clicked_point_marker(self, undirected_graph):
        fg = reward_feature_group(undirected_graph, [], clicked=(34.9905, 135.7585))
        assert any(
            isinstance(c, folium.CircleMarker) for c in fg._children.values()
        )

    def test_empty(self, undirected_graph):
        fg = reward_feature_group(undirected_graph, [])
        assert _polylines(fg) == []


class TestRouteFeatureGroup:
    @pytest.fixture
    def searched(self):
        G = grid_graph(5)
        rewards = [reward(0, 1, 10), reward(6, 11, 25), reward(17, 18, 40)]
        cands = solve(G, rewards, s=0, t=24, limit=1400.0, k=3)
        return G, rewards, cands

    def test_markers_for_start_and_end(self, searched):
        G, rewards, cands = searched
        fg = route_feature_group(G, [], s=0, t=24)
        assert len(_markers(fg)) == 2

    def test_visible_selects_single_candidate(self, searched):
        G, rewards, cands = searched
        n_rewards = len(rewards)

        fg_one = route_feature_group(G, rewards, candidates=cands, visible={1})
        lines = _polylines(fg_one)
        # 報酬エッジ + 選択した候補1本のみ
        assert len(lines) == n_rewards + 1
        route_lines = [l for l in lines if l.options["color"] != "red"]
        assert len(route_lines) == 1
        assert route_lines[0].options["color"] == "#2ca02c"  # 候補2の色

    def test_visible_none_draws_all(self, searched):
        G, rewards, cands = searched
        fg_all = route_feature_group(G, rewards, candidates=cands, visible=None)
        route_lines = [
            l for l in _polylines(fg_all) if l.options["color"] != "red"
        ]
        assert len(route_lines) == len(cands)
