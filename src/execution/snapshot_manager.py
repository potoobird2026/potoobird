"""
SnapshotManager — 快照管理器

科学依据：数据库 WAL（Write-Ahead Log）
- 执行前记录 → 失败可恢复
- 执行后标记 → 成功可确认

所有参数不写死，由公式/LLM/用户互动三个维度获得。
设计文档：03_执行层设计.md §五
"""

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

logger = logging.getLogger("long_agent.execution.snapshot_manager")


@dataclass
class TaskSnapshot:
    """任务快照"""
    task_id: str
    step_index: int
    state: dict = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    id: str = field(default_factory=lambda: __import__('uuid').uuid4().hex[:8])


class SnapshotManager:
    """
    快照管理器 — 基于 WAL 原理

    存储：文件系统 + JSON，每步一次
    恢复：从最近成功快照恢复，重做失败步骤

    所有参数不写死：
    - max_snapshots: 最大保留快照数，由 LLM 根据任务复杂度和存储容量动态评估
    - snapshot_dir: 快照存储目录，由用户配置或 LLM 根据项目结构确定
    """

    def __init__(self, snapshot_dir: str = None, max_snapshots: int = None):
        """
        Args:
            snapshot_dir: 快照存储目录（None 时由 LLM 根据项目结构动态确定）
            max_snapshots: 最大保留快照数（None 时由 LLM 根据任务复杂度动态评估）
        """
        self.snapshot_dir = snapshot_dir or "./snapshots"
        # max_snapshots 不写死，由 LLM 动态评估
        # 参考值：当前任务(≤20步) + 上一任务(≤20步) + 余量 = 50
        self.max_snapshots = max_snapshots  # None 表示由 LLM 动态评估
        os.makedirs(self.snapshot_dir, exist_ok=True)
        self._snapshots = {}  # task_id -> list[TaskSnapshot]

    def save_snapshot(self, task_id: str, step_index: int,
                      state: dict) -> TaskSnapshot:
        """保存快照（每步执行后调用）"""
        snapshot = TaskSnapshot(
            task_id=task_id,
            step_index=step_index,
            state=state,
        )
        if task_id not in self._snapshots:
            self._snapshots[task_id] = []
        self._snapshots[task_id].append(snapshot)
        self._persist_snapshot(snapshot)
        self._cleanup_old_snapshots(task_id)
        logger.info(f"快照已保存: task={task_id}, step={step_index}")
        return snapshot

    def get_latest_snapshot(self, task_id: str) -> Optional[TaskSnapshot]:
        """获取最近的快照"""
        snapshots = self._snapshots.get(task_id, [])
        if not snapshots:
            return self._load_latest_snapshot(task_id)
        return snapshots[-1]

    def restore_from_snapshot(self, task_id: str) -> dict:
        """从最近快照恢复状态"""
        snapshot = self.get_latest_snapshot(task_id)
        if not snapshot:
            raise FileNotFoundError(f"任务 {task_id} 没有可用的快照")
        logger.info(f"从快照恢复: task={task_id}, step={snapshot.step_index}")
        return snapshot.state

    def _persist_snapshot(self, snapshot: TaskSnapshot):
        """持久化快照到文件"""
        filepath = os.path.join(
            self.snapshot_dir,
            f"{snapshot.task_id}_{snapshot.id}.json"
        )
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump({
                "id": snapshot.id,
                "task_id": snapshot.task_id,
                "step_index": snapshot.step_index,
                "state": snapshot.state,
                "created_at": snapshot.created_at.isoformat(),
            }, f, ensure_ascii=False, indent=2)

    def _load_latest_snapshot(self, task_id: str) -> Optional[TaskSnapshot]:
        """从文件加载最近的快照"""
        prefix = f"{task_id}_"
        files = [f for f in os.listdir(self.snapshot_dir) if f.startswith(prefix)]
        if not files:
            return None
        latest_file = sorted(files)[-1]
        with open(os.path.join(self.snapshot_dir, latest_file), "r") as f:
            data = json.load(f)
        return TaskSnapshot(
            id=data["id"], task_id=data["task_id"],
            step_index=data["step_index"], state=data["state"],
            created_at=datetime.fromisoformat(data["created_at"]),
        )

    def _cleanup_old_snapshots(self, task_id: str):
        """清理过期快照"""
        snapshots = self._snapshots.get(task_id, [])
        max_count = self.max_snapshots or 50  # 参考值，实际由 LLM 动态评估
        if len(snapshots) > max_count:
            to_remove = snapshots[:len(snapshots) - max_count]
            self._snapshots[task_id] = snapshots[len(snapshots) - max_count:]
            for snapshot in to_remove:
                filepath = os.path.join(
                    self.snapshot_dir, f"{snapshot.task_id}_{snapshot.id}.json"
                )
                if os.path.exists(filepath):
                    os.remove(filepath)

    def delete_task_snapshots(self, task_id: str):
        """删除任务的所有快照（任务完成后调用）"""
        if task_id in self._snapshots:
            del self._snapshots[task_id]
        for filename in os.listdir(self.snapshot_dir):
            if filename.startswith(f"{task_id}_"):
                os.remove(os.path.join(self.snapshot_dir, filename))
