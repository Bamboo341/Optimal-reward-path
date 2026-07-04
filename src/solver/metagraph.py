"""メタグラフ構築・メタノード間最短距離の前計算（SPEC.md §5.1）。

メタノード集合 = { s, t } ∪ { 全報酬エッジの両端点 }。
各メタノードから元グラフ上で Dijkstra を実行し、メタノード間の
最短距離と最短経路（ノード列）を前計算して保持する。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import networkx as nx

from src.rewards import RewardEdge

INF = math.inf


@dataclass
class MetaGraph:
    meta_nodes: list[int]
    _dist: dict[int, dict[int, float]]
    _path: dict[int, dict[int, list[int]]]

    def d(self, x: int, y: int) -> float:
        """メタノード x, y 間の最短距離。到達不能なら inf。"""
        return self._dist.get(x, {}).get(y, INF)

    def path(self, x: int, y: int) -> list[int] | None:
        """メタノード x から y への最短経路のノード列。到達不能なら None。"""
        return self._path.get(x, {}).get(y)


def build_metagraph(
    G: nx.MultiGraph, s: int, t: int, rewards: list[RewardEdge]
) -> MetaGraph:
    meta = {s, t}
    for r in rewards:
        meta.add(r.u)
        meta.add(r.v)

    missing = sorted(x for x in meta if x not in G)
    if missing:
        raise ValueError(f"メタノードがグラフに存在しません: {missing}")

    meta_nodes = sorted(meta)
    dist: dict[int, dict[int, float]] = {}
    path: dict[int, dict[int, list[int]]] = {}
    for x in meta_nodes:
        d_all, p_all = nx.single_source_dijkstra(G, x, weight="length")
        dist[x] = {y: d_all[y] for y in meta_nodes if y in d_all}
        path[x] = {y: p_all[y] for y in meta_nodes if y in p_all}
    return MetaGraph(meta_nodes, dist, path)
