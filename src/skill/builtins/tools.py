"""Builtins Skill — 内置基础工具"""

from dataclasses import dataclass


def tool_def(name: str, description: str):
    """工具定义装饰器"""
    def decorator(func):
        func.__tool_def__ = {"name": name, "description": description}
        return func
    return decorator


@tool_def("list_memories", "列出最近记忆")
async def list_memories(memory_manager=None, limit: int = 10):
    """列出最近记忆"""
    if not memory_manager:
        return "记忆系统未初始化"
    memories = await memory_manager.search("", limit=limit)
    if not memories:
        return "暂无记忆"
    return "\n".join(f"- [{m.layer}] {m.content[:50]}" for m in memories)


@tool_def("get_personality", "获取当前人格状态")
async def get_personality(memory_manager=None):
    """获取人格状态"""
    if not memory_manager:
        return "记忆系统未初始化"
    p = memory_manager.personality
    return "\n".join(f"{k}: {v}" for k, v in p.items())


@tool_def("system_info", "获取系统信息")
async def system_info():
    """获取基本系统信息"""
    import platform, os
    return (
        f"系统: {platform.system()} {platform.version()}\n"
        f"Python: {platform.python_version()}\n"
        f"进程: {os.getpid()}"
    )
