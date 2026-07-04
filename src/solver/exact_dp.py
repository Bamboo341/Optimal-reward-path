"""ビットマスクDPによるモードRの厳密解（SPEC.md §5.2）。

状態: dp[mask][i][o] = 報酬エッジ集合 mask を回収済みで、最後にエッジ i を
方向 o（0: u→v, 1: v→u）で通過し終えた時点の最小総距離。

「現在の状態から t へ直行しても limit を超える」状態は、以後どう延長しても
実行可能にならない（三角不等式）ため、生成時点で枝刈りする。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from src.rewards import RewardEdge
from src.solver.metagraph import MetaGraph

INF = math.inf
EPS = 1e-6


@dataclass(frozen=True)
class PlannedSolution:
    """DPが返す訪問計画。実経路への復元は route.build_route が行う。"""

    mask: int
    order: tuple[tuple[int, int], ...]  # (報酬エッジindex, 方向o) の訪問順
    planned_length: float
    planned_reward: int


def _ends(r: RewardEdge, o: int) -> tuple[int, int]:
    """方向 o で通過するときの (入口, 出口) ノード。"""
    return (r.u, r.v) if o == 0 else (r.v, r.u)


def solve_exact(
    meta: MetaGraph,
    rewards: list[RewardEdge],
    edge_lengths: list[float],
    s: int,
    t: int,
    limit: float,
    k: int = 3,
) -> list[PlannedSolution]:
    """回収する報酬エッジ集合（mask）が互いに異なる上位 k 計画を返す。

    各 mask については最小総距離の訪問順・方向を採用する。
    """
    n = len(rewards)
    if n == 0:
        return []

    # メタ距離を配列に前計算（DP内側ループの辞書引きを避ける）
    # d_s_in[j][o]: s から j の入口まで / d_out_t[i][o]: i の出口から t まで
    # d_conn[i][o][j][o2]: i の出口から j の入口まで
    d_s_in = [[meta.d(s, _ends(r, o)[0]) for o in (0, 1)] for r in rewards]
    d_out_t = [[meta.d(_ends(r, o)[1], t) for o in (0, 1)] for r in rewards]
    d_conn = [
        [
            [
                [meta.d(_ends(ri, o)[1], _ends(rj, o2)[0]) for o2 in (0, 1)]
                for rj in rewards
            ]
            for o in (0, 1)
        ]
        for ri in rewards
    ]

    size = 1 << n
    dp = [[[INF, INF] for _ in range(n)] for _ in range(size)]
    parent: dict[tuple[int, int, int], tuple[int, int, int] | None] = {}

    for i in range(n):
        for o in (0, 1):
            cost = d_s_in[i][o] + edge_lengths[i]
            if cost + d_out_t[i][o] <= limit + EPS:
                dp[1 << i][i][o] = cost
                parent[(1 << i, i, o)] = None

    for mask in range(1, size):
        dp_mask = dp[mask]
        for i in range(n):
            if not mask & (1 << i):
                continue
            for o in (0, 1):
                cur = dp_mask[i][o]
                if cur == INF:
                    continue
                conn = d_conn[i][o]
                for j in range(n):
                    if mask & (1 << j):
                        continue
                    new_mask = mask | (1 << j)
                    dp_new = dp[new_mask][j]
                    for o2 in (0, 1):
                        cand = cur + conn[j][o2] + edge_lengths[j]
                        if (
                            cand + d_out_t[j][o2] <= limit + EPS
                            and cand < dp_new[o2] - EPS
                        ):
                            dp_new[o2] = cand
                            parent[(new_mask, j, o2)] = (mask, i, o)

    # mask ごとに最小総距離の終端状態を選ぶ
    best: dict[int, tuple[float, int, int]] = {}
    for mask in range(1, size):
        dp_mask = dp[mask]
        for i in range(n):
            for o in (0, 1):
                if dp_mask[i][o] == INF:
                    continue
                total = dp_mask[i][o] + d_out_t[i][o]
                if total <= limit + EPS and (
                    mask not in best or total < best[mask][0] - EPS
                ):
                    best[mask] = (total, i, o)

    reward_of = lambda mask: sum(
        rewards[i].reward for i in range(n) if mask & (1 << i)
    )
    ranked = sorted(
        best.items(), key=lambda kv: (-reward_of(kv[0]), kv[1][0], kv[0])
    )[:k]

    solutions = []
    for mask, (total, i, o) in ranked:
        order: list[tuple[int, int]] = []
        state: tuple[int, int, int] | None = (mask, i, o)
        while state is not None:
            m, si, so = state
            order.append((si, so))
            state = parent[(m, si, so)]
        order.reverse()
        solutions.append(
            PlannedSolution(
                mask=mask,
                order=tuple(order),
                planned_length=total,
                planned_reward=reward_of(mask),
            )
        )
    return solutions
