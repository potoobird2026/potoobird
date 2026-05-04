# Long Agent Web UI 设计方案 v1.0

> **定位**：简单实用的 Web 界面，用于测试和演示核心功能
> **原则**：不复杂，能跑通主要功能测试即可

---

## 一、技术选型

| 组件 | 选型 | 理由 |
|------|------|------|
| 后端框架 | FastAPI | 已在项目依赖中，异步支持好 |
| 前端 | 纯 HTML + CSS + JS | 不引入前端框架，简单直接 |
| 通信 | WebSocket | 流式输出 LLM 响应 |
| 模板 | Jinja2 | FastAPI 内置支持 |

---

## 二、页面布局（单页面）

```
┌─────────────────────────────────────────────────────────────┐
│  🤖 Long Agent v1.0                              [设置] ⚙️  │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │                                                     │   │
│  │              聊天消息区域                            │   │
│  │                                                     │   │
│  │  👤 用户: 帮我记住我喜欢简洁风格                     │   │
│  │                                                     │   │
│  │  🤖 Agent: ✅ 已记住（core 层）                     │   │
│  │                                                     │   │
│  │  👤 用户: 查看我的记忆                              │   │
│  │                                                     │   │
│  │  🤖 Agent: 找到以下记忆：                           │   │
│  │           - [preference] 用户喜欢简洁               │   │
│  │                                                     │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ 输入消息...                              [发送] ➤   │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
├─────────────────────────────────────────────────────────────┤
│  📊 状态栏: 记忆 128 条 | 人格 H:50 E:50 X:50 A:50 C:50 O:50 │
└─────────────────────────────────────────────────────────────┘
```

---

## 三、后端 API 设计

### 3.1 路由结构

```
GET  /                    → 主页（聊天界面）
POST /api/chat            → 发送消息（非流式）
WS   /ws/chat             → WebSocket 流式聊天
GET  /api/memory          → 获取记忆列表
POST /api/memory          → 添加记忆
DELETE /api/memory/{id}   → 删除记忆
GET  /api/personality     → 获取人格状态
PUT  /api/personality     → 更新人格
GET  /api/health          → 健康检查
GET  /api/stats           → 统计信息
```

### 3.2 核心代码结构

```
src/entry/
├── cli.py          # 已有：CLI 入口
└── web_ui.py       # 新建：Web UI 入口

templates/
└── index.html      # 聊天页面

static/
├── style.css       # 样式
└── app.js          # 前端逻辑
```

### 3.3 web_ui.py 核心代码

```python
# src/entry/web_ui.py
"""Web UI 入口 — FastAPI + WebSocket"""

import logging
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.requests import Request

from src.config.settings import Settings, init_logging
from src.memory.manager import MemoryManager
from src.memory.storage.sqlite_storage import SQLiteStorage
from src.understanding.engine import UnderstandingEngine
from src.loop.agent_loop import AgentLoop

logger = logging.getLogger("long_agent.web")

app = FastAPI(title="Long Agent", version="0.1.0")

# 静态文件和模板
BASE_DIR = Path(__file__).parent.parent.parent
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# 全局 Agent 实例
_agent = None

def get_agent():
    """获取或创建 Agent 实例（单例）"""
    global _agent
    if _agent is None:
        settings = Settings()
        init_logging(settings.log_level, settings.log_file)
        storage = SQLiteStorage(settings.database_path)
        memory = MemoryManager(storage, settings.data_dir)
        understanding = UnderstandingEngine()
        
        llm_provider = None
        if settings.openai_api_key:
            from src.llm.provider import OpenAIProvider
            llm_provider = OpenAIProvider(
                api_key=settings.openai_api_key,
                model=settings.openai_model,
            )
        
        agent_loop = AgentLoop(
            memory_manager=memory,
            understanding_engine=understanding,
            llm_provider=llm_provider,
        )
        
        _agent = {
            "loop": agent_loop,
            "memory": memory,
            "settings": settings,
        }
    return _agent


@app.get("/")
async def index(request: Request):
    """主页"""
    agent = get_agent()
    memory_count = await agent["memory"].storage.count()
    personality = agent["memory"].get_personality()
    return templates.TemplateResponse("index.html", {
        "request": request,
        "memory_count": memory_count,
        "personality": personality,
    })


@app.post("/api/chat")
async def chat(request: Request):
    """非流式聊天"""
    data = await request.json()
    user_input = data.get("message", "")
    
    agent = get_agent()
    response = await agent["agent_loop"].run(user_input)
    
    return {"response": response}


@app.websocket("/ws/chat")
async def ws_chat(websocket: WebSocket):
    """WebSocket 流式聊天"""
    await websocket.accept()
    agent = get_agent()
    
    try:
        while True:
            data = await websocket.receive_text()
            
            # 流式响应
            async for chunk in agent["agent_loop"].run_stream(data):
                await websocket.send_text(chunk)
            
            await websocket.send_text("[DONE]")
    except WebSocketDisconnect:
        logger.info("WebSocket 断开")


@app.get("/api/memory")
async def get_memories(layer: str = None, limit: int = 50):
    """获取记忆列表"""
    agent = get_agent()
    memories = await agent["memory"].search("", layer=layer, limit=limit)
    return {"memories": [{"id": m.id, "content": m.content, "layer": m.layer} for m in memories]}


@app.post("/api/memory")
async def add_memory(request: Request):
    """添加记忆"""
    data = await request.json()
    agent = get_agent()
    result = await agent["memory"].remember(
        content=data.get("content", ""),
        layer=data.get("layer", "core"),
    )
    return {"id": result.id, "created": result.created}


@app.delete("/api/memory/{memory_id}")
async def delete_memory(memory_id: str):
    """删除记忆"""
    agent = get_agent()
    result = await agent["memory"].storage.delete(memory_id)
    return {"ok": result.is_ok}


@app.get("/api/personality")
async def get_personality():
    """获取人格状态"""
    agent = get_agent()
    p = agent["memory"].get_personality()
    return {
        "H": p.honesty, "E": p.emotionality, "X": p.extraversion,
        "A": p.agreeableness, "C": p.conscientiousness, "O": p.openness,
    }


@app.put("/api/personality")
async def update_personality(request: Request):
    """更新人格"""
    data = await request.json()
    agent = get_agent()
    await agent["memory"].adjust_personality(data)
    return {"ok": True}


@app.get("/api/health")
async def health():
    """健康检查"""
    agent = get_agent()
    return {
        "status": "ok",
        "memory_count": await agent["memory"].storage.count(),
        "llm_connected": agent["settings"].openai_api_key is not None,
    }


@app.get("/api/stats")
async def stats():
    """统计信息"""
    agent = get_agent()
    return {
        "memory": {
            "total": await agent["memory"].storage.count(),
            "hot": await agent["memory"].storage.count(zone="hot"),
            "warm": await agent["memory"].storage.count(zone="warm"),
            "cold": await agent["memory"].storage.count(zone="cold"),
        },
        "personality": await get_personality(),
    }
```

### 3.4 前端页面（templates/index.html）

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Long Agent</title>
    <link rel="stylesheet" href="/static/style.css">
</head>
<body>
    <div class="container">
        <!-- 头部 -->
        <header>
            <h1>🤖 Long Agent v1.0</h1>
            <div class="status">
                <span id="memory-count">记忆: {{ memory_count }} 条</span>
                <span id="llm-status">LLM: {{ '已连接' if personality else '未连接' }}</span>
            </div>
        </header>

        <!-- 聊天区域 -->
        <main>
            <div id="chat-messages">
                <div class="msg agent">
                    <span class="avatar">🤖</span>
                    <div class="content">你好！我是 Long Agent，有什么可以帮你的？</div>
                </div>
            </div>
        </main>

        <!-- 输入区域 -->
        <footer>
            <input type="text" id="user-input" placeholder="输入消息..." autofocus>
            <button id="send-btn" onclick="sendMessage()">发送</button>
        </footer>
    </div>

    <!-- 侧边栏：记忆 & 人格 -->
    <aside id="sidebar">
        <div class="panel">
            <h3>🧠 人格状态</h3>
            <div id="personality-panel">
                <div class="trait"><span>H 诚实</span><progress value="50" max="100" id="p-H"></progress></div>
                <div class="trait"><span>E 情绪</span><progress value="50" max="100" id="p-E"></progress></div>
                <div class="trait"><span>X 外向</span><progress value="50" max="100" id="p-X"></progress></div>
                <div class="trait"><span>A 宜人</span><progress value="50" max="100" id="p-A"></progress></div>
                <div class="trait"><span>C 尽责</span><progress value="50" max="100" id="p-C"></progress></div>
                <div class="trait"><span>O 开放</span><progress value="50" max="100" id="p-O"></progress></div>
            </div>
        </div>
        <div class="panel">
            <h3>💭 最近记忆</h3>
            <div id="memory-panel"></div>
        </div>
    </aside>

    <script src="/static/app.js"></script>
</body>
</html>
```

### 3.5 前端样式（static/style.css）

```css
* { margin: 0; padding: 0; box-sizing: border-box; }

body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: #1a1a2e;
    color: #eee;
    display: flex;
    height: 100vh;
}

.container {
    flex: 1;
    display: flex;
    flex-direction: column;
    max-width: 800px;
    margin: 0 auto;
}

header {
    padding: 16px 20px;
    background: #16213e;
    border-bottom: 1px solid #0f3460;
    display: flex;
    justify-content: space-between;
    align-items: center;
}

header h1 { font-size: 18px; }

.status { font-size: 12px; color: #888; }
.status span { margin-left: 16px; }

main {
    flex: 1;
    overflow-y: auto;
    padding: 20px;
}

#chat-messages { display: flex; flex-direction: column; gap: 12px; }

.msg {
    display: flex;
    gap: 10px;
    max-width: 80%;
}

.msg.user { align-self: flex-end; flex-direction: row-reverse; }

.avatar {
    width: 32px;
    height: 32px;
    border-radius: 50%;
    background: #0f3460;
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
}

.content {
    padding: 10px 14px;
    border-radius: 12px;
    background: #0f3460;
    line-height: 1.5;
}

.msg.user .content { background: #e94560; }

footer {
    padding: 16px 20px;
    background: #16213e;
    border-top: 1px solid #0f3460;
    display: flex;
    gap: 10px;
}

#user-input {
    flex: 1;
    padding: 10px 14px;
    border: 1px solid #0f3460;
    border-radius: 8px;
    background: #1a1a2e;
    color: #eee;
    font-size: 14px;
}

#user-input:focus { outline: none; border-color: #e94560; }

#send-btn {
    padding: 10px 20px;
    background: #e94560;
    color: white;
    border: none;
    border-radius: 8px;
    cursor: pointer;
    font-size: 14px;
}

#send-btn:hover { background: #ff6b6b; }

/* 侧边栏 */
aside {
    width: 280px;
    background: #16213e;
    border-left: 1px solid #0f3460;
    padding: 16px;
    overflow-y: auto;
}

.panel { margin-bottom: 20px; }
.panel h3 { font-size: 14px; margin-bottom: 10px; color: #888; }

.trait {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 6px;
    font-size: 12px;
}

.trait span { width: 40px; }

progress {
    flex: 1;
    height: 4px;
    border-radius: 2px;
    background: #0f3460;
}

progress::-webkit-progress-value { background: #e94560; border-radius: 2px; }
```

### 3.6 前端逻辑（static/app.js）

```javascript
// static/app.js

let ws = null;

// 初始化 WebSocket
function initWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws = new WebSocket(`${protocol}//${window.location.host}/ws/chat`);
    
    ws.onmessage = (event) => {
        if (event.data === '[DONE]') {
            hideTyping();
            return;
        }
        appendMessage('agent', event.data);
    };
    
    ws.onclose = () => {
        console.log('WebSocket 断开，5秒后重连...');
        setTimeout(initWebSocket, 5000);
    };
}

// 发送消息
async function sendMessage() {
    const input = document.getElementById('user-input');
    const message = input.value.trim();
    if (!message) return;
    
    appendMessage('user', message);
    input.value = '';
    showTyping();
    
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(message);
    } else {
        // 降级到 HTTP
        try {
            const res = await fetch('/api/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ message }),
            });
            const data = await res.json();
            hideTyping();
            appendMessage('agent', data.response);
        } catch (e) {
            hideTyping();
            appendMessage('agent', '错误: ' + e.message);
        }
    }
}

// 添加消息到聊天区域
function appendMessage(role, content) {
    const messages = document.getElementById('chat-messages');
    const div = document.createElement('div');
    div.className = `msg ${role}`;
    div.innerHTML = `
        <span class="avatar">${role === 'user' ? '👤' : '🤖'}</span>
        <div class="content">${escapeHtml(content)}</div>
    `;
    messages.appendChild(div);
    messages.scrollTop = messages.scrollHeight;
}

// 显示输入中
function showTyping() {
    const messages = document.getElementById('chat-messages');
    const div = document.createElement('div');
    div.id = 'typing';
    div.className = 'msg agent';
    div.innerHTML = '<span class="avatar">🤖</span><div class="content">思考中...</div>';
    messages.appendChild(div);
    messages.scrollTop = messages.scrollHeight;
}

function hideTyping() {
    const el = document.getElementById('typing');
    if (el) el.remove();
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// 加载记忆列表
async function loadMemories() {
    try {
        const res = await fetch('/api/memory');
        const data = await res.json();
        const panel = document.getElementById('memory-panel');
        panel.innerHTML = data.memories.slice(0, 10).map(m =>
            `<div class="memory-item" title="${escapeHtml(m.content)}">
                <span class="layer">${m.layer}</span>
                ${escapeHtml(m.content.slice(0, 30))}...
            </div>`
        ).join('');
    } catch (e) {}
}

// 加载人格状态
async function loadPersonality() {
    try {
        const res = await fetch('/api/personality');
        const data = await res.json();
        for (const [k, v] of Object.entries(data)) {
            const el = document.getElementById(`p-${k}`);
            if (el) el.value = v;
        }
    } catch (e) {}
}

// 回车发送
document.getElementById('user-input').addEventListener('keypress', (e) => {
    if (e.key === 'Enter') sendMessage();
});

// 初始化
initWebSocket();
loadMemories();
loadPersonality();
```

---

## 四、启动方式

```bash
# 安装 FastAPI（如未安装）
pip install fastapi uvicorn jinja2 python-multipart

# 启动 Web UI
cd D:\github\三家PK\qwenpaw\代码
python -m uvicorn src.entry.web_ui:app --host 0.0.0.0 --port 8080 --reload

# 浏览器打开
# http://localhost:8080
```

---

## 五、功能测试清单

| 测试项 | 验证方式 | 预期结果 |
|--------|---------|---------|
| 发送消息 | 输入"你好"点击发送 | 收到 Agent 回复 |
| 记忆写入 | 输入"记住我喜欢简洁" | 记忆面板显示新记忆 |
| 记忆读取 | 输入"查看我的记忆" | 返回记忆列表 |
| 人格查看 | 打开侧边栏 | 显示 HEXACO 六维评分 |
| 流式输出 | 发送长文本请求 | 逐字显示回复 |
| 健康检查 | 访问 /api/health | 返回状态 JSON |
| 断线重连 | 关闭网络再打开 | 自动重连 |

---

> **方案版本**：v1.0
> **创建时间**：2026-05-04
> **预计开发时间**：2-3 小时
> **依赖**：fastapi, uvicorn, jinja2
