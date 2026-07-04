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

# 候補経路の色（候補1〜5。報酬エッジの赤と紛れない色を選ぶ）
ROUTE_COLORS = ["#1f77b4", "#2ca02c", "#9467bd", "#ff7f0e", "#17becf"]


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


def route_latlngs(G: nx.MultiGraph, nodes, edges) -> list[tuple[float, float]]:
    """経路（ノード列＋エッジ列）を連続した描画座標列に変換する。

    各エッジの geometry を通過方向に向きを揃えて連結する。
    """
    pts: list[tuple[float, float]] = []
    for (a, _b), (u, v, key) in zip(zip(nodes, nodes[1:]), edges):
        seg = edge_latlngs(G, u, v, key)
        start = (G.nodes[a]["y"], G.nodes[a]["x"])
        d_head = (seg[0][0] - start[0]) ** 2 + (seg[0][1] - start[1]) ** 2
        d_tail = (seg[-1][0] - start[0]) ** 2 + (seg[-1][1] - start[1]) ** 2
        if d_tail < d_head:
            seg = seg[::-1]
        pts.extend(seg if not pts else seg[1:])
    return pts


def build_route_map(
    G: nx.MultiGraph,
    rewards: list[RewardEdge],
    s: int | None = None,
    t: int | None = None,
    candidates=(),
    center: tuple[float, float] | None = None,
    zoom: int = 15,
) -> folium.Map:
    """経路探索画面の地図を構築する。

    報酬エッジ（赤）の上に、候補経路を色分けした FeatureGroup として重畳する。
    レイヤーコントロールで候補ごとに表示/非表示を切替できる（SPEC §7.2）。
    """
    m = build_reward_map(G, rewards, center=center, zoom=zoom)

    if s is not None:
        folium.Marker(
            (G.nodes[s]["y"], G.nodes[s]["x"]),
            tooltip=f"出発点（ノード {s}）",
            icon=folium.Icon(color="green", icon="play"),
        ).add_to(m)
    if t is not None:
        folium.Marker(
            (G.nodes[t]["y"], G.nodes[t]["x"]),
            tooltip=f"到着点（ノード {t}）",
            icon=folium.Icon(color="darkred", icon="stop"),
        ).add_to(m)

    for i, cand in enumerate(candidates):
        color = ROUTE_COLORS[i % len(ROUTE_COLORS)]
        group = folium.FeatureGroup(
            name=f"候補{i + 1}: 報酬{cand.reward} / {cand.length:.0f}m"
        )
        folium.PolyLine(
            route_latlngs(G, cand.nodes, cand.edges),
            color=color,
            weight=5,
            opacity=0.8,
            tooltip=f"候補{i + 1}: 報酬{cand.reward} / {cand.length:.0f}m",
        ).add_to(group)
        group.add_to(m)

    if candidates:
        folium.LayerControl(collapsed=False).add_to(m)
    return m
