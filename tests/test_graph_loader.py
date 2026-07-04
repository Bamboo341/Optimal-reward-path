from pathlib import Path

import networkx as nx
import pytest
from conftest import make_synthetic_graph
from shapely.geometry import LineString

from src import graph_loader
from src.graph_loader import (
    GraphLoadError,
    edge_road_name,
    graph_cache_path,
    load_graph,
    nearest_edge,
    place_slug,
    to_undirected,
)


class TestPlaceSlug:
    def test_default_place(self):
        assert place_slug("Shimogyo-ku, Kyoto, Japan") == "shimogyo_ku_kyoto_japan"

    def test_collapses_symbols(self):
        assert place_slug("Kyoto,  Japan!!") == "kyoto_japan"

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            place_slug("、、")


def test_graph_cache_path(tmp_path: Path):
    path = graph_cache_path("Shimogyo-ku, Kyoto, Japan", data_dir=tmp_path)
    assert path == tmp_path / "graph_shimogyo_ku_kyoto_japan.graphml"


class TestToUndirected:
    def test_converts_directed(self):
        G = to_undirected(make_synthetic_graph())
        assert not G.is_directed()
        assert isinstance(G, nx.MultiGraph)
        assert G.number_of_nodes() == 4
        # 双方向2本は往復が統合され、一方通行2本と合わせて無向エッジ4本
        assert G.number_of_edges() == 4
        for u, v in [(1, 2), (2, 3), (3, 4), (1, 4)]:
            assert G.has_edge(u, v)

    def test_undirected_passthrough(self):
        G = nx.MultiGraph(crs="epsg:4326")
        assert to_undirected(G) is G


class TestLoadGraph:
    @pytest.fixture
    def fetch_mock(self, monkeypatch):
        calls = []

        def fake_fetch(place, network_type):
            calls.append((place, network_type))
            return make_synthetic_graph()

        monkeypatch.setattr(graph_loader, "_fetch_graph", fake_fetch)
        return calls

    def test_first_load_fetches_and_caches(self, tmp_path, fetch_mock):
        place = "Shimogyo-ku, Kyoto, Japan"
        G = load_graph(place, data_dir=tmp_path)

        assert len(fetch_mock) == 1
        assert fetch_mock[0] == (place, "all")
        assert graph_cache_path(place, tmp_path).exists()
        assert not G.is_directed()

    def test_second_load_uses_cache(self, tmp_path, fetch_mock):
        place = "Shimogyo-ku, Kyoto, Japan"
        G1 = load_graph(place, data_dir=tmp_path)
        G2 = load_graph(place, data_dir=tmp_path)

        # 2回目は再取得しない
        assert len(fetch_mock) == 1
        assert not G2.is_directed()
        assert set(G2.nodes) == set(G1.nodes)
        assert G2.number_of_edges() == G1.number_of_edges()

    def test_cache_preserves_attributes(self, tmp_path, fetch_mock):
        place = "Test Place"
        load_graph(place, data_dir=tmp_path)
        G = load_graph(place, data_dir=tmp_path)

        lengths = {
            tuple(sorted((u, v))): d["length"] for u, v, d in G.edges(data=True)
        }
        assert lengths == {
            (1, 2): pytest.approx(100.0),
            (2, 3): pytest.approx(150.0),
            (3, 4): pytest.approx(120.0),
            (1, 4): pytest.approx(110.0),
        }
        assert all(isinstance(x, float) for x in lengths.values())
        # geometry 属性も graphml 往復で保持される
        geom = G.get_edge_data(3, 4, 0).get("geometry")
        assert isinstance(geom, LineString)

    def test_fetch_failure_raises_graph_load_error(self, tmp_path, monkeypatch):
        def broken(*args, **kwargs):
            raise OSError("network down")

        monkeypatch.setattr(graph_loader.ox, "graph_from_place", broken)
        with pytest.raises(GraphLoadError, match="取得に失敗"):
            load_graph("Nowhere", data_dir=tmp_path)


class TestNearestEdge:
    def test_finds_clicked_edge(self, undirected_graph):
        # エッジ 1-2（東西の道路）の中点近くをクリック
        assert nearest_edge(undirected_graph, lat=34.9901, lng=135.7585) == (1, 2, 0)
        # エッジ 2-3（南北の道路）の中点近く
        assert nearest_edge(undirected_graph, lat=34.9905, lng=135.7591) == (2, 3, 0)

    def test_returns_normalized_python_ints(self, undirected_graph):
        # エッジ 1-4（西端の南北道路、有向グラフでは 4→1 として追加）の中点近く
        u, v, key = nearest_edge(undirected_graph, lat=34.9905, lng=135.7579)
        assert (u, v, key) == (1, 4, 0)
        assert all(type(x) is int for x in (u, v, key))


class TestEdgeRoadName:
    def test_str_name(self, undirected_graph):
        assert edge_road_name(undirected_graph, 1, 2, 0) == "四条通"

    def test_list_name_joined(self, undirected_graph):
        assert edge_road_name(undirected_graph, 2, 3, 0) == "高倉通・Takakura"

    def test_missing_name_is_empty(self, undirected_graph):
        assert edge_road_name(undirected_graph, 3, 4, 0) == ""

    def test_missing_edge_raises(self, undirected_graph):
        with pytest.raises(KeyError):
            edge_road_name(undirected_graph, 1, 3, 0)
