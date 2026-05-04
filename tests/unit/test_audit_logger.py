"""
单元测试 — AuditLogger

AuditAction 枚举值（14种）：
MEMORY_WRITE, MEMORY_UPDATE, MEMORY_DELETE, MEMORY_SEARCH,
PERSONALITY_UPDATE, CONFIG_CHANGE, BACKUP_CREATED, BACKUP_RESTORED,
LOGIN, LOGOUT, PENDING_WRITE_RETRY, PENDING_WRITE_FAILED,
SECURITY_VIOLATION, WRITE_REJECTED_READONLY

AuditLogger.log() 签名：log(action, details, success=True, error=None)
AuditLogger.query() 签名：query(action=None, since=None, limit=100)
"""

import json
import os
import tempfile

import pytest

from src.audit.logger import AuditAction, AuditLogger


@pytest.fixture
def tmp_file():
    with tempfile.TemporaryDirectory() as d:
        yield os.path.join(d, "audit.jsonl")


@pytest.fixture
def logger(tmp_file):
    return AuditLogger(tmp_file)


# ---- 基本操作 ----


def test_log_write(logger, tmp_file):
    logger.log(AuditAction.MEMORY_WRITE, details={"id": "test-1"})
    entries = logger.query()
    assert len(entries) == 1
    assert entries[0]["action"] == "memory_write"


def test_log_multiple(logger):
    for i in range(5):
        logger.log(AuditAction.MEMORY_SEARCH, details={"i": i})
    entries = logger.query()
    assert len(entries) == 5


def test_log_with_success_true(logger):
    logger.log(AuditAction.MEMORY_WRITE, details={}, success=True)
    entries = logger.query()
    assert entries[0]["success"] is True


def test_log_with_success_false(logger):
    logger.log(AuditAction.MEMORY_DELETE, details={"reason": "not found"}, success=False)
    entries = logger.query()
    assert entries[0]["success"] is False


def test_log_with_error(logger):
    logger.log(AuditAction.MEMORY_WRITE, details={}, error="写入失败")
    entries = logger.query()
    assert entries[0]["error"] == "写入失败"


# ---- 查询过滤 ----


def test_query_by_action(logger):
    logger.log(AuditAction.MEMORY_WRITE, details={})
    logger.log(AuditAction.MEMORY_SEARCH, details={})
    logger.log(AuditAction.MEMORY_WRITE, details={})
    entries = logger.query(action=AuditAction.MEMORY_WRITE)
    assert len(entries) == 2


def test_query_by_limit(logger):
    for i in range(10):
        logger.log(AuditAction.MEMORY_SEARCH, details={})
    entries = logger.query(limit=3)
    assert len(entries) == 3


def test_query_no_results(logger):
    logger.log(AuditAction.MEMORY_WRITE, details={})
    entries = logger.query(action=AuditAction.MEMORY_DELETE)
    assert len(entries) == 0


def test_query_all_when_no_filter(logger):
    logger.log(AuditAction.MEMORY_WRITE, details={})
    logger.log(AuditAction.MEMORY_SEARCH, details={})
    entries = logger.query()
    assert len(entries) == 2


# ---- 持久化 ----


def test_persisted_to_file(logger, tmp_file):
    logger.log(AuditAction.MEMORY_WRITE, details={"test": True})
    assert os.path.exists(tmp_file)


def test_file_format_jsonl(logger, tmp_file):
    logger.log(AuditAction.MEMORY_WRITE, details={})
    logger.log(AuditAction.MEMORY_SEARCH, details={})
    with open(tmp_file, "r", encoding="utf-8") as f:
        lines = f.readlines()
    assert len(lines) == 2
    for line in lines:
        data = json.loads(line)
        assert "action" in data
        assert "timestamp" in data
        assert "success" in data


# ---- 时间戳 ----


def test_timestamp_present(logger):
    logger.log(AuditAction.MEMORY_WRITE, details={})
    entries = logger.query()
    assert "timestamp" in entries[0]
    assert "T" in entries[0]["timestamp"]  # ISO format


# ---- AuditAction 枚举 ----


def test_all_actions_exist():
    actions = {a.name for a in AuditAction}
    expected = {
        "MEMORY_WRITE",
        "MEMORY_UPDATE",
        "MEMORY_DELETE",
        "MEMORY_SEARCH",
        "PERSONALITY_UPDATE",
        "CONFIG_CHANGE",
        "BACKUP_CREATED",
        "BACKUP_RESTORED",
        "LOGIN",
        "LOGOUT",
        "PENDING_WRITE_RETRY",
        "PENDING_WRITE_FAILED",
        "SECURITY_VIOLATION",
        "WRITE_REJECTED_READONLY",
    }
    assert actions == expected


# ---- details 字段 ----


def test_details_preserved(logger):
    logger.log(AuditAction.MEMORY_WRITE, details={"id": "abc", "layer": "core", "count": 42})
    entries = logger.query()
    assert entries[0]["details"]["id"] == "abc"
    assert entries[0]["details"]["layer"] == "core"
    assert entries[0]["details"]["count"] == 42


def test_empty_details(logger):
    logger.log(AuditAction.MEMORY_SEARCH, details={})
    entries = logger.query()
    assert entries[0]["details"] == {}


# ---- query by since ----


def test_query_since(logger):
    logger.log(AuditAction.MEMORY_WRITE, details={"old": True})
    entries = logger.query(since="9999-01-01T00:00:00")
    assert len(entries) == 0
