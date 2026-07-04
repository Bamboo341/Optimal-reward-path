"""再訪禁止モード（モードS）の経路構築（SPEC.md §5.3）。

モードRと同じ手順で得た報酬エッジ順列から、エッジ重複のない trail を構築する。

1. 接続区間ごとに、使用済みエッジへ大きなペナルティ（length×10⁶）を課した
   Dijkstra を逐次実行してエッジ重複を回避する
2. どうしても重複が必要な接続が生じた場合、その報酬エッジをスキップして
   再試行する（修復）
3. 完成経路が trail 条件と距離制約を満たすことを検証してから採用する
"""

from __future__ import annotations

import math

import networkx as nx

from src.rewards import EdgeId, RewardEdge, normalize_edge_id
from src.route import RouteCandidate, recount_reward

INF = math.inf
EPS = 1e-6
PENALTY = 1e6


def build_route_mode_s(
    G: nx.MultiGraph,
    rewards: list[RewardEdge],
    order: tuple[tuple[int, int], ...],
    s: int,
    t: int,
    limit: float,
) -> RouteCandidate | None:
    """訪問計画からエッジ重複のない実経路を構築する。修復不能なら None。

    重複が避けられない・距離上限を超える場合は報酬エッジを1本ずつ諦めて
    再試行する。order が空になれば直行の最短経路（常に trail）に帰着する。
    """
    remaining = list(order)
    while True:
        result = _try_build_trail(G, rewards, remaining, s, t)
        if isinstance(result, int):
            # result 番目の報酬エッジへの接続（または本体）が重複を強いる
            del remaining[result]
            continue
        if result is None:
            return None
        if result.length > limit + EPS:
            if not remaining:
                return None
            remaining.pop()  # 距離超過も報酬を1本諦めて修復
            continue
        return result


def _try_build_trail(
    G: nx.MultiGraph,
    rewards: list[RewardEdge],
    order: list[tuple[int, int]],
    s: int,
    t: int,
) -> RouteCandidate | int | None:
    """エッジ重複なしで経路を構築する。

    成功: RouteCandidate / 順列内 i 番目で重複が必要: i /
    グラフ分断等で接続不能: None
    """
    nodes: list[int] = [s]
    edges: list[EdgeId] = []
    used: set[EdgeId] = set()
    length = 0.0
    cur = s

    for i, (idx, o) in enumerate(order):
        r = rewards[idx]
        e_in, e_out = (r.u, r.v) if o == 0 else (r.v, r.u)
        if r.edge_id in used:
            return i
        seg = _penalized_segment(G, used, cur, e_in)
        if seg is None:
            return None
        seg_edges, seg_len, has_dup = seg
        if has_dup or any(eid == r.edge_id for _a, _b, eid, _l in seg_edges):
            # 接続区間自体が重複する／報酬エッジ本体を先に消費してしまう
            return i
        _apply_segment(G, nodes, edges, used, seg_edges)
        length += seg_len

        data = G.get_edge_data(r.u, r.v, r.key)
        if data is None:
            return None
        nodes.append(e_out)
        edges.append(r.edge_id)
        used.add(r.edge_id)
        length += data["length"]
        cur = e_out

    seg = _penalized_segment(G, used, cur, t)
    if seg is None:
        return None
    seg_edges, seg_len, has_dup = seg
    if has_dup:
        return len(order) - 1 if order else None
    _apply_segment(G, nodes, edges, used, seg_edges)
    length += seg_len

    reward, collected = recount_reward(edges, rewards)
    return RouteCandidate(
        nodes=tuple(nodes),
        edges=tuple(edges),
        length=length,
        reward=reward,
        collected=collected,
    )


def _penalized_segment(
    G: nx.MultiGraph, used: set[EdgeId], x: int, y: int
) -> tuple[list[tuple[int, int, EdgeId, float]], float, bool] | None:
    """使用済みエッジにペナルティを課した Dijkstra で x→y の区間を求める。

    返り値: ([(a, b, edge_id, length), ...], 実総距離, 使用済みエッジを含むか)。
    x, y が非連結なら None。
    """

    def weight(u, v, data):
        best = INF
        for key, d in data.items():
            w = d.get("length", INF)
            if normalize_edge_id(u, v, key) in used:
                w *= PENALTY
            best = min(best, w)
        return best

    try:
        path = nx.dijkstra_path(G, x, y, weight=weight)
    except nx.NetworkXNoPath:
        return None

    seg: list[tuple[int, int, EdgeId, float]] = []
    total = 0.0
    has_dup = False
    for a, b in zip(path, path[1:]):
        # Dijkstra と同じ基準（ペナルティ込み最小）で並行エッジを選ぶ
        best_key, best_w, best_len = None, INF, 0.0
        for key, d in G[a][b].items():
            raw = d.get("length", INF)
            w = raw * PENALTY if normalize_edge_id(a, b, key) in used else raw
            if w < best_w:
                best_key, best_w, best_len = key, w, raw
        eid = normalize_edge_id(a, b, best_key)
        if eid in used:
            has_dup = True
        seg.append((a, b, eid, best_len))
        total += best_len
    return seg, total, has_dup


def _apply_segment(G, nodes, edges, used, seg_edges) -> None:
    for _a, b, eid, _l in seg_edges:
        nodes.append(b)
        edges.append(eid)
        used.add(eid)
