"""経路復元・報酬再集計・検証（SPEC.md §5.2, §11）。"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

import networkx as nx

from src.rewards import EdgeId, RewardEdge, normalize_edge_id

if TYPE_CHECKING:  # 実行時循環import回避（solver/__init__ が本モジュールを使う）
    from src.solver.metagraph import MetaGraph

INF = math.inf
EPS = 1e-6


class RouteError(RuntimeError):
    """経路の復元・検証に失敗したときに送出する。"""


@dataclass(frozen=True)
class RouteCandidate:
    """探索結果の1候補。

    - nodes: 実経路のノード列（先頭 s、末尾 t）
    - edges: 通過順のエッジ列（u < v 正規化した (u, v, key)）
    - length: 総距離（メートル）
    - reward: 実経路を走査して再集計した総報酬（同一エッジは1回のみ加算）
    - collected: 回収した報酬エッジ一覧（edge_id 昇順）
    """

    nodes: tuple[int, ...]
    edges: tuple[EdgeId, ...]
    length: float
    reward: int
    collected: tuple[RewardEdge, ...]


def build_route(
    G: nx.MultiGraph,
    meta: MetaGraph,
    rewards: list[RewardEdge],
    order: tuple[tuple[int, int], ...],
    s: int,
    t: int,
) -> RouteCandidate:
    """訪問計画（報酬エッジの順列＋方向）から実経路を復元する。

    接続区間は前計算した最短経路を連結する（SPEC §5.2 経路復元）。
    報酬は復元後の実経路を走査して再集計する（SPEC §5.2 報酬の再集計）。
    """
    nodes: list[int] = [s]
    edges: list[EdgeId] = []
    length = 0.0
    cur = s

    for idx, o in order:
        r = rewards[idx]
        e_in, e_out = (r.u, r.v) if o == 0 else (r.v, r.u)
        length += _append_shortest_path(G, meta, nodes, edges, cur, e_in)
        data = G.get_edge_data(r.u, r.v, r.key)
        if data is None:
            raise RouteError(f"報酬エッジ {r.edge_id} がグラフに存在しません")
        nodes.append(e_out)
        edges.append(r.edge_id)
        length += data["length"]
        cur = e_out

    length += _append_shortest_path(G, meta, nodes, edges, cur, t)

    reward, collected = recount_reward(edges, rewards)
    return RouteCandidate(
        nodes=tuple(nodes),
        edges=tuple(edges),
        length=length,
        reward=reward,
        collected=collected,
    )


def _append_shortest_path(
    G: nx.MultiGraph,
    meta: MetaGraph,
    nodes: list[int],
    edges: list[EdgeId],
    x: int,
    y: int,
) -> float:
    """メタグラフの前計算経路 x→y を nodes/edges に連結し、追加距離を返す。"""
    seg = meta.path(x, y)
    if seg is None:
        raise RouteError(f"ノード {x} から {y} への経路がありません")
    added = 0.0
    for a, b in zip(seg, seg[1:]):
        key, edge_len = _min_length_edge(G, a, b)
        nodes.append(b)
        edges.append(normalize_edge_id(a, b, key))
        added += edge_len
    return added


def _min_length_edge(G: nx.MultiGraph, a: int, b: int) -> tuple[int, float]:
    """a-b 間の並行エッジのうち最短のもの（Dijkstraが使う重みと同じ）を返す。"""
    data = G.get_edge_data(a, b)
    if not data:
        raise RouteError(f"エッジ {a}-{b} がグラフに存在しません")
    key, d = min(data.items(), key=lambda kv: kv[1].get("length", INF))
    return key, d["length"]


def recount_reward(
    edges: tuple[EdgeId, ...] | list[EdgeId],
    rewards: list[RewardEdge],
) -> tuple[int, tuple[RewardEdge, ...]]:
    """実経路のエッジ列から総報酬を再集計する。

    接続部で偶然通過した報酬エッジも加算し、同一報酬エッジは複数回
    通過しても1回のみ加算する（SPEC §4, §5.2）。
    """
    index = {r.edge_id: r for r in rewards}
    collected = {
        eid: index[eid] for eid in (normalize_edge_id(*e) for e in edges) if eid in index
    }
    ordered = tuple(sorted(collected.values(), key=lambda r: r.edge_id))
    return sum(r.reward for r in ordered), ordered


def validate_route(
    G: nx.MultiGraph,
    route: RouteCandidate,
    s: int,
    t: int,
    limit: float,
    forbid_repeated_edges: bool = False,
) -> None:
    """返却経路が実行可能解であることを検証する（SPEC §11）。

    (a) s-t を接続し隣接ノードが実エッジで結ばれている
    (b) 総距離 ≤ limit
    (c) forbid_repeated_edges=True（モードS）ならエッジ重複なし
    違反があれば RouteError を送出する。
    """
    if not route.nodes or route.nodes[0] != s or route.nodes[-1] != t:
        raise RouteError(f"経路が s={s}, t={t} を接続していません")
    if len(route.edges) != len(route.nodes) - 1:
        raise RouteError("ノード列とエッジ列の長さが一致しません")

    total = 0.0
    for (a, b), (u, v, key) in zip(zip(route.nodes, route.nodes[1:]), route.edges):
        if {a, b} != {u, v}:
            raise RouteError(f"エッジ {(u, v, key)} が区間 {a}-{b} と一致しません")
        data = G.get_edge_data(u, v, key)
        if data is None:
            raise RouteError(f"エッジ {(u, v, key)} がグラフに存在しません")
        total += data["length"]

    if abs(total - route.length) > 1e-3:
        raise RouteError(f"総距離が一致しません: {total} != {route.length}")
    if total > limit + EPS:
        raise RouteError(f"総距離 {total:.0f}m が距離上限 {limit:.0f}m を超えています")

    if forbid_repeated_edges and len(set(route.edges)) != len(route.edges):
        raise RouteError("同一エッジを2回以上通過しています（モードS違反）")
