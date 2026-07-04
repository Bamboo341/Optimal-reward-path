"""folium 地図の構築部品（SPEC.md §7.1, §8）。

描画負荷対策のため全エッジは描かず、背景タイル＋報酬エッジ（＋プレビュー・
経路）のみを描画する（SPEC §8）。
"""

from __future__ import annotations

from statistics import fmean

import folium
import networkx as nx

from src.rewards import RewardEdge

REWARD_COLOR = "red"
PREVIEW_COLOR = "blue"


def graph_center(G: nx.MultiGraph) -> tuple[float, float]:
    """全ノードの重心 (lat, lng) を返す。"""
    xs = nx.get_node_attributes(G, "x")
    ys = nx.get_node_attributes(G, "y")
    return (fmean(ys.values()), fmean(xs.values()))


def edge_latlngs(G: nx.MultiGraph, u: int, v: int, key: int) -> list[tuple[float, float]]:
    """エッジの描画用座標列 [(lat, lng), ...] を返す。

    geometry 属性があればその形状、なければ両端ノードを結ぶ直線。
    """
    data = G.get_edge_data(u, v, key)
    if data is None:
        raise KeyError(f"エッジが存在しません: {(u, v, key)}")
    geom = data.get("geometry")
    if geom is not None:
        return [(lat, lng) for lng, lat in geom.coords]
    return [(G.nodes[u]["y"], G.nodes[u]["x"]), (G.nodes[v]["y"], G.nodes[v]["x"])]


def build_reward_map(
    G: nx.MultiGraph,
    rewards: list[RewardEdge],
    preview_edge: tuple[int, int, int] | None = None,
    center: tuple[float, float] | None = None,
    zoom: int = 15,
) -> folium.Map:
    """報酬設定画面の地図を構築する。

    設定済み報酬エッジは赤色＋報酬値ツールチップ、選択中エッジは青色で描画。
    """
    if center is None:
        center = graph_center(G)
    m = folium.Map(location=center, zoom_start=zoom, tiles="OpenStreetMap")

    for r in rewards:
        folium.PolyLine(
            edge_latlngs(G, r.u, r.v, r.key),
            color=REWARD_COLOR,
            weight=6,
            opacity=0.8,
            tooltip=f"{r.road_name or '(名称なし)'} / 報酬: {r.reward}",
        ).add_to(m)

    if preview_edge is not None:
        folium.PolyLine(
            edge_latlngs(G, *preview_edge),
            color=PREVIEW_COLOR,
            weight=8,
            opacity=0.9,
            tooltip="選択中のエッジ",
        ).add_to(m)

    return m
