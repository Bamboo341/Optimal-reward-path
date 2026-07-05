"""経路探索画面（SPEC.md §7.2）。

- 出発点・到着点: 地図クリック → 最近傍ノードにスナップ（マーカー表示）
- 距離上限 L・モード・候補数 K を指定して探索実行
- 候補経路は選択した1件のみ地図に表示する（「すべて表示」も選択可能）
"""

from __future__ import annotations

import networkx as nx
import pandas as pd
import streamlit as st

from src.config import Config
from src.export import export_candidates
from src.graph_loader import nearest_node
from src.rewards import RewardsFileError, RewardStore, rewards_path
from src.route import RouteError
from src.solver import SolverError, solve
from src.ui.map_state import new_click, render_map
from src.ui.map_view import route_feature_group

_S_KEY = "route_start_node"
_T_KEY = "route_end_node"
_RESULT_KEY = "route_candidates"
_LIMIT_KEY = "route_limit_used"


def render(G: nx.MultiGraph, config: Config) -> None:
    st.header("経路探索")

    try:
        store, _ = RewardStore.open(
            rewards_path(config.place, config.data_dir), config.place, graph=G
        )
    except RewardsFileError as exc:
        st.error(f"{exc}\n\nファイルを修正または削除してから再読み込みしてください。")
        return
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
    visible = _render_candidate_picker(candidates)

    fg = route_feature_group(
        G, store.all(), s=s, t=t, candidates=candidates, visible=visible
    )
    out = render_map(G, fg, key="route_map")
    _handle_map_interaction(G, out, target)

    _render_result_table(candidates, st.session_state.get(_LIMIT_KEY), visible)
    _render_export_button(G, candidates, config)


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
    except (SolverError, RouteError) as exc:
        st.session_state[_RESULT_KEY] = []
        st.session_state[_LIMIT_KEY] = None
        st.error(str(exc))
        return
    st.session_state[_RESULT_KEY] = candidates
    st.session_state[_LIMIT_KEY] = limit


def _render_candidate_picker(candidates) -> set[int] | None:
    """地図に表示する候補を選ぶ。返り値は候補 index の集合（None は全候補）。"""
    if not candidates:
        return None
    labels = [
        f"候補{i + 1}（報酬{c.reward} / {c.length:.0f}m）"
        for i, c in enumerate(candidates)
    ]
    options = labels + ["すべて表示"] if len(candidates) > 1 else labels
    choice = st.radio("地図に表示する候補", options, horizontal=True)
    if choice == "すべて表示":
        return None
    return {options.index(choice)}


def _handle_map_interaction(G, out, target: str) -> None:
    """新しいクリックのみ処理する（古いクリックの再適用を防ぐ）。"""
    latlng = new_click(out, "route")
    if latlng is None:
        return
    node = nearest_node(G, lat=latlng[0], lng=latlng[1])
    key = _S_KEY if target == "出発点" else _T_KEY
    st.session_state[key] = node
    st.rerun()


def _render_result_table(candidates, limit, visible: set[int] | None) -> None:
    if not candidates:
        st.caption(
            "出発点・到着点を設定して「探索実行」を押すと、候補経路を表示します。"
        )
        return

    st.subheader(f"候補経路（{len(candidates)}件）")
    rows = []
    for i, c in enumerate(candidates):
        shown = visible is None or i in visible
        rows.append(
            {
                "候補": f"候補{i + 1}",
                "地図表示": "表示中" if shown else "",
                "総報酬": c.reward,
                "総距離 (m)": round(c.length, 1),
                "距離上限使用率 (%)": round(c.length / limit * 100, 1) if limit else None,
                "回収報酬エッジ数": len(c.collected),
            }
        )
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)


def _render_export_button(G, candidates, config) -> None:
    if not candidates:
        return
    if st.button("GeoJSONエクスポート（output/ に保存）"):
        try:
            path = export_candidates(G, candidates, config.output_dir)
        except OSError as exc:
            st.error(f"エクスポートに失敗しました: {exc}")
        else:
            st.success(f"エクスポートしました: {path}")
