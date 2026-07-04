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


def test_route_search_page_renders(patched_graph):
    at = AppTest.from_file(APP_PATH, default_timeout=30).run()
    at.sidebar.radio[0].set_value("経路探索").run()
    assert not at.exception
    # 出発点・到着点が未設定なので探索実行は無効、案内が表示される
    assert any("探索実行" in str(b.label) for b in at.sidebar.button)
    assert any("未設定" in str(el.value) for el in at.sidebar.caption)


def test_route_search_executes_solver(patched_graph):
    at = AppTest.from_file(APP_PATH, default_timeout=30).run()
    at.sidebar.radio[0].set_value("経路探索").run()
    # 地図クリックの代わりに session_state で出発点・到着点を設定
    at.session_state["route_start_node"] = 1
    at.session_state["route_end_node"] = 3
    at.run()
    button = next(b for b in at.sidebar.button if "探索実行" in str(b.label))
    button.click().run()
    assert not at.exception
    assert len(at.dataframe) == 1  # 候補経路の表が表示される


def test_corrupted_rewards_file_shows_error_not_crash(patched_graph, monkeypatch, tmp_path):
    import src.config
    from src.config import Config
    from src.rewards import rewards_path

    config = Config(data_dir=str(tmp_path), output_dir=str(tmp_path / "out"))
    monkeypatch.setattr(src.config, "load_config", lambda *a, **k: config)
    rewards_path(config.place, tmp_path).write_text("{ こわれた", encoding="utf-8")

    at = AppTest.from_file(APP_PATH, default_timeout=30).run()
    assert not at.exception
    assert any("壊れて" in str(e.value) for e in at.error)


def test_broken_config_shows_error_not_crash(monkeypatch):
    import src.config

    def broken(*a, **k):
        raise ValueError("不明な設定キーがあります: ['plce']")

    monkeypatch.setattr(src.config, "load_config", broken)
    at = AppTest.from_file(APP_PATH, default_timeout=30).run()
    assert not at.exception
    assert any("config.yaml" in str(e.value) for e in at.error)


def test_geojson_export_from_route_page(patched_graph, monkeypatch, tmp_path):
    import src.config
    from src.config import Config

    out_dir = tmp_path / "out"
    config = Config(data_dir=str(tmp_path), output_dir=str(out_dir))
    monkeypatch.setattr(src.config, "load_config", lambda *a, **k: config)

    at = AppTest.from_file(APP_PATH, default_timeout=30).run()
    at.sidebar.radio[0].set_value("経路探索").run()
    at.session_state["route_start_node"] = 1
    at.session_state["route_end_node"] = 3
    at.run()
    search = next(b for b in at.sidebar.button if "探索実行" in str(b.label))
    search.click().run()
    export = next(b for b in at.main.button if "GeoJSON" in str(b.label))
    export.click().run()

    assert not at.exception
    files = list(out_dir.glob("*.geojson"))
    assert len(files) == 1
    assert any("エクスポートしました" in str(el.value) for el in at.success)


def test_route_search_shows_error_when_infeasible(patched_graph):
    at = AppTest.from_file(APP_PATH, default_timeout=30).run()
    at.sidebar.radio[0].set_value("経路探索").run()
    at.session_state["route_start_node"] = 1
    at.session_state["route_end_node"] = 3
    at.run()
    # 最短距離より小さい距離上限を指定 → エラー表示
    limit_input = next(
        n for n in at.sidebar.number_input if "距離上限" in str(n.label)
    )
    limit_input.set_value(100).run()
    button = next(b for b in at.sidebar.button if "探索実行" in str(b.label))
    button.click().run()
    assert not at.exception
    assert any("実行可能解がありません" in str(e.value) for e in at.error)
