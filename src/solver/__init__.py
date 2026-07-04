"""報酬最大化経路探索のオーケストレーション（SPEC.md §5）。"""

from __future__ import annotations

import networkx as nx

from src.rewards import RewardEdge
from src.route import RouteCandidate, build_route
from src.solver.exact_dp import PlannedSolution, solve_exact
from src.solver.metagraph import MetaGraph, build_metagraph

EPS = 1e-6


class SolverError(RuntimeError):
    """実行可能解が存在しない等、探索を継続できないときに送出する。"""


def solve(
    G: nx.MultiGraph,
    rewards: list[RewardEdge],
    s: int,
    t: int,
    limit: float,
    k: int = 3,
    n_exact: int = 14,
    mode: str = "R",
) -> list[RouteCandidate]:
    """s から t への距離上限 limit の報酬最大化経路を上位 k 件返す。

    候補は回収報酬エッジ集合が互いに異なるものだけを採用する（SPEC §5.4）。
    実行可能解が存在しない（s-t 最短距離 > limit）場合は SolverError。
    """
    if s not in G:
        raise SolverError(f"出発ノード {s} がグラフに存在しません")
    if t not in G:
        raise SolverError(f"到着ノード {t} がグラフに存在しません")
    if mode != "R":
        raise SolverError(f"モード {mode!r} は未実装です（Phase 3 で対応予定）")

    meta = build_metagraph(G, s, t, rewards)
    direct = meta.d(s, t)
    if direct > limit + EPS:
        raise SolverError(
            f"実行可能解がありません: 出発点から到着点への最短距離 "
            f"{direct:.0f}m が距離上限 {limit:.0f}m を超えています"
        )

    # 距離上限内で回収し得ない報酬エッジを除外してマスク空間を削減する
    usable = _usable_rewards(G, meta, rewards, s, t, limit)
    if len(usable) > n_exact:
        raise SolverError(
            f"回収可能な報酬エッジが {len(usable)} 本あり、厳密解の上限 "
            f"N_exact={n_exact} を超えています（Phase 3 のヒューリスティックで対応予定）"
        )

    rewards_sub = [r for r, _ in usable]
    lengths_sub = [l for _, l in usable]
    planned = solve_exact(meta, rewards_sub, lengths_sub, s, t, limit, k=k)
    # 直行解（報酬エッジ回収なし）も常に候補に含める
    planned.append(
        PlannedSolution(mask=0, order=(), planned_length=direct, planned_reward=0)
    )

    candidates: list[RouteCandidate] = []
    seen: set[frozenset] = set()
    for plan in planned:
        route = build_route(G, meta, rewards_sub, plan.order, s, t)
        collected_ids = frozenset(r.edge_id for r in route.collected)
        # 報酬再集計後に回収集合が重複した候補は最良の1件に統合（SPEC §5.4）
        if collected_ids in seen:
            continue
        seen.add(collected_ids)
        candidates.append(route)

    candidates.sort(key=lambda c: (-c.reward, c.length))
    return candidates[:k]


def _usable_rewards(
    G: nx.MultiGraph,
    meta: MetaGraph,
    rewards: list[RewardEdge],
    s: int,
    t: int,
    limit: float,
) -> list[tuple[RewardEdge, float]]:
    usable = []
    for r in rewards:
        data = G.get_edge_data(r.u, r.v, r.key)
        if data is None:
            raise SolverError(f"報酬エッジ {r.edge_id} がグラフに存在しません")
        length = data["length"]
        best = min(
            meta.d(s, r.u) + length + meta.d(r.v, t),
            meta.d(s, r.v) + length + meta.d(r.u, t),
        )
        if best <= limit + EPS:
            usable.append((r, length))
    return usable
