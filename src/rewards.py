"""報酬データのCRUD・永続化（SPEC.md §6.1 / Phase 1）。

保存形式:
{
  "version": 1,
  "place": "Shimogyo-ku, Kyoto, Japan",
  "rewards": [{"u": ..., "v": ..., "key": ..., "reward": ..., "memo": ..., "road_name": ...}]
}
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path

import networkx as nx

from src.graph_loader import place_slug

logger = logging.getLogger(__name__)

FORMAT_VERSION = 1

EdgeId = tuple[int, int, int]


class RewardsFileError(RuntimeError):
    """報酬ファイルが壊れている・形式が不正なときに送出する。"""


def rewards_path(place: str, data_dir: str | Path = "data") -> Path:
    return Path(data_dir) / f"rewards_{place_slug(place)}.json"


def normalize_edge_id(u: int, v: int, key: int) -> EdgeId:
    """u < v に正規化したエッジIDを返す（SPEC §3「エッジの同定」）。"""
    return (u, v, key) if u <= v else (v, u, key)


@dataclass(frozen=True)
class RewardEdge:
    u: int
    v: int
    key: int
    reward: int
    memo: str = ""
    road_name: str = ""

    def __post_init__(self) -> None:
        if self.u > self.v:
            u, v = self.u, self.v
            object.__setattr__(self, "u", v)
            object.__setattr__(self, "v", u)
        if not isinstance(self.reward, int) or isinstance(self.reward, bool):
            raise ValueError(f"reward は整数が必要です: {self.reward!r}")
        if self.reward < 1:
            raise ValueError(f"reward は正整数が必要です: {self.reward}")

    @property
    def edge_id(self) -> EdgeId:
        return (self.u, self.v, self.key)


class RewardStore:
    """報酬エッジ集合を保持し、変更を即時にJSONへ書き込む（SPEC §7.1）。"""

    def __init__(self, path: str | Path, place: str, rewards: tuple = ()) -> None:
        self.path = Path(path)
        self.place = place
        self._rewards: dict[EdgeId, RewardEdge] = {r.edge_id: r for r in rewards}

    @classmethod
    def open(
        cls,
        path: str | Path,
        place: str,
        graph: nx.MultiGraph | None = None,
    ) -> tuple["RewardStore", list[RewardEdge]]:
        """JSONを読み込んでストアを返す。

        graph を与えると、グラフに存在しないエッジを警告してスキップする
        （SPEC §6.1: グラフ更新への耐性）。スキップされたエッジは戻り値の
        第2要素で返し、以後の保存では書き戻さない。
        """
        path = Path(path)
        rewards: list[RewardEdge] = []
        skipped: list[RewardEdge] = []
        if path.exists():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                raise RewardsFileError(
                    f"報酬ファイル {path} を読み込めません（JSONが壊れています）: {exc}"
                ) from exc
            if not isinstance(raw, dict):
                raise RewardsFileError(
                    f"報酬ファイル {path} の形式が不正です（オブジェクトではありません）"
                )
            version = raw.get("version")
            if version != FORMAT_VERSION:
                logger.warning(
                    "%s: 未知のversion=%r を version=%d として読み込みます",
                    path, version, FORMAT_VERSION,
                )
            for item in raw.get("rewards", []):
                try:
                    r = RewardEdge(
                        u=item["u"],
                        v=item["v"],
                        key=item.get("key", 0),
                        reward=item["reward"],
                        memo=item.get("memo", ""),
                        road_name=item.get("road_name", ""),
                    )
                except (KeyError, TypeError, ValueError) as exc:
                    raise RewardsFileError(
                        f"報酬ファイル {path} に不正なエントリがあります: {item!r} ({exc})"
                    ) from exc
                if graph is not None and not graph.has_edge(r.u, r.v, r.key):
                    logger.warning("グラフに存在しない報酬エッジをスキップ: %s", r.edge_id)
                    skipped.append(r)
                    continue
                rewards.append(r)
        return cls(path, place, tuple(rewards)), skipped

    def all(self) -> list[RewardEdge]:
        return sorted(self._rewards.values(), key=lambda r: r.edge_id)

    def get(self, u: int, v: int, key: int) -> RewardEdge | None:
        return self._rewards.get(normalize_edge_id(u, v, key))

    def set(
        self,
        u: int,
        v: int,
        key: int,
        reward: int,
        memo: str = "",
        road_name: str = "",
    ) -> RewardEdge:
        """報酬エッジを追加または更新し、即時保存する。"""
        r = RewardEdge(u=u, v=v, key=key, reward=reward, memo=memo, road_name=road_name)
        self._rewards[r.edge_id] = r
        self.save()
        return r

    def remove(self, u: int, v: int, key: int) -> bool:
        """報酬エッジを削除して即時保存する。存在しなければ False。"""
        removed = self._rewards.pop(normalize_edge_id(u, v, key), None)
        if removed is None:
            return False
        self.save()
        return True

    def save(self) -> None:
        payload = {
            "version": FORMAT_VERSION,
            "place": self.place,
            "rewards": [asdict(r) for r in self.all()],
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        tmp.replace(self.path)

    def __len__(self) -> int:
        return len(self._rewards)

    def __contains__(self, edge_id: EdgeId) -> bool:
        return normalize_edge_id(*edge_id) in self._rewards
