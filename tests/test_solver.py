"""ソルバーのテスト（SPEC.md §11）。

合成グリッドグラフで最適解が既知のケースを検証し、さらに独立実装の
ブルートフォース（順列全列挙）とビットマスクDPの結果を照合する。
"""

import itertools
import math

import networkx as nx
import pytest

from src.rewards import RewardEdge
from src.route import RouteError, build_route, recount_reward, validate_route
from src.solver import SolverError, solve
from src.solver.exact_dp import solve_exact
from src.solver.metagraph import build_metagraph

INF = math.inf


def grid_graph(n: int, edge_len: float = 100.0) -> nx.MultiGraph:
    """n×n の格子グラフ（全エッジ長 edge_len、ノードID = i*n + j）。"""
    G = nx.MultiGraph(crs="epsg:4326")
    for i in range(n):
        for j in range(n):
            G.add_node(i * n + j, x=135.75 + j * 0.001, y=34.99 + i * 0.001)
    for i in range(n):
        for j in range(n):
            u = i * n + j
            if j < n - 1:
                G.add_edge(u, u + 1, key=0, length=edge_len)
            if i < n - 1:
                G.add_edge(u, u + n, key=0, length=edge_len)
    return G


def line_graph(n: int, edge_len: float = 100.0) -> nx.MultiGraph:
    G = nx.MultiGraph(crs="epsg:4326")
    for i in range(n):
        G.add_node(i, x=135.75 + i * 0.001, y=34.99)
    for i in range(n - 1):
        G.add_edge(i, i + 1, key=0, length=edge_len)
    return G


def reward(u, v, p, key=0):
    return RewardEdge(u=u, v=v, key=key, reward=p)


class TestMetagraph:
    def test_distances_and_paths(self):
        G = grid_graph(5)
        rewards = [reward(6, 7, 10)]
        meta = build_metagraph(G, s=0, t=24, rewards=rewards)

        assert sorted(meta.meta_nodes) == [0, 6, 7, 24]
        assert meta.d(0, 24) == pytest.approx(800.0)  # 対角: 8エッジ
        assert meta.d(0, 6) == pytest.approx(200.0)
        assert meta.d(7, 24) == pytest.approx(500.0)
        # 経路はノード列として復元でき、距離と整合する
        path = meta.path(0, 24)
        assert path[0] == 0 and path[-1] == 24
        assert len(path) == 9

    def test_missing_meta_node_raises(self):
        G = grid_graph(3)
        with pytest.raises(ValueError, match="存在しません"):
            build_metagraph(G, s=0, t=999, rewards=[])


class TestKnownOptima:
    """最適解が手計算で既知のケース（SPEC §11 DPの正当性確認）。"""

    def test_reward_on_direct_path(self):
        # 直線 0-1-2-3-4。報酬エッジ(1,2)は最短経路上にあり、L=400で回収できる
        G = line_graph(5)
        cands = solve(G, [reward(1, 2, 5)], s=0, t=4, limit=400.0)

        best = cands[0]
        assert best.reward == 5
        assert best.length == pytest.approx(400.0)
        assert best.nodes == (0, 1, 2, 3, 4)

    def test_spur_requires_backtrack_reward_counted_once(self):
        # 直線 0-1-2 で s=t=0。行き止まりの報酬エッジ(1,2)を回収して戻る。
        # 同一報酬エッジを2回通過するが報酬は1回のみ加算（SPEC §4, §11）
        G = line_graph(3)
        cands = solve(G, [reward(1, 2, 7)], s=0, t=0, limit=400.0)

        best = cands[0]
        assert best.reward == 7
        assert best.length == pytest.approx(400.0)
        assert best.nodes == (0, 1, 2, 1, 0)
        # エッジ(1,2)を2回通過している
        assert best.edges.count((1, 2, 0)) == 2
        assert len(best.collected) == 1

    def test_conflicting_rewards_within_budget(self):
        # 3×3格子 s=0, t=8（対角、最短400）。
        # 報酬A=(0,1) と 報酬B=(3,6) は単調経路では両立しない。
        G = grid_graph(3)
        rewards = [reward(0, 1, 3), reward(3, 6, 7)]

        # L=400: どちらか一方のみ回収可能 → 報酬が大きいBを選ぶ
        best = solve(G, rewards, s=0, t=8, limit=400.0)[0]
        assert best.reward == 7
        assert best.length == pytest.approx(400.0)

        # L=600: 両方回収できる（0→1→0→3→6→7→8 で600）
        best = solve(G, rewards, s=0, t=8, limit=600.0)[0]
        assert best.reward == 10
        assert best.length == pytest.approx(600.0)

    def test_no_rewards_returns_direct_path(self):
        G = grid_graph(3)
        cands = solve(G, [], s=0, t=8, limit=1000.0)
        assert len(cands) == 1
        assert cands[0].reward == 0
        assert cands[0].length == pytest.approx(400.0)

    def test_infeasible_raises(self):
        G = grid_graph(3)
        with pytest.raises(SolverError, match="実行可能解がありません"):
            solve(G, [], s=0, t=8, limit=300.0)

    def test_unreachable_reward_is_ignored(self):
        # 距離上限内で回収不能な報酬エッジがあっても直行解は返る
        G = grid_graph(5)
        far = reward(15, 20, 100)  # 左下側の縦エッジ
        cands = solve(G, [far], s=0, t=4, limit=400.0)
        assert cands[0].reward == 0
        assert cands[0].length == pytest.approx(400.0)


class TestAgainstBruteForce:
    """独立実装のブルートフォース（部分集合×順列×方向の全列挙）と照合する。"""

    @staticmethod
    def brute_force(meta, rewards, lengths, s, t, limit):
        """(最大報酬, その最小総距離) を返す。"""
        n = len(rewards)
        best_reward, best_len = 0, meta.d(s, t)
        for size in range(1, n + 1):
            for subset in itertools.combinations(range(n), size):
                for perm in itertools.permutations(subset):
                    for orients in itertools.product((0, 1), repeat=size):
                        cur, total = s, 0.0
                        for idx, o in zip(perm, orients):
                            r = rewards[idx]
                            e_in, e_out = ((r.u, r.v), (r.v, r.u))[o]
                            total += meta.d(cur, e_in) + lengths[idx]
                            cur = e_out
                        total += meta.d(cur, t)
                        if total <= limit + 1e-6:
                            p = sum(rewards[i].reward for i in subset)
                            if p > best_reward or (
                                p == best_reward and total < best_len - 1e-6
                            ):
                                best_reward, best_len = p, total
        return best_reward, best_len

    @pytest.mark.parametrize("limit", [400.0, 800.0, 1000.0, 1400.0, 2400.0])
    def test_dp_matches_brute_force_on_grid(self, limit):
        G = grid_graph(5)
        rewards = [
            reward(0, 1, 10),
            reward(6, 11, 25),
            reward(17, 18, 40),
            reward(23, 24, 15),
        ]
        s, t = 0, 24
        meta = build_metagraph(G, s, t, rewards)
        lengths = [100.0] * len(rewards)

        expect_reward, expect_len = self.brute_force(
            meta, rewards, lengths, s, t, limit
        )

        plans = solve_exact(meta, rewards, lengths, s, t, limit, k=1)
        if expect_reward == 0:
            assert plans == [] or plans[0].planned_reward == 0
        else:
            assert plans[0].planned_reward == expect_reward
            assert plans[0].planned_length == pytest.approx(expect_len)


class TestRouteBuilding:
    def test_incidental_reward_recounted(self):
        # 接続部で偶然通過した報酬エッジも加算する（SPEC §5.2）
        G = line_graph(5)
        r_far = reward(3, 4, 100)
        r_incidental = reward(0, 1, 1)
        rewards = [r_far, r_incidental]
        meta = build_metagraph(G, 0, 4, rewards)

        # 計画は r_far のみだが、実経路 0→4 は (0,1) も通過する
        route = build_route(G, meta, rewards, order=((0, 0),), s=0, t=4)
        assert route.reward == 101
        assert {r.edge_id for r in route.collected} == {(3, 4, 0), (0, 1, 0)}

    def test_recount_deduplicates(self):
        r = reward(1, 2, 7)
        total, collected = recount_reward([(1, 2, 0), (1, 2, 0)], [r])
        assert total == 7
        assert collected == (r,)


class TestValidateRoute:
    @pytest.fixture
    def valid_route(self):
        G = grid_graph(3)
        cands = solve(G, [reward(0, 1, 3)], s=0, t=8, limit=600.0)
        return G, cands[0]

    def test_valid_route_passes(self, valid_route):
        G, route = valid_route
        validate_route(G, route, s=0, t=8, limit=600.0)

    def test_wrong_endpoints_fail(self, valid_route):
        G, route = valid_route
        with pytest.raises(RouteError, match="接続していません"):
            validate_route(G, route, s=1, t=8, limit=600.0)

    def test_over_limit_fails(self, valid_route):
        G, route = valid_route
        with pytest.raises(RouteError, match="距離上限"):
            validate_route(G, route, s=0, t=8, limit=route.length - 1)

    def test_mode_s_detects_repeated_edges(self):
        # スパー往復経路はモードS条件に違反する
        G = line_graph(3)
        route = solve(G, [reward(1, 2, 7)], s=0, t=0, limit=400.0)[0]
        validate_route(G, route, s=0, t=0, limit=400.0)  # モードRではOK
        with pytest.raises(RouteError, match="モードS違反"):
            validate_route(
                G, route, s=0, t=0, limit=400.0, forbid_repeated_edges=True
            )


class TestSolveCandidates:
    def test_candidates_have_distinct_collected_sets(self):
        G = grid_graph(5)
        rewards = [reward(0, 1, 10), reward(6, 11, 25), reward(17, 18, 40)]
        cands = solve(G, rewards, s=0, t=24, limit=1400.0, k=5)

        sets = [frozenset(r.edge_id for r in c.collected) for c in cands]
        assert len(sets) == len(set(sets))
        # 報酬降順（同報酬なら距離昇順）
        assert all(
            (a.reward, -a.length) >= (b.reward, -b.length)
            for a, b in zip(cands, cands[1:])
        )
        # 全候補が実行可能解
        for c in cands:
            validate_route(G, c, s=0, t=24, limit=1400.0)

    def test_too_many_rewards_raises_until_phase3(self):
        G = grid_graph(4)
        many = [
            reward(u, v, 1, key=0)
            for u, v in [(0, 1), (1, 2), (2, 3), (4, 5), (5, 6), (6, 7)]
        ]
        with pytest.raises(SolverError, match="N_exact"):
            solve(G, many, s=0, t=15, limit=5000.0, n_exact=3)

    def test_mode_s_not_implemented_yet(self):
        G = grid_graph(3)
        with pytest.raises(SolverError, match="未実装"):
            solve(G, [], s=0, t=8, limit=1000.0, mode="S")
