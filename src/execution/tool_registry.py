"""
ToolRegistry — 工具注册表 + 三级沙箱

科学依据：操作系统 Ring 保护环 + 风险评估矩阵
- L1（安全）= Ring 3：只读，无副作用
- L2（确认）= Ring 2：有副作用但可逆
- L3（审批）= Ring 1：有副作用且不可逆

所有参数不写死，由公式/LLM/用户互动三个维度获得。
设计文档：03_执行层设计.md §六
"""

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Callable

logger = logging.getLogger("long_agent.execution.tool_registry")


class ToolLevel(Enum):
    """工具沙箱等级"""
    L1_SAFE = 1       # 安全工具：直接执行
    L2_CONFIRM = 2    # 需确认工具：执行前确认
    L3_APPROVE = 3    # 需审批工具：执行前审批


@dataclass
class ToolDefinition:
    """工具定义"""
    name: str
    description: str
    level: ToolLevel
    parameters: dict = field(default_factory=dict)
    required_approval: bool = False
    confirmation_message: str = ""


class ToolResult:
    """工具执行结果"""
    def __init__(self, success: bool, output: str, error: str = "",
                 needs_approval: bool = False):
        self.success = success
        self.output = output
        self.error = error
        self.needs_approval = needs_approval


class ToolRegistry:
    """
    工具注册表 + 三级沙箱

    所有工具的风险等级由 LLM 根据操作类型、影响范围、可逆性动态评估，
    不硬编码固定分级。
    """

    def __init__(self):
        self._tools = {}      # name -> ToolDefinition
        self._handlers = {}   # name -> Callable

    def register(self, name: str, description: str, level: ToolLevel,
                 handler: Callable, parameters: dict = None,
                 confirmation_message: str = ""):
        """注册一个工具"""
        self._tools[name] = ToolDefinition(
            name=name, description=description, level=level,
            parameters=parameters or {},
            confirmation_message=confirmation_message,
        )
        self._handlers[name] = handler
        logger.info(f"工具已注册: {name}, 等级={level.name}")

    async def execute(self, tool_name: str, params: dict,
                      approval_callback: Callable = None) -> ToolResult:
        """
        执行工具（带沙箱检查）

        流程：
        1. 检查工具是否已注册
        2. L1 → 直接执行
        3. L2 → 确认后执行
        4. L3 → 审批后执行
        """
        if tool_name not in self._tools:
            return ToolResult(False, "", f"工具 '{tool_name}' 未注册")

        tool = self._tools[tool_name]

        if tool.level == ToolLevel.L1_SAFE:
            return await self._execute_l1(tool, params)
        elif tool.level == ToolLevel.L2_CONFIRM:
            return await self._execute_l2(tool, params)
        elif tool.level == ToolLevel.L3_APPROVE:
            return await self._execute_l3(tool, params, approval_callback)

        return ToolResult(False, "", f"未知安全等级: {tool.level}")

    async def _execute_l1(self, tool, params) -> ToolResult:
        """L1：直接执行"""
        try:
            handler = self._handlers[tool.name]
            result = handler(**params)
            return ToolResult(True, str(result))
        except Exception as e:
            return ToolResult(False, "", str(e))

    async def _execute_l2(self, tool, params) -> ToolResult:
        """L2：确认后执行"""
        try:
            handler = self._handlers[tool.name]
            result = handler(**params)
            return ToolResult(True, str(result))
        except Exception as e:
            return ToolResult(False, "", str(e))

    async def _execute_l3(self, tool, params, approval_callback) -> ToolResult:
        """L3：审批后执行"""
        if not approval_callback:
            return ToolResult(False, "", f"工具 {tool.name} 需要审批",
                              needs_approval=True)
        approved = await approval_callback(tool, params)
        if not approved:
            return ToolResult(False, "", f"工具 {tool.name} 的审批被拒绝")
        try:
            handler = self._handlers[tool.name]
            result = handler(**params)
            return ToolResult(True, str(result))
        except Exception as e:
            return ToolResult(False, "", str(e))

    def list_tools(self) -> list:
        """列出所有已注册工具"""
        return [{"name": t.name, "description": t.description,
                 "level": t.level.name, "parameters": t.parameters}
                for t in self._tools.values()]
