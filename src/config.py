"""config.yaml の読み込み（SPEC.md §9 / Phase 0）。"""

from __future__ import annotations

from dataclasses import dataclass, fields
from pathlib import Path

import yaml

DEFAULT_CONFIG_PATH = Path("config.yaml")


@dataclass(frozen=True)
class Config:
    place: str = "Shimogyo-ku, Kyoto, Japan"
    network_type: str = "all"
    n_exact: int = 14
    time_limit_sec: int = 90
    k_default: int = 3
    data_dir: str = "data"
    output_dir: str = "output"

    def __post_init__(self) -> None:
        if not self.place or not self.place.strip():
            raise ValueError("place が空です")
        if self.n_exact < 1:
            raise ValueError(f"n_exact は正整数が必要です: {self.n_exact}")
        if self.time_limit_sec < 1:
            raise ValueError(f"time_limit_sec は正整数が必要です: {self.time_limit_sec}")
        if not 1 <= self.k_default <= 5:
            raise ValueError(f"k_default は1〜5が必要です: {self.k_default}")


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> Config:
    """config.yaml を読み込む。ファイルがなければ既定値を返す。"""
    path = Path(path)
    if not path.exists():
        return Config()

    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: キーと値のマッピング形式で記述してください")

    known = {f.name for f in fields(Config)}
    unknown = sorted(set(raw) - known)
    if unknown:
        raise ValueError(f"{path}: 不明な設定キーがあります: {unknown}")

    return Config(**raw)
