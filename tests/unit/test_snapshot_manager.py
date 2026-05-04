"""
SnapshotManager — 单元测试

覆盖：快照保存/恢复/加载/清理/删除、TaskSnapshot 数据类
"""
import os
import shutil
import tempfile

import pytest

from src.execution.snapshot_manager import SnapshotManager, TaskSnapshot


@pytest.fixture
def tmp_dir():
    d = tempfile.mkdtemp(prefix="snapshot_test_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def manager(tmp_dir):
    return SnapshotManager(snapshot_dir=tmp_dir, max_snapshots=5)


class TestSnapshotSave:
    def test_save_returns_snapshot(self, manager):
        snap = manager.save_snapshot("task1", 0, {"key": "value"})
        assert isinstance(snap, TaskSnapshot)
        assert snap.task_id == "task1"
        assert snap.step_index == 0
        assert snap.state == {"key": "value"}

    def test_save_persists_to_file(self, manager, tmp_dir):
        _ = manager.save_snapshot("task1", 0, {"step": 1})  # noqa: F841
        files = os.listdir(tmp_dir)
        assert any(f.startswith("task1_") for f in files)

    def test_save_multiple_steps(self, manager):
        s1 = manager.save_snapshot("task1", 0, {"step": 0})
        s2 = manager.save_snapshot("task1", 1, {"step": 1})
        assert s1.id != s2.id
        assert s1.step_index == 0
        assert s2.step_index == 1


class TestSnapshotGetLatest:
    def test_get_latest_in_memory(self, manager):
        manager.save_snapshot("task1", 0, {"step": 0})
        manager.save_snapshot("task1", 1, {"step": 1})
        latest = manager.get_latest_snapshot("task1")
        assert latest.step_index == 1

    def test_get_latest_from_disk(self, tmp_dir):
        """内存为空时应从磁盘加载"""
        m1 = SnapshotManager(snapshot_dir=tmp_dir, max_snapshots=5)
        m1.save_snapshot("task1", 3, {"from": "first"})
        # 新实例（内存为空），应从文件加载
        m2 = SnapshotManager(snapshot_dir=tmp_dir, max_snapshots=5)
        latest = m2.get_latest_snapshot("task1")
        assert latest is not None
        assert latest.step_index == 3

    def test_get_latest_nonexistent(self, manager):
        assert manager.get_latest_snapshot("nonexistent") is None


class TestSnapshotRestore:
    def test_restore_returns_state(self, manager):
        manager.save_snapshot("task1", 2, {"data": "hello"})
        state = manager.restore_from_snapshot("task1")
        assert state == {"data": "hello"}

    def test_restore_raises_when_no_snapshot(self, manager):
        with pytest.raises(FileNotFoundError):
            manager.restore_from_snapshot("nonexistent")


class TestSnapshotCleanup:
    def test_cleanup_old_snapshots(self, manager):
        """超过 max_snapshots 应清理最老的快照"""
        for i in range(10):
            manager.save_snapshot("task1", i, {"step": i})
        # max_snapshots=5，应只保留最新的5个
        assert len(manager._snapshots["task1"]) <= 5

    def test_cleanup_deletes_files(self, tmp_dir):
        mgr = SnapshotManager(snapshot_dir=tmp_dir, max_snapshots=3)
        for i in range(6):
            mgr.save_snapshot("task1", i, {"step": i})
        files = [f for f in os.listdir(tmp_dir) if f.startswith("task1_")]
        assert len(files) <= 3

    def test_delete_task_snapshots(self, manager, tmp_dir):
        manager.save_snapshot("task1", 0, {"step": 0})
        manager.delete_task_snapshots("task1")
        assert "task1" not in manager._snapshots
        files = [f for f in os.listdir(tmp_dir) if f.startswith("task1_")]
        assert len(files) == 0

    def test_delete_nonexistent_task(self, manager):
        # 不应抛异常
        manager.delete_task_snapshots("nonexistent")


class TestSnapshotDataClass:
    def test_snapshot_has_uuid(self):
        snap = SnapshotManager(snapshot_dir=tempfile.mkdtemp(), max_snapshots=5)
        s = snap.save_snapshot("t1", 0, {})
        assert len(s.id) == 8  # uuid4 hex[:8]

    def test_snapshot_created_at_is_recent(self, manager):
        import datetime
        s = manager.save_snapshot("t1", 0, {})
        now = datetime.datetime.now()
        diff = (now - s.created_at).total_seconds()
        assert diff < 5  # 5秒内创建的
