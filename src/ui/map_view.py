"""folium 地図の構築部品（SPEC.md §7.1, §8）。

地図の頻繁な再読込（ズーム・表示位置のリセット）を防ぐため、
「ベース地図」と「変化するレイヤー」を分離する:

- ベース地図: タイル＋（任意で）選択可能道路の下敷き。セッション内で
  同一オブジェクトを使い回す（map_state.session_base_map）
- 変化するレイヤー（報酬エッジ・プレビュー・マーカー・候補経路）:
  FeatureGroup として st_folium の feature_group_to_add に渡し、
  地図全体を再読込せずに差し替える
"""

from __future__ import annotations

import weakref
from statistics import fmean

import folium
import networkx as nx

from src.rewards import RewardEdge
from src.route import RouteCandidate, edge_latlngs, route_latlngs  # noqa: F401

REWARD_COLOR = "red"
PREVIEW_COLOR = "blue"
CLICK_COLOR = "#333333"
SELECTABLE_COLOR = "#787878"

# 候補経路の色（候補1〜5。報酬エッジの赤と紛れない色を選ぶ）
ROUTE_COLORS = ["#1f77b4", "#2ca02c", "#9467bd", "#ff7f0e", "#17becf"]

# 選択可能道路の下敷きを描画するエッジ数の上限。
# 京都市全域などでは描画負荷が大きいため無効化する（SPEC §8 の方針）
MAX_OVERLAY_EDGES = 30_000


def graph_center(G: nx.MultiGraph) -> tuple[float, float]:
    """全ノードの重心 (lat, lng) を返す。"""
    xs = nx.get_node_attributes(G, "x")
    ys = nx.get_node_attributes(G, "y")
    return (fmean(ys.values()), fmean(xs.values()))


_EDGES_GEOJSON_CACHE: "weakref.WeakKeyDictionary[nx.MultiGraph, dict]" = (
    weakref.WeakKeyDictionary()
)


def edges_geojson(G: nx.MultiGraph) -> dict:
    """全エッジを LineString の FeatureCollection にする（選択可能道路の下敷き用）。

    再実行のたびに作り直さないよう、グラフごとにキャッシュする
    （グラフは読込後不変とみなす）。
    """
    cached = _EDGES_GEOJSON_CACHE.get(G)
    if cached is not None:
        return cached
    features = []
    for u, v, _key, data in G.edges(keys=True, data=True):
        geom = data.get("geometry")
        if geom is not None:
            coords = [[x, y] for x, y in geom.coords]
        else:
            coords = [
                [G.nodes[u]["x"], G.nodes[u]["y"]],
                [G.nodes[v]["x"], G.nodes[v]["y"]],
            ]
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": coords},
                "properties": {},
            }
        )
    result = {"type": "FeatureCollection", "features": features}
    _EDGES_GEOJSON_CACHE[G] = result
    return result


def create_base_map(
    G: nx.MultiGraph, zoom: int = 15, selectable_overlay: bool = False
) -> folium.Map:
    """ベース地図を構築する。selectable_overlay=True で全エッジをグレー描画。"""
    m = folium.Map(location=graph_center(G), zoom_start=zoom, tiles="OpenStreetMap")
    if selectable_overlay:
        folium.GeoJson(
            edges_geojson(G),
            style_function=lambda _f: {
                "color": SELECTABLE_COLOR,
                "weight": 2,
                "opacity": 0.6,
            },
            smooth_factor=2,
            # クリックを吸わせない（下敷きに当たると地図クリックが発火しないため）
            interactive=False,
        ).add_to(m)
    return m


def reward_feature_group(
    G: nx.MultiGraph,
    rewards: list[RewardEdge],
    preview_edge: tuple[int, int, int] | None = None,
    clicked: tuple[float, float] | None = None,
) -> folium.FeatureGroup:
    """報酬設定画面の可変レイヤー（報酬エッジ・選択プレビュー・クリック位置）。"""
    fg = folium.FeatureGroup(name="報酬設定")
    _add_reward_lines(G, rewards, fg)
    if preview_edge is not None:
        folium.PolyLine(
            edge_latlngs(G, *preview_edge),
            color=PREVIEW_COLOR,
            weight=8,
            opacity=0.9,
            tooltip="選択中のエッジ",
        ).add_to(fg)
    if clicked is not None:
        folium.CircleMarker(
            clicked,
            radius=5,
            color=CLICK_COLOR,
            fill=True,
            fill_opacity=0.9,
            tooltip="クリック位置",
        ).add_to(fg)
    return fg


def route_feature_group(
    G: nx.MultiGraph,
    rewards: list[RewardEdge],
    s: int | None = None,
    t: int | None = None,
    candidates: tuple | list = (),
    visible: set[int] | None = None,
) -> folium.FeatureGroup:
    """経路探索画面の可変レイヤー。

    visible は描画する候補 index の集合（None なら全候補を描画）。
    """
    fg = folium.FeatureGroup(name="経路探索")
    _add_reward_lines(G, rewards, fg)

    if s is not None:
        folium.Marker(
            (G.nodes[s]["y"], G.nodes[s]["x"]),
            tooltip=f"出発点（ノード {s}）",
            icon=folium.Icon(color="green", icon="play"),
        ).add_to(fg)
    if t is not None:
        folium.Marker(
            (G.nodes[t]["y"], G.nodes[t]["x"]),
            tooltip=f"到着点（ノード {t}）",
            icon=folium.Icon(color="darkred", icon="stop"),
        ).add_to(fg)

    for i, cand in enumerate(candidates):
        if visible is not None and i not in visible:
            continue
        folium.PolyLine(
            route_latlngs(G, cand.nodes, cand.edges),
            color=ROUTE_COLORS[i % len(ROUTE_COLORS)],
            weight=5,
            opacity=0.85,
            tooltip=f"候補{i + 1}: 報酬{cand.reward} / {cand.length:.0f}m",
        ).add_to(fg)
    return fg


def _add_reward_lines(G, rewards, fg) -> None:
    for r in rewards:
        folium.PolyLine(
            edge_latlngs(G, r.u, r.v, r.key),
            color=REWARD_COLOR,
            weight=6,
            opacity=0.8,
            tooltip=f"{r.road_name or '(名称なし)'} / 報酬: {r.reward}",
        ).add_to(fg)
