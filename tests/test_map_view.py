import folium
import pytest

from src.rewards import RewardEdge
from src.ui.map_view import build_reward_map, edge_latlngs, graph_center


def _polylines(m: folium.Map) -> list[folium.PolyLine]:
    return [c for c in m._children.values() if isinstance(c, folium.PolyLine)]


def test_graph_center(undirected_graph):
    lat, lng = graph_center(undirected_graph)
    assert lat == pytest.approx(34.9905)
    assert lng == pytest.approx(135.7585)


class TestEdgeLatLngs:
    def test_straight_line_without_geometry(self):
        # geometry 属性がないエッジは両端ノードを結ぶ直線
        import networkx as nx

        G = nx.MultiGraph(crs="epsg:4326")
        G.add_node(1, x=135.758, y=34.990)
        G.add_node(2, x=135.759, y=34.990)
        G.add_edge(1, 2, key=0, length=100.0)
        assert edge_latlngs(G, 1, 2, 0) == [(34.990, 135.758), (34.990, 135.759)]

    def test_undirected_conversion_fills_geometry(self, undirected_graph):
        # ox.convert.to_undirected は全エッジに geometry を付与する（向きは元エッジ基準）
        coords = edge_latlngs(undirected_graph, 1, 2, 0)
        assert sorted(coords) == [(34.990, 135.758), (34.990, 135.759)]

    def test_uses_geometry_when_present(self, undirected_graph):
        coords = edge_latlngs(undirected_graph, 3, 4, 0)
        # geometry の (lng, lat) 座標列が (lat, lng) に変換される
        assert len(coords) == 3
        assert coords[0] in [(34.991, 135.759), (34.991, 135.758)]
        assert coords[1] == (34.9912, 135.7585)

    def test_missing_edge_raises(self, undirected_graph):
        with pytest.raises(KeyError):
            edge_latlngs(undirected_graph, 1, 3, 0)


class TestBuildRewardMap:
    def test_draws_reward_edges_red_with_tooltip(self, undirected_graph):
        rewards = [
            RewardEdge(u=1, v=2, key=0, reward=50, road_name="四条通"),
            RewardEdge(u=2, v=3, key=0, reward=30),
        ]
        m = build_reward_map(undirected_graph, rewards)

        lines = _polylines(m)
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
        m = build_reward_map(undirected_graph, [], preview_edge=(1, 4, 0))
        lines = _polylines(m)
        assert len(lines) == 1
        assert lines[0].options["color"] == "blue"

    def test_empty_map_has_no_polylines(self, undirected_graph):
        m = build_reward_map(undirected_graph, [])
        assert _polylines(m) == []
