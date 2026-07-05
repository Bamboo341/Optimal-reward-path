"""st_folium 呼び出しのラッパ（地図の再マウント防止とクリック処理）。

streamlit-folium はコンポーネント引数（ベース地図のHTML等）が前回と
変わるとコンポーネントを再マウントし、ズーム・表示位置がリセットされる。
これを防ぐための構成:

1. ベース地図は毎回新規に構築する。folium のランダムIDは streamlit-folium
   側で正規化されるため、内容が同じなら引数は完全に一致し再マウントは
   起きない（使い回すと streamlit-folium 内部の構造変更が蓄積して逆に
   毎回変わってしまう）
2. 変化する内容（報酬エッジ・マーカー・経路）は feature_group_to_add で
   渡し、地図の再読込なしでレイヤーだけ差し替える
3. returned_objects をクリック系のみに絞る
   （ズーム・パン操作では Streamlit の再実行自体が起きない）
"""

from __future__ import annotations

import folium
import networkx as nx
import streamlit as st
from streamlit_folium import st_folium

from src.ui.map_view import create_base_map


def render_map(
    G: nx.MultiGraph,
    feature_group: folium.FeatureGroup,
    key: str,
    selectable_overlay: bool = False,
) -> dict:
    """ベース地図＋可変レイヤーを描画し、クリック情報を返す。"""
    base = create_base_map(G, selectable_overlay=selectable_overlay)
    return st_folium(
        base,
        feature_group_to_add=feature_group,
        height=560,
        use_container_width=True,
        key=key,
        # 地図クリックに加え、報酬エッジ等のオブジェクト上のクリックも受ける
        returned_objects=["last_clicked", "last_object_clicked"],
    )


def new_click(out: dict | None, page_key: str) -> tuple[float, float] | None:
    """未処理の新しいクリック位置 (lat, lng) を返す。なければ None。

    st_folium は最後のクリックを再実行のたびに返し続けるため、処理済みの
    値をセッションに記録して比較する（放置すると、ラジオ切替など無関係な
    操作で古いクリックが再適用されてしまう）。地図上のクリックと
    オブジェクト（報酬エッジ等）上のクリックを両方受ける。
    """
    for field in ("last_clicked", "last_object_clicked"):
        value = (out or {}).get(field)
        if not value:
            continue
        latlng = (value["lat"], value["lng"])
        state_key = f"__click::{page_key}::{field}"
        if latlng != st.session_state.get(state_key):
            st.session_state[state_key] = latlng
            return latlng
    return None
