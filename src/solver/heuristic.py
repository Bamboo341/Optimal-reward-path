"""貪欲挿入＋ローカルサーチによるヒューリスティック探索（SPEC.md §5.2）。

|R| > N_exact のときに使う。解は「報酬エッジの訪問順列＋方向」で表現し、
総距離はメタ距離テーブルで評価する。

- 初期解: 貪欲挿入（報酬/追加距離 比が最大のエッジを距離制約内で逐次挿入）
- 改善: ローカルサーチ（挿入・削除・入替・2-opt・方向反転）
- ランダムリスタート（ランダム化貪欲）付きで反復し、time_limit_sec 到達で
  打ち切る。収束後も回し続けても改善しないため、リスタートが一定回数
  連続で全体最良を更新しない場合は早期終了する（上限は time_limit_sec）。

探索中に評価した実行可能解を mask ごとに最良保持し、上位 k 件を返す。
"""

from __future__ import annotations

import math
import random
import time

from src.rewards import RewardEdge
from src.solver.exact_dp import PlannedSolution, distance_tables
from src.solver.metagraph import MetaGraph

INF = math.inf
EPS = 1e-6

Visit = tuple[int, int]  # (報酬エッジindex, 方向o)


def solve_heuristic(
    meta: MetaGraph,
    rewards: list[RewardEdge],
    edge_lengths: list[float],
    s: int,
    t: int,
    limit: float,
    k: int = 3,
    time_limit_sec: float = 90.0,
    seed: int = 0,
    max_stale_restarts: int = 8,
) -> list[PlannedSolution]:
    n = len(rewards)
    if n == 0:
        return []
    searcher = _Searcher(
        meta, rewards, edge_lengths, s, t, limit, seed, time_limit_sec
    )
    searcher.run(max_stale_restarts)
    return searcher.top_plans(k)


class _Searcher:
    def __init__(self, meta, rewards, edge_lengths, s, t, limit, seed, time_limit_sec):
        self.rewards = rewards
        self.lengths = edge_lengths
        self.limit = limit
        self.n = len(rewards)
        self.rng = random.Random(seed)
        self.deadline = time.monotonic() + time_limit_sec
        self.d_st = meta.d(s, t)
        self.d_s_in, self.d_out_t, self.d_conn = distance_tables(meta, rewards, s, t)
        # mask -> (総距離, 訪問順列)。実行可能解のプール（SPEC §5.4 の候補源）
        self.pool: dict[int, tuple[float, tuple[Visit, ...]]] = {}

    # --- 評価 ---

    def plan_length(self, order: list[Visit]) -> float:
        if not order:
            return self.d_st
        i0, o0 = order[0]
        total = self.d_s_in[i0][o0] + self.lengths[i0]
        for (i, o), (j, o2) in zip(order, order[1:]):
            total += self.d_conn[i][o][j][o2] + self.lengths[j]
        il, ol = order[-1]
        return total + self.d_out_t[il][ol]

    def plan_reward(self, order: list[Visit]) -> int:
        return sum(self.rewards[i].reward for i, _ in order)

    def _record(self, order: list[Visit], length: float) -> None:
        if length > self.limit + EPS:
            return
        mask = 0
        for i, _ in order:
            mask |= 1 << i
        cur = self.pool.get(mask)
        if cur is None or length < cur[0] - EPS:
            self.pool[mask] = (length, tuple(order))

    def _time_up(self) -> bool:
        return time.monotonic() >= self.deadline

    # --- 探索本体 ---

    def run(self, max_stale_restarts: int) -> None:
        stale = 0
        best_key: tuple[int, float] | None = None
        while not self._time_up() and stale <= max_stale_restarts:
            order = self.greedy(randomized=bool(self.pool))
            order = self.local_search(order)
            self._record(order, self.plan_length(order))

            key = self._pool_best_key()
            if key != best_key:
                best_key, stale = key, 0
            else:
                stale += 1

    def _pool_best_key(self) -> tuple[int, float] | None:
        if not self.pool:
            return None
        best = max(
            self.pool.items(),
            key=lambda kv: (self._mask_reward(kv[0]), -kv[1][0]),
        )
        return (self._mask_reward(best[0]), best[1][0])

    def _mask_reward(self, mask: int) -> int:
        return sum(
            self.rewards[i].reward for i in range(self.n) if mask & (1 << i)
        )

    def greedy(self, randomized: bool = False) -> list[Visit]:
        """報酬/追加距離 比が最大のエッジを距離制約内で逐次挿入する。

        randomized=True では上位3候補からランダムに選ぶ（リスタート用）。
        """
        order: list[Visit] = []
        length = self.d_st
        remaining = set(range(self.n))
        while remaining and not self._time_up():
            gains = []
            for j in remaining:
                best = self._best_insertion(order, length, j)
                if best is not None:
                    delta, pos, o = best
                    ratio = self.rewards[j].reward / max(delta, 1.0)
                    gains.append((ratio, j, pos, o, delta))
            if not gains:
                break
            gains.sort(key=lambda g: -g[0])
            pick = (
                self.rng.choice(gains[: min(3, len(gains))]) if randomized else gains[0]
            )
            _, j, pos, o, delta = pick
            order.insert(pos, (j, o))
            length += delta
            remaining.discard(j)
        return order

    def _best_insertion(
        self, order: list[Visit], length: float, j: int
    ) -> tuple[float, int, int] | None:
        """報酬エッジ j の最良挿入 (追加距離, 位置, 方向) を返す。不能なら None。"""
        best = None
        for pos in range(len(order) + 1):
            for o in (0, 1):
                delta = self._insertion_delta(order, pos, j, o)
                if length + delta <= self.limit + EPS and (
                    best is None or delta < best[0] - EPS
                ):
                    best = (delta, pos, o)
        return best

    def _insertion_delta(self, order: list[Visit], pos: int, j: int, o: int) -> float:
        d_in = (
            self.d_s_in[j][o]
            if pos == 0
            else self.d_conn[order[pos - 1][0]][order[pos - 1][1]][j][o]
        )
        d_out = (
            self.d_out_t[j][o]
            if pos == len(order)
            else self.d_conn[j][o][order[pos][0]][order[pos][1]]
        )
        if pos == 0 and pos == len(order):
            removed = self.d_st
        elif pos == 0:
            nx_i, nx_o = order[0]
            removed = self.d_s_in[nx_i][nx_o]
        elif pos == len(order):
            pv_i, pv_o = order[-1]
            removed = self.d_out_t[pv_i][pv_o]
        else:
            pv_i, pv_o = order[pos - 1]
            nx_i, nx_o = order[pos]
            removed = self.d_conn[pv_i][pv_o][nx_i][nx_o]
        return d_in + self.lengths[j] + d_out - removed

    def local_search(self, order: list[Visit]) -> list[Visit]:
        """距離短縮（方向反転・2-opt・入替・削除）と挿入（報酬増）を反復する。"""
        improved = True
        while improved and not self._time_up():
            improved = False
            length = self.plan_length(order)
            reward = self.plan_reward(order)

            # 距離を縮める・報酬を上げる近傍を first-improvement で採用
            for cand in self._neighbors(order):
                c_len = self.plan_length(cand)
                if c_len > self.limit + EPS:
                    continue
                c_rew = self.plan_reward(cand)
                if c_rew > reward or (c_rew == reward and c_len < length - EPS):
                    self._record(cand, c_len)
                    order, improved = cand, True
                    break
        return order

    def _neighbors(self, order: list[Visit]):
        k = len(order)
        collected = {i for i, _ in order}
        # 方向反転
        for i in range(k):
            cand = order.copy()
            cand[i] = (cand[i][0], 1 - cand[i][1])
            yield cand
        # 2-opt（部分列を反転し、内部の方向も反転）
        for a in range(k - 1):
            for b in range(a + 1, k):
                mid = [(i, 1 - o) for i, o in reversed(order[a : b + 1])]
                yield order[:a] + mid + order[b + 1 :]
        # 入替（回収済み1本を未回収1本に置換）
        for pos in range(k):
            for j in range(self.n):
                if j in collected:
                    continue
                for o in (0, 1):
                    cand = order.copy()
                    cand[pos] = (j, o)
                    yield cand
        # 挿入（未回収の報酬エッジを追加 → 報酬増）
        for j in range(self.n):
            if j in collected:
                continue
            for pos in range(k + 1):
                for o in (0, 1):
                    cand = order.copy()
                    cand.insert(pos, (j, o))
                    yield cand
        # 削除（それ自体では報酬減だが、削除+挿入の組で改善する場合がある。
        # 削除後に挿入近傍が同一パス内で評価されるよう最後に置く）
        for pos in range(k):
            yield order[:pos] + order[pos + 1 :]

    def top_plans(self, k: int) -> list[PlannedSolution]:
        ranked = sorted(
            self.pool.items(),
            key=lambda kv: (-self._mask_reward(kv[0]), kv[1][0], kv[0]),
        )[:k]
        return [
            PlannedSolution(
                mask=mask,
                order=order,
                planned_length=length,
                planned_reward=self._mask_reward(mask),
            )
            for mask, (length, order) in ranked
        ]
