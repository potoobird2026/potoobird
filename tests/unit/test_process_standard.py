"""
单元测试 — 流程标准化器 (src/execution/process_standard.py)

覆盖：
- ProcessStandard 初始化
- record_step()
- get_standard_process()
- finalize_task()
- get_approval_log()
- StepRecord / ApprovalRecord 数据类
"""

from unittest.mock import MagicMock

import pytest
from src.execution.process_standard import (
    ProcessStandard,
    StepRecord,
    ApprovalRecord,
)


class TestStepRecord:
    """测试 StepRecord 数据类"""

    def test_defaults(self):
        sr = StepRecord()
        assert sr.index == 0
        assert sr.description == ""
        assert sr.tool_name == ""
        assert sr.tool_params == {}
        assert sr.result == ""
        assert sr.error == ""
        assert sr.approved is False
        assert sr.completed_at is None

    def test_custom_values(self):
        sr = StepRecord(
            index=1,
            description="test step",
            tool_name="shell",
            tool_params={"cmd": "echo hi"},
            result="ok",
        )
        assert sr.index == 1
        assert sr.description == "test step"
        assert sr.tool_name == "shell"
        assert sr.result == "ok"


class TestApprovalRecord:
    """测试 ApprovalRecord 数据类"""

    def test_defaults(self):
        ar = ApprovalRecord()
        assert ar.step_index == 0
        assert ar.action == ""
        assert ar.approved is False
        assert ar.approver == ""
        assert ar.reason == ""
        assert ar.risk_score == 0.0

    def test_custom_values(self):
        ar = ApprovalRecord(
            step_index=1,
            action="delete_file",
            approved=True,
            approver="admin",
            reason="safe",
            risk_score=0.2,
        )
        assert ar.action == "delete_file"
        assert ar.approved is True
        assert ar.risk_score == 0.2


class TestProcessStandardInit:
    """测试 ProcessStandard 初始化"""

    def test_default_init(self):
        ps = ProcessStandard()
        assert ps.memory is None
        assert ps._standard_processes == {}
        assert ps._approval_logs == {}

    def test_with_memory_manager(self):
        mock_mm = MagicMock()
        ps = ProcessStandard(memory_manager=mock_mm)
        assert ps.memory is mock_mm


class TestRecordStep:
    def test_record_first_step(self):
        ps = ProcessStandard()
        ps.record_step("coding", {"index": 0, "description": "write code", "tool_name": "editor"})
        assert "coding" in ps._standard_processes
        assert len(ps._standard_processes["coding"]) == 1
        assert ps._standard_processes["coding"][0].description == "write code"

    def test_record_multiple_steps(self):
        ps = ProcessStandard()
        ps.record_step("coding", {"index": 0, "description": "step1"})
        ps.record_step("coding", {"index": 1, "description": "step2"})
        assert len(ps._standard_processes["coding"]) == 2

    def test_record_multiple_task_types(self):
        ps = ProcessStandard()
        ps.record_step("coding", {"index": 0, "description": "code"})
        ps.record_step("review", {"index": 0, "description": "review"})
        assert "coding" in ps._standard_processes
        assert "review" in ps._standard_processes

    def test_record_step_with_error(self):
        ps = ProcessStandard()
        ps.record_step("coding", {"index": 0, "description": "fail step", "error": "timeout"})
        assert ps._standard_processes["coding"][0].error == "timeout"

    def test_record_step_minimal_data(self):
        ps = ProcessStandard()
        ps.record_step("test", {})
        rec = ps._standard_processes["test"][0]
        assert rec.index == 0
        assert rec.description == ""

    def test_record_step_with_tool_params(self):
        ps = ProcessStandard()
        ps.record_step("coding", {
            "index": 0,
            "description": "run",
            "tool_name": "shell",
            "tool_params": {"cmd": "pytest"},
            "result": "passed",
        })
        rec = ps._standard_processes["coding"][0]
        assert rec.tool_params == {"cmd": "pytest"}
        assert rec.result == "passed"


class TestGetStandardProcess:
    def test_empty_for_unknown_type(self):
        ps = ProcessStandard()
        result = ps.get_standard_process("nonexistent")
        assert result == []

    def test_returns_step_dicts(self):
        ps = ProcessStandard()
        ps.record_step("coding", {
            "index": 0,
            "description": "write code",
            "tool_name": "editor",
            "tool_params": {"lang": "python"},
        })
        result = ps.get_standard_process("coding")
        assert len(result) == 1
        assert result[0]["description"] == "write code"
        assert result[0]["tool_name"] == "editor"

    def test_params_hint_from_tool_params(self):
        ps = ProcessStandard()
        ps.record_step("coding", {
            "index": 0,
            "description": "run test",
            "tool_name": "shell",
            "tool_params": {"cmd": "pytest"},
        })
        result = ps.get_standard_process("coding")
        assert "params_hint" in result[0]
        assert result[0]["params_hint"] == {"cmd": "pytest"}

    def test_multiple_steps_order(self):
        ps = ProcessStandard()
        ps.record_step("coding", {"index": 0, "description": "init"})
        ps.record_step("coding", {"index": 1, "description": "code"})
        ps.record_step("coding", {"index": 2, "description": "test"})
        result = ps.get_standard_process("coding")
        assert len(result) == 3
        assert result[0]["index"] == 0
        assert result[2]["index"] == 2

    def test_approved_field_in_result(self):
        ps = ProcessStandard()
        ps.record_step("coding", {"index": 0, "description": "approved step"})
        result = ps.get_standard_process("coding")
        assert "approved" in result[0]


class TestFinalizeTask:
    def test_finalize_with_empty_logs(self):
        ps = ProcessStandard()
        ps._standard_processes["coding"] = []
        ps.finalize_task("coding", [], [])
        assert "coding" in ps._standard_processes

    def test_finalize_adds_new_steps(self):
        ps = ProcessStandard()
        ps.finalize_task("coding", [
            {"index": 0, "description": "new step", "tool_name": "git"},
        ], [])
        assert "coding" in ps._standard_processes
        assert len(ps._standard_processes["coding"]) == 1
        assert ps._standard_processes["coding"][0].description == "new step"

    def test_finalize_deduplicates_steps(self):
        ps = ProcessStandard()
        ps.record_step("coding", {"index": 0, "description": "existing"})
        ps.finalize_task("coding", [
            {"index": 0, "description": "existing"},
            {"index": 1, "description": "new one"},
        ], [])
        descriptions = [s.description for s in ps._standard_processes["coding"]]
        assert "existing" in descriptions
        assert "new one" in descriptions
        # 不应有重复
        assert len(descriptions) == len(set(descriptions))

    def test_finalize_records_approvals(self):
        ps = ProcessStandard()
        ps.finalize_task("coding", [], [
            {"action": "write", "approved": True, "approver": "admin"},
        ])
        assert "coding" in ps._approval_logs
        assert len(ps._approval_logs["coding"]) == 1
        assert ps._approval_logs["coding"][0].action == "write"

    def test_finalize_with_no_approval_log(self):
        ps = ProcessStandard()
        ps.finalize_task("coding", [
            {"index": 0, "description": "step"},
        ], [])
        # approval_log 为空列表，不应创建 key
        assert "coding" not in ps._approval_logs


class TestGetApprovalLog:
    def test_empty_for_unknown(self):
        ps = ProcessStandard()
        assert ps.get_approval_log("nonexistent") == []

    def test_returns_records_for_type(self):
        ps = ProcessStandard()
        ps.finalize_task("coding", [], [
            {"action": "write", "approved": True},
            {"action": "delete", "approved": False},
        ])
        result = ps.get_approval_log("coding")
        assert len(result) == 2

    def test_returns_all_when_no_type(self):
        ps = ProcessStandard()
        ps.finalize_task("coding", [], [
            {"action": "write", "approved": True},
        ])
        ps.finalize_task("review", [], [
            {"action": "approve", "approved": True},
        ])
        result = ps.get_approval_log()
        assert len(result) == 2

    def test_returns_list_copy(self):
        ps = ProcessStandard()
        ps.finalize_task("coding", [], [
            {"action": "write", "approved": True},
        ])
        result = ps.get_approval_log("coding")
        result.clear()
        # 原始数据不应被修改
        assert len(ps._approval_logs["coding"]) == 1
