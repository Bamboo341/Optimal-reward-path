"""報酬設定画面（SPEC.md §7.1）。

操作フロー:
1. 地図上の任意点をクリック（クリック位置に小さな丸を表示）
2. 最近傍エッジを青色でプレビュー表示し、道路名をサイドバーに表示
3. サイドバーで報酬値（正整数）とメモを入力し「設定」で即時JSON保存

設定済みエッジの一覧・個別削除・報酬値の変更も本画面で行う。
選択可能な道路はグレーの下敷きとして表示できる（誤クリック対策）。
"""

from __future__ import annotations

import networkx as nx
import streamlit as st

from src.config import Config
from src.graph_loader import edge_road_name, nearest_edge
from src.rewards import RewardsFileError, RewardStore, rewards_path
from src.ui.map_state import new_click, render_map
from src.ui.map_view import MAX_OVERLAY_EDGES, reward_feature_group

_PREVIEW_KEY = "reward_preview_edge"
_CLICK_KEY = "reward_clicked_latlng"


def render(G: nx.MultiGraph, config: Config) -> None:
    st.header("報酬設定")

    try:
        store, skipped = RewardStore.open(
            rewards_path(config.place, config.data_dir), config.place, graph=G
        )
    except RewardsFileError as exc:
        st.error(f"{exc}\n\nファイルを修正または削除してから再読み込みしてください。")
        return
    if skipped:
        ids = ", ".join(str(r.edge_id) for r in skipped)
        st.warning(
            f"グラフに存在しない報酬エッジ {len(skipped)} 件をスキップしました: {ids}"
        )

    overlay_allowed = G.number_of_edges() <= MAX_OVERLAY_EDGES
    show_roads = st.checkbox(
        "選択可能な道路をグレーで表示",
        value=overlay_allowed,
        disabled=not overlay_allowed,
        help="クリックで選択できる道路の位置が分かります",
    )
    if not overlay_allowed:
        st.caption(
            f"エッジ数が多いため下敷き表示は無効です"
            f"（{G.number_of_edges():,} > {MAX_OVERLAY_EDGES:,}）"
        )

    preview = st.session_state.get(_PREVIEW_KEY)
    fg = reward_feature_group(
        G,
        store.all(),
        preview_edge=preview,
        clicked=st.session_state.get(_CLICK_KEY),
    )
    out = render_map(G, fg, key="reward_map", selectable_overlay=show_roads)

    _handle_click(G, out)
    _render_sidebar_form(G, store, preview)
    _render_reward_list(store)


def _handle_click(G: nx.MultiGraph, out: dict | None) -> None:
    """新しいクリックのみ処理する（他のウィジェット操作の再実行では反応しない）。"""
    latlng = new_click(out, "reward")
    if latlng is None:
        return
    st.session_state[_CLICK_KEY] = latlng
    st.session_state[_PREVIEW_KEY] = nearest_edge(G, lat=latlng[0], lng=latlng[1])
    st.rerun()


def _render_sidebar_form(G: nx.MultiGraph, store: RewardStore, preview) -> None:
    with st.sidebar:
        st.subheader("報酬の設定")
        if preview is None:
            st.info("地図をクリックすると最近傍の道路エッジを選択できます。")
            return

        u, v, key = preview
        road = edge_road_name(G, u, v, key) or "(名称なし)"
        st.markdown(f"**選択中**: {road}")
        st.caption(f"エッジ (u={u}, v={v}, key={key})")

        existing = store.get(u, v, key)
        reward = st.number_input(
            "報酬値（正整数）",
            min_value=1,
            step=1,
            value=existing.reward if existing else 10,
        )
        memo = st.text_input("メモ", value=existing.memo if existing else "")

        if st.button("設定", type="primary"):
            store.set(
                u, v, key,
                reward=int(reward),
                memo=memo,
                road_name=edge_road_name(G, u, v, key),
            )
            st.success("保存しました")
            st.rerun()


def _render_reward_list(store: RewardStore) -> None:
    rewards = store.all()
    st.subheader(f"設定済み報酬エッジ（{len(rewards)}件）")
    if not rewards:
        st.caption("まだ報酬エッジがありません。地図をクリックして設定してください。")
        return

    header = st.columns([3, 2, 3, 1, 1])
    header[0].markdown("**道路名 / エッジ**")
    header[1].markdown("**報酬値**")
    header[2].markdown("**メモ**")

    for r in rewards:
        eid = f"{r.u}_{r.v}_{r.key}"
        cols = st.columns([3, 2, 3, 1, 1])
        cols[0].markdown(f"{r.road_name or '(名称なし)'}")
        cols[0].caption(f"({r.u}, {r.v}, {r.key})")
        new_reward = cols[1].number_input(
            "報酬値",
            min_value=1,
            step=1,
            value=r.reward,
            key=f"reward_input_{eid}",
            label_visibility="collapsed",
        )
        cols[2].write(r.memo or "—")
        if cols[3].button("更新", key=f"update_{eid}"):
            store.set(r.u, r.v, r.key, reward=int(new_reward), memo=r.memo, road_name=r.road_name)
            st.rerun()
        if cols[4].button("削除", key=f"delete_{eid}"):
            store.remove(r.u, r.v, r.key)
            st.rerun()
