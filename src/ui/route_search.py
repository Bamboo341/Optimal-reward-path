"""経路探索画面（SPEC.md §7.2）。

- 出発点・到着点: 地図クリック → 最近傍ノードにスナップ（マーカー表示）
- 距離上限 L・モード・候補数 K を指定して探索実行
- 候補経路を色分けして地図に重畳し、候補ごとの表を表示
"""

from __future__ import annotations

import networkx as nx
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

from src.config import Config
from src.graph_loader import nearest_node
from src.rewards import RewardStore, rewards_path
from src.solver import SolverError, solve
from src.ui.map_view import ROUTE_COLORS, build_route_map

_S_KEY = "route_start_node"
_T_KEY = "route_end_node"
_RESULT_KEY = "route_candidates"
_LIMIT_KEY = "route_limit_used"
_CENTER_KEY = "route_map_center"
_ZOOM_KEY = "route_map_zoom"


def render(G: nx.MultiGraph, config: Config) -> None:
    st.header("経路探索")

    store, _ = RewardStore.open(
        rewards_path(config.place, config.data_dir), config.place, graph=G
    )
    s = st.session_state.get(_S_KEY)
    t = st.session_state.get(_T_KEY)

    with st.sidebar:
        st.subheader("探索条件")
        target = st.radio("地図クリックで設定する点", ("出発点", "到着点"))
        st.caption(
            f"出発点: {'ノード ' + str(s) if s is not None else '未設定'} / "
            f"到着点: {'ノード ' + str(t) if t is not None else '未設定'}"
        )
        limit = st.number_input(
            "距離上限 L（メートル）", min_value=100, value=5000, step=100
        )
        mode_label = st.radio(
            "モード",
            ("再訪許可（歩道）", "再訪禁止（小道）"),
            help="再訪禁止では同一の道路エッジを2度通らない経路のみを探索します",
        )
        mode = "R" if mode_label.startswith("再訪許可") else "S"
        k = st.slider("候補数 K", min_value=1, max_value=5, value=config.k_default)
        run = st.button(
            "探索実行",
            type="primary",
            disabled=(s is None or t is None),
            help="出発点と到着点を地図クリックで設定すると実行できます",
        )

    if run:
        _run_search(G, store, s, t, float(limit), int(k), mode, config)

    candidates = st.session_state.get(_RESULT_KEY, [])
    m = build_route_map(
        G,
        store.all(),
        s=s,
        t=t,
        candidates=candidates,
        center=st.session_state.get(_CENTER_KEY),
        zoom=st.session_state.get(_ZOOM_KEY, 15),
    )
    out = st_folium(
        m,
        height=560,
        use_container_width=True,
        key="route_map",
        returned_objects=["last_clicked", "center", "zoom"],
    )
    _handle_map_interaction(G, out, target)

    _render_result_table(candidates, st.session_state.get(_LIMIT_KEY))


def _run_search(G, store, s, t, limit, k, mode, config) -> None:
    rewards = store.all()
    try:
        with st.spinner("経路を探索中..."):
            candidates = solve(
                G,
                rewards,
                s,
                t,
                limit,
                k=k,
                n_exact=config.n_exact,
                mode=mode,
                time_limit_sec=config.time_limit_sec,
            )
    except SolverError as exc:
        st.session_state[_RESULT_KEY] = []
        st.session_state[_LIMIT_KEY] = None
        st.error(str(exc))
        return
    st.session_state[_RESULT_KEY] = candidates
    st.session_state[_LIMIT_KEY] = limit


def _handle_map_interaction(G, out, target: str) -> None:
    if not out:
        return
    center = out.get("center")
    if center:
        st.session_state[_CENTER_KEY] = (center["lat"], center["lng"])
    if out.get("zoom"):
        st.session_state[_ZOOM_KEY] = out["zoom"]

    clicked = out.get("last_clicked")
    if not clicked:
        return
    node = nearest_node(G, lat=clicked["lat"], lng=clicked["lng"])
    key = _S_KEY if target == "出発点" else _T_KEY
    if st.session_state.get(key) != node:
        st.session_state[key] = node
        st.rerun()


def _render_result_table(candidates, limit) -> None:
    if not candidates:
        st.caption(
            "出発点・到着点を設定して「探索実行」を押すと、候補経路を表示します。"
        )
        return

    st.subheader(f"候補経路（{len(candidates)}件）")
    rows = []
    for i, c in enumerate(candidates):
        rows.append(
            {
                "候補": f"候補{i + 1}",
                "総報酬": c.reward,
                "総距離 (m)": round(c.length, 1),
                "距離上限使用率 (%)": round(c.length / limit * 100, 1) if limit else None,
                "回収報酬エッジ数": len(c.collected),
            }
        )
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
    st.caption(
        "地図の色: "
        + " / ".join(
            f"候補{i + 1}={ROUTE_COLORS[i % len(ROUTE_COLORS)]}"
            for i in range(len(candidates))
        )
        + "（レイヤーコントロールで表示/非表示を切替できます）"
    )
