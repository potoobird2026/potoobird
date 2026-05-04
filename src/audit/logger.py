"""
审计日志系统

记录所有关键操作的"谁、什么时候、做了什么、结果如何"。
审计日志独立于应用日志，单独文件存储。
"""

import json
import logging
from datetime import datetime
from enum import Enum
from pathlib import Path

logger = logging.getLogger("long_agent.audit")


class AuditAction(Enum):
    """审计操作类型"""

    MEMORY_WRITE = "memory_write"
    MEMORY_UPDATE = "memory_update"
    MEMORY_DELETE = "memory_delete"
    MEMORY_SEARCH = "memory_search"
    PERSONALITY_UPDATE = "personality_update"
    CONFIG_CHANGE = "config_change"
    BACKUP_CREATED = "backup_created"
    BACKUP_RESTORED = "backup_restored"
    LOGIN = "login"
    LOGOUT = "logout"
    PENDING_WRITE_RETRY = "pending_write_retry"
    PENDING_WRITE_FAILED = "pending_write_failed"
    SECURITY_VIOLATION = "security_violation"
    WRITE_REJECTED_READONLY = "write_rejected_readonly"


class AuditLogger:
    """审计日志器"""

    def __init__(self, audit_log_path: str = "data/audit.jsonl"):
        self.audit_log_path = Path(audit_log_path)
        self.audit_log_path.parent.mkdir(parents=True, exist_ok=True)

    def log(self, action: AuditAction, details: dict, success: bool = True, error: str = None):
        """记录一条审计日志"""
        entry = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "action": action.value,
            "success": success,
            "details": details,
        }
        if error:
            entry["error"] = error

        with open(self.audit_log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def query(self, action: AuditAction = None, since: str = None, limit: int = 100) -> list[dict]:
        """查询审计日志"""
        results = []
        if not self.audit_log_path.exists():
            return results

        with open(self.audit_log_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if action and entry.get("action") != action.value:
                    continue
                if since and entry.get("timestamp", "") < since:
                    continue

                results.append(entry)
                if len(results) >= limit:
                    break

        return results
