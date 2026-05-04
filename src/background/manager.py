"""
后台任务管理器 — 纯事件驱动

不依赖任何定时器。三个钩子：
- on_conversation_end：访问计数衰减 + 备份检查 + 冷区压缩检查
- on_startup：备份状态检查 + 48h 提醒
- on_shutdown：备份 + 快照清理 + VACUUM
"""

import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger("long_agent.background")


class BackgroundTaskManager:
    """
    后台任务管理器 — 纯事件驱动

    备份/快照清理/VACUUM 分开频率判断。
    """

    def __init__(
        self,
        data_dir: str,
        backup_interval_hours: int = 24,
        snapshot_cleanup_days: int = 7,
        vacuum_interval_days: int = 30,
    ):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self._backup_interval = timedelta(hours=backup_interval_hours)
        self._snapshot_cleanup_interval = timedelta(days=snapshot_cleanup_days)
        self._vacuum_interval = timedelta(days=vacuum_interval_days)

        # 时间戳文件
        self._last_backup_file = self.data_dir / "last_backup.txt"
        self._last_snapshot_cleanup_file = self.data_dir / "last_snapshot_cleanup.txt"
        self._last_vacuum_file = self.data_dir / "last_vacuum.txt"

        self._decay_factor = 0.9  # 访问计数衰减因子

    # ---- 时间戳读写 ----

    def _read_timestamp(self, path: Path) -> Optional[datetime]:
        try:
            ts = path.read_text().strip()
            return datetime.fromisoformat(ts)
        except (FileNotFoundError, ValueError):
            return None

    def _write_timestamp(self, path: Path):
        # 注意：不加 Z 后缀，Python 3.10 的 fromisoformat 不支持 Z
        path.write_text(datetime.utcnow().isoformat())

    def _should_run(self, last_file: Path, interval: timedelta) -> bool:
        last = self._read_timestamp(last_file)
        if last is None:
            return True
        return datetime.utcnow() - last >= interval

    # ---- 事件钩子 ----

    async def on_startup(self, storage, memory_manager):
        """启动时调用"""
        logger.info("后台任务：启动检查")

        # 检查备份状态
        last_backup = self._read_timestamp(self._last_backup_file)
        if last_backup is None:
            logger.info("从未备份过，建议尽快备份")
        elif datetime.utcnow() - last_backup > timedelta(hours=48):
            logger.warning(
                f"距上次备份已超过 48 小时（上次：{last_backup.isoformat()}），建议尽快备份"
            )
        else:
            logger.info(f"上次备份：{last_backup.isoformat()}，状态正常")

        # 冷区压缩检查
        should_compress = await memory_manager.should_compress_cold_zone()
        if should_compress:
            logger.info("冷区记忆数超过阈值，执行压缩")
            await memory_manager.compress_cold_zone()
        else:
            logger.debug("冷区记忆数未超过阈值，跳过压缩")

    async def on_conversation_end(self, storage, memory_manager):
        """每次对话结束时调用"""
        logger.debug("后台任务：对话结束检查")

        # 访问计数衰减
        await memory_manager.decay_access_counts(factor=self._decay_factor)

        # 备份检查
        if self._should_run(self._last_backup_file, self._backup_interval):
            logger.info("触发对话后备份")
            try:
                memory_manager.backup()
                self._write_timestamp(self._last_backup_file)
            except Exception as e:
                logger.error(f"对话后备份失败: {e}")

        # 冷区压缩检查
        should_compress = await memory_manager.should_compress_cold_zone()
        if should_compress:
            logger.info("冷区记忆数超过阈值，执行压缩")
            await memory_manager.compress_cold_zone()

    async def on_shutdown(self, storage, memory_manager):
        """关闭前调用"""
        logger.info("后台任务：关闭前维护")

        # 关闭前立即备份
        try:
            memory_manager.backup()
            self._write_timestamp(self._last_backup_file)
            logger.info("关闭前备份完成")
        except Exception as e:
            logger.error(f"关闭前备份失败: {e}")

        # 快照清理（7天）
        if self._should_run(self._last_snapshot_cleanup_file, self._snapshot_cleanup_interval):
            try:
                old_snapshots = await storage.get_old_snapshots(days=7)
                if old_snapshots:
                    ids = [s.id for s in old_snapshots]
                    await storage.delete_snapshots(ids)
                    logger.info(f"清理 {len(ids)} 个过期快照")
                self._write_timestamp(self._last_snapshot_cleanup_file)
            except Exception as e:
                logger.error(f"快照清理失败: {e}")

        # VACUUM（30天）
        if self._should_run(self._last_vacuum_file, self._vacuum_interval):
            try:
                await storage.vacuum()
                self._write_timestamp(self._last_vacuum_file)
                logger.info("VACUUM 完成")
            except Exception as e:
                logger.error(f"VACUUM 失败: {e}")
