from pathlib import Path

import pytest

from src.config import Config, load_config


def test_defaults_when_file_missing(tmp_path: Path):
    config = load_config(tmp_path / "no_such.yaml")
    assert config == Config()
    assert config.place == "Shimogyo-ku, Kyoto, Japan"
    assert config.n_exact == 14
    assert config.time_limit_sec == 90
    assert config.k_default == 3


def test_loads_overrides(tmp_path: Path):
    path = tmp_path / "config.yaml"
    path.write_text(
        'place: "Kyoto, Japan"\nn_exact: 10\nk_default: 5\n', encoding="utf-8"
    )
    config = load_config(path)
    assert config.place == "Kyoto, Japan"
    assert config.n_exact == 10
    assert config.k_default == 5
    # 未指定キーは既定値のまま
    assert config.time_limit_sec == 90


def test_unknown_key_raises(tmp_path: Path):
    path = tmp_path / "config.yaml"
    path.write_text("plce: typo\n", encoding="utf-8")
    with pytest.raises(ValueError, match="不明な設定キー"):
        load_config(path)


def test_non_mapping_yaml_raises(tmp_path: Path):
    path = tmp_path / "config.yaml"
    path.write_text("- a\n- b\n", encoding="utf-8")
    with pytest.raises(ValueError, match="マッピング"):
        load_config(path)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"place": "  "},
        {"n_exact": 0},
        {"time_limit_sec": 0},
        {"k_default": 0},
        {"k_default": 6},
    ],
)
def test_invalid_values_raise(kwargs):
    with pytest.raises(ValueError):
        Config(**kwargs)


def test_repo_config_yaml_is_valid():
    """リポジトリ直下の config.yaml が読み込めること。"""
    repo_config = Path(__file__).resolve().parent.parent / "config.yaml"
    config = load_config(repo_config)
    assert config.place == "Shimogyo-ku, Kyoto, Japan"
