import json
import logging
from pathlib import Path

import pytest

from src.rewards import (
    RewardEdge,
    RewardsFileError,
    RewardStore,
    normalize_edge_id,
    rewards_path,
)

PLACE = "Shimogyo-ku, Kyoto, Japan"


@pytest.fixture
def store(tmp_path: Path) -> RewardStore:
    return RewardStore(rewards_path(PLACE, tmp_path), PLACE)


def test_rewards_path(tmp_path: Path):
    assert rewards_path(PLACE, tmp_path) == (
        tmp_path / "rewards_shimogyo_ku_kyoto_japan.json"
    )


def test_normalize_edge_id():
    assert normalize_edge_id(5, 2, 0) == (2, 5, 0)
    assert normalize_edge_id(2, 5, 1) == (2, 5, 1)


class TestRewardEdge:
    def test_normalizes_u_v(self):
        r = RewardEdge(u=5, v=2, key=0, reward=10)
        assert (r.u, r.v) == (2, 5)
        assert r.edge_id == (2, 5, 0)

    @pytest.mark.parametrize("reward", [0, -3, 1.5, "10", True])
    def test_invalid_reward_raises(self, reward):
        with pytest.raises(ValueError):
            RewardEdge(u=1, v=2, key=0, reward=reward)


class TestRewardStoreCrud:
    def test_set_and_get_with_either_orientation(self, store):
        store.set(5, 2, 0, reward=30, memo="テスト", road_name="四条通")
        assert store.get(2, 5, 0) == store.get(5, 2, 0)
        assert store.get(2, 5, 0).reward == 30
        assert (2, 5, 0) in store
        assert (5, 2, 0) in store

    def test_set_updates_existing(self, store):
        store.set(1, 2, 0, reward=10)
        store.set(2, 1, 0, reward=99, memo="更新")
        assert len(store) == 1
        assert store.get(1, 2, 0).reward == 99
        assert store.get(1, 2, 0).memo == "更新"

    def test_remove(self, store):
        store.set(1, 2, 0, reward=10)
        assert store.remove(2, 1, 0) is True
        assert len(store) == 0
        assert store.remove(1, 2, 0) is False

    def test_all_sorted_by_edge_id(self, store):
        store.set(9, 8, 0, reward=1)
        store.set(1, 2, 0, reward=2)
        assert [r.edge_id for r in store.all()] == [(1, 2, 0), (8, 9, 0)]


class TestPersistence:
    def test_set_writes_json_immediately(self, store):
        store.set(5, 2, 0, reward=50, memo="四条通の一部", road_name="四条通")

        raw = json.loads(store.path.read_text(encoding="utf-8"))
        assert raw["version"] == 1
        assert raw["place"] == PLACE
        assert raw["rewards"] == [
            {
                "u": 2,
                "v": 5,
                "key": 0,
                "reward": 50,
                "memo": "四条通の一部",
                "road_name": "四条通",
            }
        ]

    def test_roundtrip_survives_restart(self, store):
        """受入基準: 報酬設定が再起動後も保持されること（永続化部分）。"""
        store.set(1, 2, 0, reward=10, memo="a")
        store.set(4, 3, 1, reward=20, road_name="高倉通")

        reopened, skipped = RewardStore.open(store.path, PLACE)
        assert skipped == []
        assert reopened.all() == store.all()

    def test_remove_persists(self, store):
        store.set(1, 2, 0, reward=10)
        store.set(3, 4, 0, reward=20)
        store.remove(1, 2, 0)

        reopened, _ = RewardStore.open(store.path, PLACE)
        assert [r.edge_id for r in reopened.all()] == [(3, 4, 0)]


class TestOpen:
    def test_missing_file_gives_empty_store(self, tmp_path):
        store, skipped = RewardStore.open(tmp_path / "none.json", PLACE)
        assert len(store) == 0
        assert skipped == []

    def test_normalizes_reversed_entries(self, tmp_path):
        path = tmp_path / "rewards.json"
        path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "place": PLACE,
                    "rewards": [{"u": 3, "v": 2, "key": 0, "reward": 5}],
                }
            ),
            encoding="utf-8",
        )
        store, _ = RewardStore.open(path, PLACE)
        assert store.get(2, 3, 0).edge_id == (2, 3, 0)

    def test_optional_fields_default(self, tmp_path):
        path = tmp_path / "rewards.json"
        path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "place": PLACE,
                    "rewards": [{"u": 1, "v": 2, "reward": 5}],
                }
            ),
            encoding="utf-8",
        )
        store, _ = RewardStore.open(path, PLACE)
        r = store.get(1, 2, 0)
        assert (r.key, r.memo, r.road_name) == (0, "", "")

    def test_corrupted_json_raises_rewards_file_error(self, tmp_path):
        path = tmp_path / "rewards.json"
        path.write_text("{ こわれたJSON", encoding="utf-8")
        with pytest.raises(RewardsFileError, match="壊れて"):
            RewardStore.open(path, PLACE)

    def test_non_object_json_raises(self, tmp_path):
        path = tmp_path / "rewards.json"
        path.write_text("[1, 2, 3]", encoding="utf-8")
        with pytest.raises(RewardsFileError, match="形式が不正"):
            RewardStore.open(path, PLACE)

    def test_invalid_entry_raises_with_context(self, tmp_path):
        path = tmp_path / "rewards.json"
        path.write_text(
            json.dumps(
                {"version": 1, "place": PLACE, "rewards": [{"u": 1, "v": 2}]}
            ),
            encoding="utf-8",
        )
        with pytest.raises(RewardsFileError, match="不正なエントリ"):
            RewardStore.open(path, PLACE)

    def test_skips_edges_missing_from_graph(self, tmp_path, undirected_graph, caplog):
        """SPEC §6.1: グラフに存在しないエッジは警告を出してスキップ。"""
        path = tmp_path / "rewards.json"
        path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "place": PLACE,
                    "rewards": [
                        {"u": 1, "v": 2, "key": 0, "reward": 10},
                        {"u": 999, "v": 1000, "key": 0, "reward": 20},
                    ],
                }
            ),
            encoding="utf-8",
        )
        with caplog.at_level(logging.WARNING):
            store, skipped = RewardStore.open(path, PLACE, graph=undirected_graph)

        assert [r.edge_id for r in store.all()] == [(1, 2, 0)]
        assert [r.edge_id for r in skipped] == [(999, 1000, 0)]
        assert "スキップ" in caplog.text
