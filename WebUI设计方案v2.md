# Long Agent Web UI 设计方案 v2.0

> **参考**：Open WebUI 界面风格
> **定位**：简洁现代的聊天界面，支持流式输出、记忆管理、人格配置
> **原则**：不复杂，能跑通主要功能测试即可

---

## 一、界面布局（参考 Open WebUI）

```
┌─────────────────────────────────────────────────────────────────────┐
│  🤝 Long Agent                                    ⚙️ 设置  👤 用户  │
├──────────┬──────────────────────────────────────────────────────────┤
│          │                                                          │
│  📁 会话  │  ┌────────────────────────────────────────────────────┐ │
│  ────────│  │                                                    │ │
│  # 会话1  │  │  👤 帮我记住我喜欢简洁风格                         │ │
│  # 会话2  │  │                                                    │ │
│  # 会话3  │  │  🤖 ✅ 已记住（core 层）                           │ │
│          │  │                                                    │ │
│  [+新建]  │  │  👤 查看我的记忆                                   │ │
│          │  │                                                    │ │
│  ────────│  │  🤖 找到以下记忆：                                  │ │
│  📊 状态  │  │  - [preference] 用户喜欢简洁                      │ │
│  记忆 128 │  │  - [project] Long Agent 开发中                    │ │
│  人格 H50 │  │                                                    │ │
│  运行中   │  └────────────────────────────────────────────────────┘ │
│          │                                                          │
│  ────────│  ┌────────────────────────────────────────────────────┐ │
│  ⚙️ 设置  │  │ 💬 输入消息...                        📎  ⬆️ 发送 │ │
│          │  └────────────────────────────────────────────────────┘ │
└──────────┴──────────────────────────────────────────────────────────┘
```

### Open WebUI 风格特点
- **左侧边栏**：会话列表 + 状态面板
- **中间主区域**：聊天消息流
- **底部输入框**：支持附件、回车发送
- **深色主题**：护眼，现代感
- **消息气泡**：左右区分用户/Agent
- **流式输出**：逐字显示，类似 ChatGPT

---

## 二、技术选型

| 组件 | 选型 | 理由 |
|------|------|------|
| 后端 | FastAPI | 已在项目依赖中 |
| 前端 | 纯 HTML + CSS + JS | 简单直接，无框架依赖 |
| 通信 | Server-Sent Events (SSE) | 比 WebSocket 简单，单向流式足够 |
| 样式 | 参考 Open WebUI 深色主题 | 现代美观 |

---

## 三、文件结构

```
src/entry/
├── cli.py          # 已有：CLI 入口
└── web_ui.py       # 新建：Web UI 入口

templates/
└── index.html      # 单页面聊天界面

static/
├── style.css       # 深色主题样式
└── app.js          # 前端逻辑（SSE 流式接收）
```

---

## 四、后端代码（src/entry/web_ui.py）

```python
"""Web UI 入口 — FastAPI + SSE 流式输出"""

import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import json

from src.config.settings import Settings, init_logging
from src.memory.manager import MemoryManager
from src.memory.storage.sqlite_storage import SQLiteStorage
from src.understanding.engine import UnderstandingEngine
from src.loop.agent_loop import AgentLoop

logger = logging.getLogger("long_agent.web")

app = FastAPI(title="Long Agent", version="0.1.0")

BASE_DIR = Path(__file__).parent.parent.parent
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# 全局 Agent 实例
_agent = None

def get_agent():
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
        _agent = {"loop": agent_loop, "memory": memory, "settings": settings}
    return _agent


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """主页"""
    agent = get_agent()
    memory_count = await agent["memory"].storage.count()
    personality = agent["memory"].personality
    return templates.TemplateResponse("index.html", {
        "request": request,
        "memory_count": memory_count,
        "personality": personality,
    })


@app.post("/api/chat")
async def chat_stream(request: Request):
    """SSE 流式聊天"""
    data = await request.json()
    user_input = data.get("message", "")
    agent = get_agent()
    
    async def generate():
        try:
            response = await agent["loop"].run(user_input)
            # 模拟流式输出（逐字符）
            for char in response:
                yield f"data: {json.dumps({'content': char})}\n\n"
            yield f"data: {json.dumps({'done': True})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
    
    return StreamingResponse(generate(), media_type="text/event-stream")


@app.get("/api/memory")
async def get_memories(layer: str = None, limit: int = 50):
    """获取记忆列表"""
    agent = get_agent()
    memories = await agent["memory"].search("", layer=layer, limit=limit)
    return {"memories": [{"id": m.id, "content": m.content, "layer": m.layer,
                          "category": m.category, "created_at": m.created_at} for m in memories]}


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
    p = agent["memory"].personality
    return {"H": p.get("H", 50), "E": p.get("E", 50), "X": p.get("X", 50),
            "A": p.get("A", 50), "C": p.get("C", 50), "O": p.get("O", 50)}


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
    return {"status": "ok", "memory_count": await agent["memory"].storage.count()}
```

---

## 五、前端页面（templates/index.html）

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
    <!-- 左侧边栏 -->
    <aside id="sidebar">
        <div class="sidebar-header">
            <h2>🤖 Long Agent</h2>
        </div>
        
        <!-- 会话列表 -->
        <div class="sidebar-section">
            <h3>📁 会话</h3>
            <div id="session-list">
                <div class="session-item active" onclick="switchSession(0)">
                    <span class="session-name"># 会话 1</span>
                </div>
            </div>
            <button class="new-session-btn" onclick="newSession()">+ 新建会话</button>
        </div>
        
        <!-- 状态面板 -->
        <div class="sidebar-section">
            <h3>📊 状态</h3>
            <div class="status-item">
                <span class="label">记忆</span>
                <span class="value" id="memory-count">{{ memory_count }} 条</span>
            </div>
            <div class="status-item">
                <span class="label">人格</span>
                <span class="value">H:{{ personality.H }} E:{{ personality.E }} X:{{ personality.X }}</span>
            </div>
            <div class="status-item">
                <span class="label">状态</span>
                <span class="value status-online">● 运行中</span>
            </div>
        </div>
        
        <!-- 设置 -->
        <div class="sidebar-section">
            <h3>⚙️ 快速设置</h3>
            <div class="setting-item">
                <label>模型</label>
                <select id="model-select">
                    <option value="gpt-4o">GPT-4o</option>
                    <option value="gpt-4o-mini">GPT-4o Mini</option>
                </select>
            </div>
        </div>
    </aside>

    <!-- 主聊天区域 -->
    <main id="chat-container">
        <!-- 聊天头部 -->
        <header id="chat-header">
            <h1>Long Agent — 以交付为核心的 AI 助手</h1>
        </header>
        
        <!-- 消息列表 -->
        <div id="chat-messages">
            <div class="message agent">
                <div class="avatar">🤖</div>
                <div class="content">
                    <p>你好！我是 Long Agent，有什么可以帮你的？</p>
                    <p>你可以试试：</p>
                    <ul>
                        <li>"记住我喜欢简洁风格" — 测试记忆写入</li>
                        <li>"查看我的记忆" — 测试记忆读取</li>
                        <li>"你的人格是什么" — 查看人格状态</li>
                    </ul>
                </div>
            </div>
        </div>
        
        <!-- 输入区域 -->
        <footer id="chat-input">
            <div class="input-wrapper">
                <textarea id="user-input" placeholder="输入消息... (Enter 发送, Shift+Enter 换行)" rows="1"></textarea>
                <button id="send-btn" onclick="sendMessage()">
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M22 2L11 13M22 2L15 22L11 13M11 13L2 9L22 2"/>
                    </svg>
                </button>
            </div>
        </footer>
    </main>

    <script src="/static/app.js"></script>
</body>
</html>
```

---

## 六、前端样式（static/style.css）

```css
/* ===== 深色主题（参考 Open WebUI） ===== */
:root {
    --bg-primary: #0f0f1a;
    --bg-secondary: #1a1a2e;
    --bg-tertiary: #16213e;
    --bg-input: #1e1e3a;
    --text-primary: #e8e8f0;
    --text-secondary: #8888a0;
    --accent: #6366f1;
    --accent-hover: #818cf8;
    --border: #2a2a4a;
    --user-bg: #3b3b5a;
    --agent-bg: transparent;
    --success: #22c55e;
    --warning: #f59e0b;
    --error: #ef4444;
}

* { margin: 0; padding: 0; box-sizing: border-box; }

body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Noto Sans SC', sans-serif;
    background: var(--bg-primary);
    color: var(--text-primary);
    display: flex;
    height: 100vh;
    overflow: hidden;
}

/* ===== 左侧边栏 ===== */
aside {
    width: 260px;
    background: var(--bg-secondary);
    border-right: 1px solid var(--border);
    display: flex;
    flex-direction: column;
    flex-shrink: 0;
}

.sidebar-header {
    padding: 16px;
    border-bottom: 1px solid var(--border);
}

.sidebar-header h2 {
    font-size: 16px;
    font-weight: 600;
}

.sidebar-section {
    padding: 12px;
    border-bottom: 1px solid var(--border);
}

.sidebar-section h3 {
    font-size: 11px;
    text-transform: uppercase;
    color: var(--text-secondary);
    margin-bottom: 8px;
    letter-spacing: 0.5px;
}

.session-item {
    padding: 8px 10px;
    border-radius: 6px;
    cursor: pointer;
    font-size: 13px;
    margin-bottom: 2px;
}

.session-item:hover { background: var(--bg-tertiary); }
.session-item.active { background: var(--accent); color: white; }

.new-session-btn {
    width: 100%;
    padding: 8px;
    background: transparent;
    border: 1px dashed var(--border);
    border-radius: 6px;
    color: var(--text-secondary);
    cursor: pointer;
    font-size: 12px;
    margin-top: 4px;
}

.new-session-btn:hover {
    border-color: var(--accent);
    color: var(--accent);
}

.status-item {
    display: flex;
    justify-content: space-between;
    padding: 6px 0;
    font-size: 12px;
}

.status-item .label { color: var(--text-secondary); }
.status-item .value { color: var(--text-primary); }
.status-online { color: var(--success); }

.setting-item { margin-bottom: 8px; }
.setting-item label { display: block; font-size: 11px; color: var(--text-secondary); margin-bottom: 4px; }
.setting-item select {
    width: 100%;
    padding: 6px 8px;
    background: var(--bg-input);
    border: 1px solid var(--border);
    border-radius: 4px;
    color: var(--text-primary);
    font-size: 12px;
}

/* ===== 主聊天区域 ===== */
#chat-container {
    flex: 1;
    display: flex;
    flex-direction: column;
    min-width: 0;
}

#chat-header {
    padding: 12px 20px;
    border-bottom: 1px solid var(--border);
    font-size: 14px;
    color: var(--text-secondary);
}

#chat-messages {
    flex: 1;
    overflow-y: auto;
    padding: 20px;
    display: flex;
    flex-direction: column;
    gap: 16px;
}

/* ===== 消息气泡 ===== */
.message {
    display: flex;
    gap: 12px;
    max-width: 85%;
    animation: fadeIn 0.2s ease;
}

@keyframes fadeIn {
    from { opacity: 0; transform: translateY(4px); }
    to { opacity: 1; transform: translateY(0); }
}

.message.user {
    align-self: flex-end;
    flex-direction: row-reverse;
}

.avatar {
    width: 32px;
    height: 32px;
    border-radius: 6px;
    background: var(--bg-tertiary);
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    font-size: 16px;
}

.message.user .avatar { background: var(--accent); }

.content {
    padding: 10px 14px;
    border-radius: 12px;
    line-height: 1.6;
    font-size: 14px;
}

.message.agent .content {
    background: var(--agent-bg);
    border: 1px solid var(--border);
}

.message.user .content {
    background: var(--user-bg);
}

.content p { margin-bottom: 4px; }
.content ul, .content ol { padding-left: 20px; margin: 4px 0; }
.content li { margin-bottom: 2px; }
.content code {
    background: var(--bg-input);
    padding: 2px 6px;
    border-radius: 4px;
    font-size: 13px;
}

/* ===== 输入区域 ===== */
#chat-input {
    padding: 16px 20px;
    border-top: 1px solid var(--border);
}

.input-wrapper {
    display: flex;
    gap: 8px;
    align-items: flex-end;
    background: var(--bg-input);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 8px 12px;
}

.input-wrapper:focus-within {
    border-color: var(--accent);
}

#user-input {
    flex: 1;
    background: transparent;
    border: none;
    color: var(--text-primary);
    font-size: 14px;
    resize: none;
    max-height: 120px;
    line-height: 1.5;
    font-family: inherit;
}

#user-input:focus { outline: none; }
#user-input::placeholder { color: var(--text-secondary); }

#send-btn {
    width: 36px;
    height: 36px;
    background: var(--accent);
    border: none;
    border-radius: 8px;
    color: white;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
}

#send-btn:hover { background: var(--accent-hover); }
#send-btn:disabled { opacity: 0.5; cursor: not-allowed; }

/* ===== 滚动条 ===== */
::-webkit-scrollbar { width: 6px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: var(--text-secondary); }

/* ===== 响应式 ===== */
@media (max-width: 768px) {
    aside { display: none; }
    .message { max-width: 90%; }
}
```

---

## 七、前端逻辑（static/app.js）

```javascript
// static/app.js

let isStreaming = false;
let currentSessionId = 0;

// 发送消息
async function sendMessage() {
    if (isStreaming) return;
    
    const input = document.getElementById('user-input');
    const message = input.value.trim();
    if (!message) return;
    
    // 添加用户消息
    appendMessage('user', message);
    input.value = '';
    input.style.height = 'auto';
    
    // 创建 Agent 消息容器
    const agentMsgId = appendMessage('agent', '');
    const contentEl = agentMsgId.querySelector('.content');
    
    isStreaming = true;
    document.getElementById('send-btn').disabled = true;
    
    try {
        const response = await fetch('/api/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message }),
        });
        
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        
        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            
            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n\n');
            buffer = lines.pop();
            
            for (const line of lines) {
                if (line.startsWith('data: ')) {
                    try {
                        const data = JSON.parse(line.slice(6));
                        if (data.content) {
                            contentEl.textContent += data.content;
                            scrollToBottom();
                        }
                        if (data.done) {
                            isStreaming = false;
                            document.getElementById('send-btn').disabled = false;
                            loadMemories();
                        }
                        if (data.error) {
                            contentEl.textContent = '❌ ' + data.error;
                        }
                    } catch (e) {}
                }
            }
        }
    } catch (e) {
        contentEl.textContent = '❌ 连接错误: ' + e.message;
        isStreaming = false;
        document.getElementById('send-btn').disabled = false;
    }
}

// 添加消息
function appendMessage(role, content) {
    const messages = document.getElementById('chat-messages');
    const div = document.createElement('div');
    div.className = `message ${role}`;
    div.innerHTML = `
        <div class="avatar">${role === 'user' ? '👤' : '🤖'}</div>
        <div class="content">${escapeHtml(content)}</div>
    `;
    messages.appendChild(div);
    scrollToBottom();
    return div;
}

// 滚动到底部
function scrollToBottom() {
    const messages = document.getElementById('chat-messages');
    messages.scrollTop = messages.scrollHeight;
}

// HTML 转义
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
        document.getElementById('memory-count').textContent = data.memories.length + ' 条';
    } catch (e) {}
}

// 新建会话
function newSession() {
    currentSessionId++;
    document.getElementById('chat-messages').innerHTML = '';
    appendMessage('agent', '新会话已开始，有什么可以帮你的？');
    
    const sessionList = document.getElementById('session-list');
    const div = document.createElement('div');
    div.className = 'session-item';
    div.innerHTML = `<span class="session-name"># 会话 ${currentSessionId + 1}</span>`;
    div.onclick = () => switchSession(currentSessionId);
    sessionList.appendChild(div);
}

function switchSession(id) {
    document.querySelectorAll('.session-item').forEach(el => el.classList.remove('active'));
    // 简化：实际应该加载对应会话的消息
}

// 回车发送
document.getElementById('user-input').addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
    }
});

// 自动调整输入框高度
document.getElementById('user-input').addEventListener('input', function() {
    this.style.height = 'auto';
    this.style.height = Math.min(this.scrollHeight, 120) + 'px';
});

// 初始化
loadMemories();
```

---

## 八、启动方式

```bash
# 安装依赖
pip install fastapi uvicorn jinja2 python-multipart

# 启动
cd D:\github\三家PK\qwenpaw\代码
python -m uvicorn src.entry.web_ui:app --host 0.0.0.0 --port 8080 --reload

# 浏览器打开
# http://localhost:8080
```

---

> **方案版本**：v2.0（参考 Open WebUI 风格）
> **创建时间**：2026-05-04
> **预计开发时间**：2 小时
> **新增文件**：3 个（web_ui.py + index.html + style.css + app.js）
