"""BackgroundTaskManager 单元测试"""

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d


class TestBackgroundTaskManager:
    def test_init_creates_directories(self, tmp_dir):
        """初始化创建数据目录"""
        from src.background.manager import BackgroundTaskManager
        _ = BackgroundTaskManager(data_dir=tmp_dir)
        assert Path(tmp_dir).exists()

    def test_init_default_intervals(self, tmp_dir):
        from src.background.manager import BackgroundTaskManager
        mgr = BackgroundTaskManager(data_dir=tmp_dir)
        assert mgr._decay_factor == 0.9

    @pytest.mark.asyncio
    async def test_on_startup_no_prior_backup(self, tmp_dir):
        """启动时无备份记录"""
        from src.background.manager import BackgroundTaskManager
        mgr = BackgroundTaskManager(data_dir=tmp_dir)
        mock_storage = MagicMock()
        mock_mm = AsyncMock()
        mock_mm.should_compress_cold_zone = AsyncMock(return_value=False)
        await mgr.on_startup(mock_storage, mock_mm)

    @pytest.mark.asyncio
    async def test_on_startup_triggers_compress(self, tmp_dir):
        """启动时触发冷区压缩"""
        from src.background.manager import BackgroundTaskManager
        mgr = BackgroundTaskManager(data_dir=tmp_dir)
        mock_storage = MagicMock()
        mock_mm = AsyncMock()
        mock_mm.should_compress_cold_zone = AsyncMock(return_value=True)
        mock_mm.compress_cold_zone = AsyncMock()
        await mgr.on_startup(mock_storage, mock_mm)
        mock_mm.compress_cold_zone.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_on_conversation_end_decay(self, tmp_dir):
        """对话结束触发访问计数衰减"""
        from src.background.manager import BackgroundTaskManager
        mgr = BackgroundTaskManager(data_dir=tmp_dir)
        mock_storage = MagicMock()
        mock_mm = AsyncMock()
        mock_mm.decay_access_counts = AsyncMock()
        await mgr.on_conversation_end(mock_storage, mock_mm)
        mock_mm.decay_access_counts.assert_called_once_with(factor=0.9)

    @pytest.mark.asyncio
    async def test_on_shutdown_backup(self, tmp_dir):
        """关闭前备份"""
        from src.background.manager import BackgroundTaskManager
        mgr = BackgroundTaskManager(data_dir=tmp_dir)
        mock_storage = MagicMock()
        mock_mm = AsyncMock()
        mock_mm.backup = MagicMock()
        await mgr.on_shutdown(mock_storage, mock_mm)
        mock_mm.backup.assert_called_once()

    def test_timestamp_read_write(self, tmp_dir):
        """时间戳读写"""
        from src.background.manager import BackgroundTaskManager
        mgr = BackgroundTaskManager(data_dir=tmp_dir)
        ts_file = Path(tmp_dir) / "test_ts.txt"
        mgr._write_timestamp(ts_file)
        result = mgr._read_timestamp(ts_file)
        assert result is not None

    def test_timestamp_read_nonexistent(self, tmp_dir):
        """读取不存在的时间戳返回 None"""
        from src.background.manager import BackgroundTaskManager
        mgr = BackgroundTaskManager(data_dir=tmp_dir)
        assert mgr._read_timestamp(Path(tmp_dir) / "nonexistent.txt") is None

    def test_timestamp_read_corrupt(self, tmp_dir):
        """读取损坏的时间戳返回 None"""
        from src.background.manager import BackgroundTaskManager
        mgr = BackgroundTaskManager(data_dir=tmp_dir)
        p = Path(tmp_dir) / "bad.txt"
        p.write_text("not-a-date")
        assert mgr._read_timestamp(p) is None

    def test_should_run_no_file(self, tmp_dir):
        """从未运行过 → True"""
        from datetime import timedelta

        from src.background.manager import BackgroundTaskManager
        mgr = BackgroundTaskManager(data_dir=tmp_dir)
        assert mgr._should_run(Path(tmp_dir) / "none.txt", timedelta(hours=1)) is True

    def test_should_run_recent(self, tmp_dir):
        """刚运行过 → False"""
        from datetime import timedelta

        from src.background.manager import BackgroundTaskManager
        mgr = BackgroundTaskManager(data_dir=tmp_dir)
        p = Path(tmp_dir) / "recent.txt"
        mgr._write_timestamp(p)
        assert mgr._should_run(p, timedelta(hours=24)) is False

    def test_should_run_expired(self, tmp_dir):
        """超过间隔 → True"""
        from datetime import datetime, timedelta

        from src.background.manager import BackgroundTaskManager
        mgr = BackgroundTaskManager(data_dir=tmp_dir)
        p = Path(tmp_dir) / "old.txt"
        old = datetime.utcnow() - timedelta(hours=2)
        p.write_text(old.isoformat())
        assert mgr._should_run(p, timedelta(hours=1)) is True

    @pytest.mark.asyncio
    async def test_on_conversation_end_triggers_backup(self, tmp_dir):
        """对话结束且需要备份时触发备份"""
        from src.background.manager import BackgroundTaskManager
        mgr = BackgroundTaskManager(data_dir=tmp_dir)
        # 没有上次备份记录，_should_run 返回 True
        mock_storage = MagicMock()
        mock_mm = AsyncMock()
        mock_mm.decay_access_counts = AsyncMock()
        mock_mm.backup = MagicMock()
        await mgr.on_conversation_end(mock_storage, mock_mm)
        mock_mm.backup.assert_called_once()

    @pytest.mark.asyncio
    async def test_on_shutdown_snapshot_cleanup(self, tmp_dir):
        """关闭时快照清理"""
        from src.background.manager import BackgroundTaskManager
        mgr = BackgroundTaskManager(data_dir=tmp_dir)
        mock_storage = MagicMock()
        mock_storage.get_old_snapshots = AsyncMock(return_value=[])
        mock_storage.vacuum = AsyncMock()
        mock_mm = AsyncMock()
        mock_mm.backup = MagicMock()
        await mgr.on_shutdown(mock_storage, mock_mm)

    @pytest.mark.asyncio
    async def test_on_shutdown_vacuum(self, tmp_dir):
        """关闭时 VACUUM"""
        from src.background.manager import BackgroundTaskManager
        mgr = BackgroundTaskManager(data_dir=tmp_dir)
        mock_storage = MagicMock()
        mock_storage.get_old_snapshots = AsyncMock(return_value=[])
        mock_storage.vacuum = AsyncMock()
        mock_mm = AsyncMock()
        mock_mm.backup = MagicMock()
        await mgr.on_shutdown(mock_storage, mock_mm)
        mock_storage.vacuum.assert_called_once()
