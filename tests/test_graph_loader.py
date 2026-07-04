from pathlib import Path

import networkx as nx
import pytest

from src import graph_loader
from src.graph_loader import (
    GraphLoadError,
    graph_cache_path,
    load_graph,
    place_slug,
    to_undirected,
)


def make_synthetic_graph() -> nx.MultiDiGraph:
    """OSMnx互換の最小限の属性を持つ合成有向グラフ。"""
    G = nx.MultiDiGraph(crs="epsg:4326", simplified=True)
    coords = {1: (135.758, 34.990), 2: (135.759, 34.990), 3: (135.759, 34.991)}
    for node, (x, y) in coords.items():
        G.add_node(node, x=x, y=y)
    # 双方向道路（往復2本の有向エッジ）→ 無向化で1本に統合される
    G.add_edge(1, 2, key=0, osmid=100, length=100.0)
    G.add_edge(2, 1, key=0, osmid=100, length=100.0)
    # 一方通行道路 → 無向化でそのまま1本になる
    G.add_edge(2, 3, key=0, osmid=101, length=150.0, oneway=True)
    return G


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
        assert G.number_of_nodes() == 3
        # 双方向1本＋一方通行1本 = 無向エッジ2本
        assert G.number_of_edges() == 2
        assert G.has_edge(1, 2)
        assert G.has_edge(2, 3)

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

    def test_cache_preserves_length_as_float(self, tmp_path, fetch_mock):
        place = "Test Place"
        load_graph(place, data_dir=tmp_path)
        G = load_graph(place, data_dir=tmp_path)

        lengths = {(u, v): d["length"] for u, v, d in G.edges(data=True)}
        assert lengths[(1, 2)] == pytest.approx(100.0)
        assert lengths[(2, 3)] == pytest.approx(150.0)
        assert all(isinstance(x, float) for x in lengths.values())

    def test_fetch_failure_raises_graph_load_error(self, tmp_path, monkeypatch):
        def broken(*args, **kwargs):
            raise OSError("network down")

        monkeypatch.setattr(graph_loader.ox, "graph_from_place", broken)
        with pytest.raises(GraphLoadError, match="取得に失敗"):
            load_graph("Nowhere", data_dir=tmp_path)
