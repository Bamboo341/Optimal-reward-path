"""Streamlit AppTest によるスモークテスト（UI一式が例外なく描画できること）。"""

from pathlib import Path

import pytest
from conftest import make_synthetic_graph
from streamlit.testing.v1 import AppTest

import src.graph_loader

APP_PATH = str(Path(__file__).resolve().parent.parent / "app.py")


@pytest.fixture
def patched_graph(monkeypatch):
    from src.graph_loader import to_undirected

    G = to_undirected(make_synthetic_graph())
    monkeypatch.setattr(src.graph_loader, "load_graph", lambda *a, **k: G)
    return G


def test_reward_page_renders(patched_graph):
    at = AppTest.from_file(APP_PATH, default_timeout=30)
    at.run()
    assert not at.exception
    assert at.sidebar.radio[0].value == "報酬設定"
    # 報酬未設定時の案内が表示される
    assert any("地図をクリック" in str(el.value) for el in at.sidebar.info)


def test_mode_switch_to_route_search(patched_graph):
    at = AppTest.from_file(APP_PATH, default_timeout=30).run()
    at.sidebar.radio[0].set_value("経路探索").run()
    assert not at.exception
    assert any("Phase 2" in str(el.value) for el in at.info)
