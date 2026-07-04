"""Phase 3 のテスト: ヒューリスティック探索とモードS（SPEC.md §5.2, §5.3, §10）。"""

import time

import networkx as nx
import pytest

from src.rewards import RewardEdge
from src.route import validate_route
from src.solver import SolverError, solve
from src.solver.exact_dp import solve_exact
from src.solver.heuristic import solve_heuristic
from src.solver.metagraph import build_metagraph
from src.solver.mode_s import build_route_mode_s
from tests.test_solver import grid_graph, line_graph, reward


class TestHeuristic:
    def test_matches_exact_on_small_case(self):
        """小さいケースでは厳密解（DP）と同じ報酬に到達する。"""
        G = grid_graph(5)
        rewards = [
            reward(0, 1, 10),
            reward(6, 11, 25),
            reward(17, 18, 40),
            reward(23, 24, 15),
        ]
        s, t, limit = 0, 24, 1400.0
        meta = build_metagraph(G, s, t, rewards)
        lengths = [100.0] * len(rewards)

        exact = solve_exact(meta, rewards, lengths, s, t, limit, k=1)[0]
        heur = solve_heuristic(
            meta, rewards, lengths, s, t, limit, k=1, time_limit_sec=10.0, seed=1
        )[0]

        assert heur.planned_reward == exact.planned_reward
        assert heur.planned_length == pytest.approx(exact.planned_length)

    def test_returns_distinct_masks_sorted(self):
        G = grid_graph(5)
        rewards = [reward(0, 1, 10), reward(6, 11, 25), reward(17, 18, 40)]
        meta = build_metagraph(G, 0, 24, rewards)
        plans = solve_heuristic(
            meta, rewards, [100.0] * 3, 0, 24, 1400.0, k=5, time_limit_sec=10.0
        )

        masks = [p.mask for p in plans]
        assert len(masks) == len(set(masks))
        assert all(
            a.planned_reward >= b.planned_reward for a, b in zip(plans, plans[1:])
        )

    def test_respects_time_limit(self):
        """time_limit_sec 到達で打ち切り、その時点の最良解を返す（SPEC §5.2）。"""
        G = grid_graph(10)
        rewards = [
            reward(i * 10 + j, i * 10 + j + 1, 5 + (i * 7 + j) % 20)
            for i in range(6)
            for j in range(4)
        ]  # 24本
        meta = build_metagraph(G, 0, 99, rewards)
        lengths = [100.0] * len(rewards)

        t0 = time.monotonic()
        plans = solve_heuristic(
            meta, rewards, lengths, 0, 99, 3000.0,
            k=3, time_limit_sec=2.0, max_stale_restarts=10**9,
        )
        elapsed = time.monotonic() - t0
        assert elapsed < 5.0  # 2秒上限＋後処理の余裕
        assert plans and plans[0].planned_reward > 0

    def test_solve_falls_back_to_heuristic_over_n_exact(self):
        """|回収可能R| > N_exact でヒューリスティックに自動フォールバック。"""
        G = grid_graph(4)
        many = [
            reward(u, v, 1 + i)
            for i, (u, v) in enumerate(
                [(0, 1), (1, 2), (2, 3), (4, 5), (5, 6), (6, 7)]
            )
        ]
        cands = solve(G, many, s=0, t=15, limit=5000.0, n_exact=3, time_limit_sec=5.0)
        assert cands[0].reward > 0
        for c in cands:
            validate_route(G, c, s=0, t=15, limit=5000.0)


class TestModeS:
    def test_spur_reward_unreachable_without_edge_reuse(self):
        """行き止まりの報酬はモードSでは回収できない（モードRでは可能）。"""
        G = line_graph(3)
        r = [reward(1, 2, 7)]

        mode_r = solve(G, r, s=0, t=0, limit=400.0, mode="R")[0]
        assert mode_r.reward == 7

        mode_s = solve(G, r, s=0, t=0, limit=400.0, mode="S")[0]
        assert mode_s.reward == 0  # 修復で報酬エッジを諦め、直行解に帰着
        validate_route(G, mode_s, s=0, t=0, limit=400.0, forbid_repeated_edges=True)

    def test_collects_reward_via_cycle(self):
        """迂回路があればエッジ重複なしで回収できる。"""
        # 正方形サイクル 0-1-2-3-0、s=t=0、報酬は (2,3)
        G = nx.MultiGraph(crs="epsg:4326")
        for i, (x, y) in enumerate(
            [(135.75, 34.99), (135.751, 34.99), (135.751, 34.991), (135.75, 34.991)]
        ):
            G.add_node(i, x=x, y=y)
        for u, v in [(0, 1), (1, 2), (2, 3), (3, 0)]:
            G.add_edge(u, v, key=0, length=100.0)

        cands = solve(G, [reward(2, 3, 9)], s=0, t=0, limit=400.0, mode="S")
        best = cands[0]
        assert best.reward == 9
        assert best.length == pytest.approx(400.0)
        validate_route(G, best, s=0, t=0, limit=400.0, forbid_repeated_edges=True)

    def test_repair_drops_infeasible_reward_keeps_others(self):
        """重複を強いる報酬エッジだけをスキップし、他は回収する（修復）。"""
        # 0-1-3-4 の道 + 1-2 のスパー。s=0, t=4。
        # スパー先の報酬(1,2)は trail では回収不能、(3,4) は回収可能
        G = nx.MultiGraph(crs="epsg:4326")
        for i, (x, y) in enumerate(
            [
                (135.75, 34.99),
                (135.751, 34.99),
                (135.751, 34.991),
                (135.752, 34.99),
                (135.753, 34.99),
            ]
        ):
            G.add_node(i, x=x, y=y)
        for u, v in [(0, 1), (1, 2), (1, 3), (3, 4)]:
            G.add_edge(u, v, key=0, length=100.0)
        rewards = [reward(1, 2, 100), reward(3, 4, 5)]

        cands = solve(G, rewards, s=0, t=4, limit=1000.0, mode="S")
        best = cands[0]
        assert {r.edge_id for r in best.collected} == {(3, 4, 0)}
        validate_route(G, best, s=0, t=4, limit=1000.0, forbid_repeated_edges=True)

    def test_all_candidates_are_trails(self):
        """受入基準: モードSの解にエッジ重複がないことを検証コードで確認。"""
        G = grid_graph(5)
        rewards = [
            reward(0, 1, 10),
            reward(6, 11, 25),
            reward(17, 18, 40),
            reward(23, 24, 15),
            reward(2, 7, 30),
        ]
        cands = solve(G, rewards, s=0, t=24, limit=1600.0, mode="S", k=5)
        assert cands
        for c in cands:
            validate_route(G, c, s=0, t=24, limit=1600.0, forbid_repeated_edges=True)
            assert len(set(c.edges)) == len(c.edges)

    def test_mode_s_reward_not_worse_than_direct(self):
        G = grid_graph(5)
        rewards = [reward(6, 11, 25), reward(17, 18, 40)]
        best = solve(G, rewards, s=0, t=24, limit=1200.0, mode="S")[0]
        assert best.reward >= 40  # 少なくとも大きい方は回収できる盤面


class TestAcceptancePhase3:
    def test_30_rewards_within_time_budget(self):
        """受入基準: 報酬30本でも90秒以内（テストでは10秒予算で確認）。"""
        G = grid_graph(10)
        rewards = []
        for idx in range(30):
            i, j = divmod(idx, 6)
            u = (i + 1) * 10 + j + 1
            v = u + 1 if idx % 2 == 0 else u + 10
            rewards.append(reward(u, v, 5 + idx % 23))
        assert len({r.edge_id for r in rewards}) == 30

        t0 = time.monotonic()
        cands = solve(
            G, rewards, s=0, t=99, limit=3000.0,
            n_exact=14, time_limit_sec=10.0, k=3,
        )
        elapsed = time.monotonic() - t0

        assert elapsed < 90.0
        assert cands[0].reward > 0
        sets = [frozenset(r.edge_id for r in c.collected) for c in cands]
        assert len(sets) == len(set(sets))
        for c in cands:
            validate_route(G, c, s=0, t=99, limit=3000.0)
