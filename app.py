"""Streamlit エントリポイント。

Phase 0 時点ではグラフ読込の確認画面のみ。報酬設定・経路探索の画面は
Phase 1 以降で追加する（docs/SPEC.md §7, §10）。
"""

import streamlit as st

from src.config import load_config
from src.graph_loader import GraphLoadError, load_graph


@st.cache_resource(show_spinner="道路ネットワークを読み込み中...")
def get_graph(place: str, network_type: str, data_dir: str):
    return load_graph(place, network_type=network_type, data_dir=data_dir)


def main() -> None:
    st.set_page_config(page_title="OSM報酬最大化経路探索", layout="wide")
    st.title("OSM報酬最大化経路探索")

    config = load_config()

    try:
        G = get_graph(config.place, config.network_type, config.data_dir)
    except GraphLoadError as exc:
        st.error(str(exc))
        st.stop()
        return

    st.success(f"グラフ読込完了: {config.place}")
    col1, col2 = st.columns(2)
    col1.metric("ノード数", f"{G.number_of_nodes():,}")
    col2.metric("エッジ数", f"{G.number_of_edges():,}")
    st.caption("Phase 0: 基盤のみ。報酬設定・経路探索は今後のPhaseで追加予定。")


if __name__ == "__main__":
    main()
