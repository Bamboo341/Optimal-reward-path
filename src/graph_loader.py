"""OSM道路ネットワークの取得・graphmlキャッシュ・無向化（SPEC.md §3 / Phase 0）。

キャッシュには無向化済みのグラフを保存する。これにより2回目以降の読込は
graphml のロードのみで完了し、受入基準（キャッシュから3秒以内）を満たしやすい。
"""

from __future__ import annotations

import math
import re
from pathlib import Path

import networkx as nx
import osmnx as ox


class GraphLoadError(RuntimeError):
    """OSMからのグラフ新規取得に失敗したときに送出する（SPEC.md §12）。"""


def place_slug(place: str) -> str:
    """place 文字列をファイル名に使えるスラッグへ変換する。

    例: "Shimogyo-ku, Kyoto, Japan" -> "shimogyo_ku_kyoto_japan"
    """
    slug = re.sub(r"[^a-z0-9]+", "_", place.lower()).strip("_")
    if not slug:
        raise ValueError(f"place からスラッグを生成できません: {place!r}")
    return slug


def graph_cache_path(place: str, data_dir: str | Path = "data") -> Path:
    return Path(data_dir) / f"graph_{place_slug(place)}.graphml"


def to_undirected(G: nx.MultiDiGraph | nx.MultiGraph) -> nx.MultiGraph:
    """有向 MultiDiGraph を無向 MultiGraph に変換する。無向ならそのまま返す。"""
    if not G.is_directed():
        return G
    return ox.convert.to_undirected(G)


def load_graph(
    place: str,
    network_type: str = "all",
    data_dir: str | Path = "data",
) -> nx.MultiGraph:
    """place の道路ネットワークを無向 MultiGraph として返す。

    キャッシュ（data/graph_{place_slug}.graphml）があればローカル読込、
    なければ OSM から取得して無向化のうえキャッシュに保存する。
    """
    path = graph_cache_path(place, data_dir)
    if path.exists():
        G = ox.io.load_graphml(path)
    else:
        G = to_undirected(_fetch_graph(place, network_type))
        path.parent.mkdir(parents=True, exist_ok=True)
        ox.io.save_graphml(G, path)
    # 旧形式（有向）のキャッシュにも耐えるよう常に無向化して返す
    return to_undirected(G)


def nearest_node(G: nx.MultiGraph, lat: float, lng: float) -> int:
    """地点 (lat, lng) の最近傍ノードを返す（SPEC §7.2 のスナップ用）。

    緯度補正付きの度数ユークリッド距離による線形探索。市区規模
    （〜1万ノード）なら十分高速で、追加依存も不要。
    """
    import numpy as np

    nodes = list(G.nodes)
    xs = np.array([G.nodes[n]["x"] for n in nodes])
    ys = np.array([G.nodes[n]["y"] for n in nodes])
    scale = math.cos(math.radians(lat))
    d2 = ((xs - lng) * scale) ** 2 + (ys - lat) ** 2
    return int(nodes[int(np.argmin(d2))])


def nearest_edge(G: nx.MultiGraph, lat: float, lng: float) -> tuple[int, int, int]:
    """地点 (lat, lng) の最近傍エッジを u < v 正規化した (u, v, key) で返す（SPEC §7.1）。"""
    u, v, key = ox.distance.nearest_edges(G, X=lng, Y=lat)
    return (int(u), int(v), int(key)) if u <= v else (int(v), int(u), int(key))


def edge_road_name(G: nx.MultiGraph, u: int, v: int, key: int) -> str:
    """エッジの道路名を返す。名称がなければ空文字列。"""
    data = G.get_edge_data(u, v, key)
    if data is None:
        raise KeyError(f"エッジが存在しません: {(u, v, key)}")
    name = data.get("name")
    if name is None or name == "":
        return ""
    if isinstance(name, (list, tuple)):
        return "・".join(str(n) for n in name)
    return str(name)


def _fetch_graph(place: str, network_type: str) -> nx.MultiDiGraph:
    try:
        return ox.graph_from_place(place, network_type=network_type, simplify=True)
    except Exception as exc:
        raise GraphLoadError(
            f"OSMからのグラフ取得に失敗しました（place={place!r}）。"
            "初回取得にはネットワーク接続が必要です。"
            "接続を確認するか、既存の graphml キャッシュを data/ に配置してください。"
        ) from exc
