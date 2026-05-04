# Long Agent Skill + MCP 设计方案 v1.0

> **定位**：简单实用，能跑通主要功能即可
> **原则**：轻量、可扩展、不引入复杂框架

---

## 一、Skill 系统

### 1.1 什么是 Skill

Skill = 一组工具 + 一份使用说明，Agent 按需加载。

```
skills/
├── file_operations/    # 文件操作 Skill
│   ├── SKILL.md        # 使用说明（含工具定义）
│   └── tools.py        # 工具实现
├── web_search/         # 网络搜索 Skill
│   ├── SKILL.md
│   └── tools.py
└── code_analysis/      # 代码分析 Skill
    ├── SKILL.md
    └── tools.py
```

### 1.2 后端实现

**新增文件**：`src/skill/manager.py`

```python
class SkillManager:
    """Skill 管理器 — 加载/注册/执行"""

    def __init__(self, skill_dir: str = "skills"):
        self.skill_dir = Path(skill_dir)
        self._skills: dict[str, Skill] = {}

    def load_skill(self, name: str) -> Skill:
        """加载一个 Skill（读取 SKILL.md + 注册工具）"""
        ...

    def execute_tool(self, skill_name: str, tool_name: str, params: dict) -> ToolResult:
        """执行 Skill 中的工具"""
        ...

    def list_skills(self) -> list[dict]:
        """列出所有可用 Skill"""
        ...

    def load_all(self):
        """启动时加载所有 Skill"""
        ...
```

**数据结构**：

```python
@dataclass
class Skill:
    name: str
    description: str
    tools: dict[str, ToolDefinition]
    handler: object  # tools.py 模块
```

### 1.3 与主循环集成

在 `AgentLoop.__init__` 添加 `skill_manager: SkillManager = None` 参数。
在 `_step_execute` 中，当意图为 `tool_call` 时，先查 skill_manager 再查 tool_registry。

### 1.4 Web UI 集成

**新增 API**：
- `GET /api/skills` — 列出所有 Skill
- `POST /api/skills/{name}/load` — 加载 Skill
- `GET /api/skills/{name}/tools` — 查看 Skill 的工具

**前端页面**：在侧边栏新增"🗂️ Skill 管理"面板，显示已加载的 Skill 列表。

---

## 二、MCP 协议支持

### 2.1 什么是 MCP

MCP（Model Context Protocol）是 AI Agent 之间通信的轻量协议。Long Agent 作为 MCP Server，暴露工具接口给其他 Agent 调用。

### 2.2 协议设计（极简版）

```
MCP Request:
{
    "jsonrpc": "2.0",
    "method": "tool/call",
    "params": {
        "name": "memory_search",
        "arguments": {"query": "Python"}
    },
    "id": 1
}

MCP Response:
{
    "jsonrpc": "2.0",
    "result": {
        "content": [{"type": "text", "text": "找到3条记忆..."}]
    },
    "id": 1
}
```

### 2.3 后端实现

**新增文件**：`src/mcp/server.py`

```python
class MCPServer:
    """
    MCP 服务器 — 轻量 HTTP + JSON-RPC

    暴露的工具：
    - memory_search(query, layer) → list
    - memory_write(content, layer) → str
    - personality_get() → dict
    - skill_execute(skill_name, tool_name, params) → str
    """

    def __init__(self, agent, host="0.0.0.0", port=9090):
        self.agent = agent
        self.host = host
        self.port = port
        self.app = FastAPI()

    def start(self):
        """启动 MCP HTTP 服务器"""
        uvicorn.run(self.app, host=self.host, port=self.port)
```

### 2.4 Web UI 集成

**新增 API**：
- `GET /api/mcp/status` — MCP 服务器状态
- `POST /api/mcp/call` — 手动调用 MCP 工具（调试用）

**前端页面**：在设置页新增"MCP 配置"面板，显示服务器地址、端口、已暴露的工具列表。

---

## 三、文件结构

```
src/
├── skill/
│   ├── __init__.py
│   └── manager.py          # SkillManager（约200行）
├── mcp/
│   ├── __init__.py
│   └── server.py           # MCPServer（约150行）
└── entry/
    └── web_ui.py           # 新增2个API

skins/                       # 内置 Skill（新建）
└── builtins/
    ├── SKILL.md
    └── tools.py

templates/
└── index.html              # 新增Skill面板（约20行）

static/
└── app.js                  # 新增Skill加载逻辑（约30行）
```

---

## 四、启动方式

```bash
# 默认启动（不带 MCP）
python -m src.entry.cli run

# 带 MCP 服务器启动
python -m src.entry.cli run --mcp-port 9090

# 启动 Web UI + MCP
python -m src.entry.cli web --mcp-port 9090
```

---

## 五、工作量估算

| 模块 | 文件 | 行数 | 工时 |
|------|------|------|------|
| SkillManager | `src/skill/manager.py` | ~200 | 1小时 |
| MCPServer | `src/mcp/server.py` | ~150 | 1小时 |
| 内置 Skill | `skins/builtins/` | ~50 | 30分钟 |
| Web UI 集成 | web_ui.py + app.js | ~50 | 30分钟 |
| 测试 | tests/ | ~100 | 30分钟 |
| **总计** | **~6个文件** | **~550行** | **~3.5小时** |

---

> **方案版本**：v1.0
> **创建时间**：2026-05-04
> **核心依赖**：无需新依赖（复用 FastAPI）
