import networkx as nx
import pytest
from shapely.geometry import LineString


def make_synthetic_graph() -> nx.MultiDiGraph:
    """OSMnx互換の最小限の属性を持つ合成有向グラフ（正方形の4ノード）。

    - 1-2: 双方向・名称あり
    - 2-3: 一方通行・名称がリスト
    - 3-4: 双方向・geometry属性つき（中間点で膨らむ）・名称なし
    - 4-1: 一方通行・名称なし（u > v で追加され、正規化の検証に使える）
    """
    G = nx.MultiDiGraph(crs="epsg:4326", simplified=True)
    coords = {
        1: (135.758, 34.990),
        2: (135.759, 34.990),
        3: (135.759, 34.991),
        4: (135.758, 34.991),
    }
    for node, (x, y) in coords.items():
        G.add_node(node, x=x, y=y)

    G.add_edge(1, 2, key=0, osmid=100, length=100.0, name="四条通")
    G.add_edge(2, 1, key=0, osmid=100, length=100.0, name="四条通")
    G.add_edge(2, 3, key=0, osmid=101, length=150.0, oneway=True,
               name=["高倉通", "Takakura"])
    geom = LineString([(135.759, 34.991), (135.7585, 34.9912), (135.758, 34.991)])
    G.add_edge(3, 4, key=0, osmid=102, length=120.0, geometry=geom)
    G.add_edge(4, 3, key=0, osmid=102, length=120.0,
               geometry=LineString(list(geom.coords)[::-1]))
    G.add_edge(4, 1, key=0, osmid=103, length=110.0, oneway=True)
    return G


@pytest.fixture
def undirected_graph() -> nx.MultiGraph:
    from src.graph_loader import to_undirected

    return to_undirected(make_synthetic_graph())
