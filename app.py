"""Streamlit エントリポイント。

サイドバーで「報酬設定」「経路探索」の2モードを切り替える（docs/SPEC.md §7）。
"""

import streamlit as st

from src.config import load_config
from src.graph_loader import GraphLoadError, load_graph
from src.ui import reward_editor, route_search


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

    mode = st.sidebar.radio("画面", ("報酬設定", "経路探索"))
    st.sidebar.caption(
        f"{config.place}\nノード {G.number_of_nodes():,} / エッジ {G.number_of_edges():,}"
    )
    st.sidebar.divider()

    if mode == "報酬設定":
        reward_editor.render(G, config)
    else:
        route_search.render(G, config)


if __name__ == "__main__":
    main()
