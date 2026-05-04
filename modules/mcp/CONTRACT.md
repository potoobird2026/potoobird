# MCP 模块 — 安全设计文档

> **版本**：v1.0 | **日期**：2026-05-05
> **设计文档**：MCP 模块安全设计
> **源码路径**：`src/mcp/`

---

## 一、模块定位

MCP（Model Context Protocol）模块是 Agent 的外部工具扩展桥梁，负责与 MCP 服务端建立连接、发现工具、代理调用。

**核心安全约束（主心骨）**：
> **纵深防御：传输安全（SSRF 防护 + 协议白名单）→ 命令白名单（stdio 模式）→ 凭据加密（Fernet + 环境变量优先）→ 工具调用审批（L2 确认级）。所有外部交互默认不可信，所有配置变更留痕可追溯。**

### 1.1 支持的双传输方式

| 传输方式 | 协议 | 连接类 | 安全等级 | 主要风险 |
|----------|------|--------|----------|----------|
| stdio | 子进程 stdin/stdout JSON-RPC | `StdioMcpConnection` | 中 | 命令注入、子进程逃逸 |
| HTTP | HTTP POST JSON-RPC | `HttpMcpConnection` | 高 | SSRF、凭据泄露、中间人攻击 |

---

## 二、双传输方式安全差异

### 2.1 stdio 传输安全模型

```
Agent → subprocess.Popen → MCP Server 子进程
         stdin (写入 JSON-RPC 请求)
         stdout (读取 JSON-RPC 响应)
         stderr (后台日志)
```

**安全特性**：
- 子进程在操作系统沙箱内运行，无法直接访问 Agent 内存
- 通信通过内核管道，不经过网络栈，天然免疫网络攻击
- 子进程生命周期由 Agent 完全控制（terminate/kill）

**安全风险**：
- **命令注入**：若 `command` 参数可被攻击者控制，可执行任意系统命令
- **参数注入**：`args` 中的参数若未校验，可能触发恶意行为
- **环境变量泄露**：`env` 可能包含敏感信息（API Key、密码），被子进程继承
- **子进程逃逸**：子进程可能产生后代进程，若 kill 不彻底则成为僵尸进程

**缓解措施**：
- 命令白名单（详见 §3）
- 参数列表化（不使用 shell=True，避免 shell 注入）
- 环境变量最小化（仅传递必要变量）
- 进程终止保障（terminate → 等待 → kill 三级退出）

### 2.2 HTTP 传输安全模型

```
Agent → httpx.AsyncClient → MCP Server (远程 HTTP endpoint)
         POST /mcp (JSON-RPC 请求)
         ← JSON-RPC 响应
```

**安全特性**：
- 可复用 HTTP 生态的成熟安全机制（TLS、认证、代理）
- 连接可配置超时，避免无限等待
- 支持自定义 headers（Bearer Token、API Key 等）

**安全风险**：
- **SSRF（服务端请求伪造）**：攻击者可能通过篡改 URL 访问内网服务
- **凭据泄露**：headers 中的认证信息若明文存储，泄露风险高
- **中间人攻击**：若未使用 HTTPS，通信内容可被窃听/篡改
- **DNS 重绑定攻击**：域名解析可能在连接前后发生变化

**缓解措施**：
- SSRF 防护（详见 §3）
- URL 协议白名单（详见 §4）
- 凭据加密存储（详见 §5）
- 建议使用 HTTPS（在 SSRF 检查中强制校验 scheme）

### 2.3 安全差异对比矩阵

| 安全维度 | stdio | HTTP |
|----------|-------|------|
| 命令注入 | ⚠️ 高风险（需白名单防护） | ✅ 无风险（不执行命令） |
| SSRF | ✅ 无风险（不访问网络） | ⚠️ 高风险（需 URL 过滤） |
| 凭据泄露 | ⚠️ 中风险（环境变量继承） | ⚠️ 中风险（headers 明文） |
| 中间人攻击 | ✅ 无风险（本地管道） | ⚠️ 中风险（需 HTTPS） |
| 服务逃逸 | ⚠️ 中风险（子进程管理） | ✅ 低风险（无进程创建） |
| 超时控制 | ✅ 内置（wait_for） | ✅ 内置（httpx timeout） |
| 审计日志 | ✅ 可审计（进程 PID） | ✅ 可审计（URL + 状态码） |

---

## 三、SSRF 防护

### 3.1 威胁模型

攻击者通过以下路径触发 SSRF：
1. 篡改 `McpServerConfig.url` 为内网地址（如 `http://169.254.169.254/latest/meta-data/`）
2. 利用 DNS 重绑定绕过单次检查
3. 通过重定向（302）跳转到内网地址

### 3.2 URL 黑名单

以下地址模式**禁止**作为 HTTP MCP 服务端目标：

```python
# ========== SSRF 防护：URL 黑名单 ==========

# Loopback 地址（指向本机）
BLOCKED_HOST_PATTERNS = [
    "localhost",
    "127.0.0.1",
    "127.0.0.0/8",         # 整个 loopback 段
    "::1",                  # IPv6 loopback
    "0.0.0.0",
]

# 私有网络地址（RFC 1918 + RFC 4193）
BLOCKED_HOST_PATTERNS += [
    "10.0.0.0/8",           # A 类私有地址
    "172.16.0.0/12",        # B 类私有地址
    "192.168.0.0/16",       # C 类私有地址
    "fc00::/7",             # IPv6 私有地址
]

# Link-local 地址
BLOCKED_HOST_PATTERNS += [
    "169.254.0.0/16",       # AWS 元数据 / link-local
    "fe80::/10",            # IPv6 link-local
]

# 特殊用途地址
BLOCKED_HOST_PATTERNS += [
    "100.64.0.0/10",        # 运营商级 NAT (CGN)
    "192.0.0.0/24",         # IETF 协议分配
    "192.0.2.0/24",         # TEST-NET-1（文档/示例）
    "198.51.100.0/24",      # TEST-NET-2
    "203.0.113.0/24",       # TEST-NET-3
    "224.0.0.0/4",          # 组播
    "240.0.0.0/4",          # 保留
    "255.255.255.255",      # 广播
]

# 云元数据端点（高频攻击目标）
BLOCKED_URL_PATTERNS = [
    "http://169.254.169.254/",          # AWS / Azure / GCP 元数据
    "http://metadata.google.internal/",  # GCP 元数据
    "http://metadata.azure.internal/",   # Azure 元数据
]
```

### 3.3 SSRF 检查实现

```python
import ipaddress
import socket
from urllib.parse import urlparse


def check_ssrf(url: str) -> tuple[bool, str]:
    """
    SSRF 防护检查。

    Returns:
        (is_safe, reason)
        is_safe=True  表示安全，is_safe=False 表示被阻止
    """
    parsed = urlparse(url)
    hostname = parsed.hostname

    if not hostname:
        return False, "URL 缺少主机名"

    # 1. 直接字符串匹配（快速路径）
    hostname_lower = hostname.lower().strip()
    for pattern in BLOCKED_HOST_PATTERNS:
        if "/" not in pattern:  # 非 CIDR
            if hostname_lower == pattern:
                return False, f"主机名匹配黑名单: {pattern}"
        # CIDR 范围检查在下面 IP 解析后处理

    # 2. DNS 解析 + IP 范围检查
    try:
        resolved_ips = socket.getaddrinfo(hostname, None)
        for family, _, _, _, sockaddr in resolved_ips:
            ip_str = sockaddr[0]
            ip = ipaddress.ip_address(ip_str)

            # 检查 loopback
            if ip.is_loopback:
                return False, f"解析到 loopback 地址: {ip}"

            # 检查私有网络
            if ip.is_private:
                return False, f"解析到私有地址: {ip}"

            # 检查 link-local
            if ip.is_link_local:
                return False, f"解析到 link-local 地址: {ip}"

            # 检查保留地址
            if ip.is_reserved:
                return False, f"解析到保留地址: {ip}"

            # CIDR 范围匹配
            for pattern in BLOCKED_HOST_PATTERNS:
                if "/" in pattern:
                    try:
                        network = ipaddress.ip_network(pattern, strict=False)
                        if ip in network:
                            return False, f"解析到黑名单 CIDR: {pattern}"
                    except ValueError:
                        continue

    except socket.gaierror:
        return False, f"DNS 解析失败: {hostname}"

    # 3. 检查端口（禁止非标准端口访问内网服务）
    port = parsed.port
    if port is not None:
        DANGEROUS_PORTS = {
            22,    # SSH
            23,    # Telnet
            3306,  # MySQL
            5432,  # PostgreSQL
            6379,  # Redis
            27017, # MongoDB
            9200,  # Elasticsearch
            11211, # Memcached
        }
        if port in DANGEROUS_PORTS:
            return False, f"端口 {port} 属于高危端口列表"

    return True, "通过 SSRF 检查"
```

### 3.4 重定向防护

```python
# httpx 客户端应禁止自动重定向，防止 302 跳转到内网
client = httpx.AsyncClient(
    follow_redirects=False,  # 禁止自动跟随重定向
    timeout=httpx.Timeout(30.0),
)

# 如需支持重定向，需对每个跳转目标重新执行 SSRF 检查
MAX_REDIRECTS = 3

async def safe_request(url: str, message: dict) -> dict:
    """带 SSRF 防护的安全 HTTP 请求"""
    current_url = url
    for redirect_count in range(MAX_REDIRECTS + 1):
        is_safe, reason = check_ssrf(current_url)
        if not is_safe:
            raise SecurityError(f"SSRF 阻止: {reason} (URL: {current_url})")

        response = await client.post(current_url, json=message)

        if response.status_code in (301, 302, 303, 307, 308):
            current_url = response.headers.get("Location", "")
            if not current_url:
                raise SecurityError("重定向响应缺少 Location header")
            logger.warning(f"重定向 #{redirect_count + 1}: {current_url}")
            continue

        return response.json()

    raise SecurityError(f"重定向次数超限 ({MAX_REDIRECTS})")
```

---

## 四、URL 协议白名单

### 4.1 允许的协议

```python
# ========== URL 协议白名单 ==========
ALLOWED_URL_SCHEMES = {"http", "https"}
```

**设计理由**：
- `https`：推荐。TLS 加密传输，防止中间人攻击
- `http`：兼容。仅用于可信内网环境（但 SSRF 防护已阻止内网地址）
- 禁止 `file://`：防止读取本地文件
- 禁止 `ftp://`：防止 FTP 协议滥用
- 禁止 `gopher://`：防止 Gopher 协议 SSRF 利用
- 禁止 `dict://`、`ldap://`、`tftp://` 等非 HTTP 协议

### 4.2 协议检查实现

```python
def check_url_scheme(url: str) -> tuple[bool, str]:
    """
    检查 URL 协议是否在白名单中。

    Returns:
        (is_allowed, reason)
    """
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()

    if not scheme:
        return False, "URL 缺少协议 scheme"

    if scheme not in ALLOWED_URL_SCHEMES:
        return False, (
            f"协议 '{scheme}' 不在白名单中。"
            f"允许的协议: {', '.join(sorted(ALLOWED_URL_SCHEMES))}"
        )

    return True, f"协议 '{scheme}' 已通过检查"
```

### 4.3 推荐配置

生产环境中应强制使用 HTTPS：

```python
# 生产环境推荐：仅允许 HTTPS
PRODUCTION_ALLOWED_SCHEMES = {"https"}

# 开发环境：允许 HTTP + HTTPS
DEV_ALLOWED_SCHEMES = {"http", "https"}
```

---

## 五、命令白名单加强

### 5.1 现有白名单机制

源码中已定义基础命令白名单：

```python
# client.py 中的现有白名单
SAFE_COMMANDS = {"npx", "node", "python", "python3", "deno", "bun"}
```

`connect()` 方法中已有校验：

```python
if config.command not in self.SAFE_COMMANDS:
    raise ValueError(f"命令不在白名单中: {config.command}")
```

### 5.2 加强方案：命令名 + 完整路径双重校验

**问题**：仅校验命令名存在绕过风险——攻击者可在 PATH 前面放置同名恶意可执行文件。

**方案**：同时允许命令名和完整路径两种指定方式：

```python
# ========== stdio 命令白名单（加强版） ==========

# 允许的命令名（将通过 which/where 解析为完整路径后二次校验）
SAFE_COMMAND_NAMES = {
    "npx",
    "node",
    "python",
    "python3",
    "deno",
    "bun",
}

# 允许的完整路径（精确匹配，优先级高于命令名）
# 格式：绝对路径，如 /usr/bin/python3
SAFE_COMMAND_PATHS = {
    # Linux / macOS
    "/usr/bin/node",
    "/usr/bin/python3",
    "/usr/bin/python",
    "/usr/bin/npx",
    "/usr/bin/deno",
    "/usr/bin/bun",
    "/usr/local/bin/node",
    "/usr/local/bin/python3",
    "/usr/local/bin/python",
    "/usr/local/bin/npx",
    "/usr/local/bin/deno",
    "/usr/local/bin/bun",
    # Windows
    "C:\\nodejs\\node.exe",
    "C:\\Python312\\python.exe",
    "C:\\Python311\\python.exe",
    "C:\\Program Files\\nodejs\\node.exe",
    "C:\\Program Files\\deno\\deno.exe",
}

# 允许的路径前缀（适用于 nvm、pyenv 等版本管理器）
SAFE_PATH_PREFIXES = (
    "/usr/bin/",
    "/usr/local/bin/",
    "/home/",              # 用户本地安装
    "C:\\nodejs\\",
    "C:\\Python",
    "C:\\Program Files\\nodejs\\",
    "C:\\Program Files\\deno\\",
    "C:\\bun\\",
)


def validate_command(command: str) -> tuple[bool, str]:
    """
    校验 stdio 命令是否安全。

    支持两种模式：
    1. 命令名模式：command="python3" → 在 SAFE_COMMAND_NAMES 中
    2. 完整路径模式：command="/usr/bin/python3" → 在 SAFE_COMMAND_PATHS 中
       或以 SAFE_PATH_PREFIXES 中某个前缀开头

    Returns:
        (is_safe, reason)
    """
    if not command or not command.strip():
        return False, "命令不能为空"

    command = command.strip()

    # 模式 1：完整路径匹配
    if "/" in command or "\\" in command:
        # 精确匹配
        if command in SAFE_COMMAND_PATHS:
            return True, f"命令路径精确匹配: {command}"

        # 前缀匹配
        for prefix in SAFE_PATH_PREFIXES:
            if command.startswith(prefix):
                # 额外校验：路径必须真实存在且为文件
                import os.path
                if os.path.isfile(command):
                    return True, f"命令路径前缀匹配: {prefix}"
                else:
                    return False, f"命令路径不存在: {command}"

        return False, (
            f"命令路径不在白名单中: {command}。"
            f"允许的路径: {', '.join(sorted(SAFE_COMMAND_PATHS))}"
        )

    # 模式 2：命令名匹配
    if command in SAFE_COMMAND_NAMES:
        # 解析完整路径并二次校验
        import shutil
        resolved = shutil.which(command)
        if resolved is None:
            return False, f"命令 '{command}' 在 PATH 中未找到"

        # 解析后的路径也必须在安全范围内
        for prefix in SAFE_PATH_PREFIXES:
            if resolved.startswith(prefix):
                return True, f"命令名匹配，解析路径: {resolved}"

        return False, (
            f"命令 '{command}' 解析到非预期路径: {resolved}。"
            f"请检查 PATH 环境变量是否被篡改"
        )

    return False, (
        f"命令 '{command}' 不在白名单中。"
        f"允许的命令名: {', '.join(sorted(SAFE_COMMAND_NAMES))}"
    )
```

### 5.3 参数安全校验

```python
def validate_args(args: list[str]) -> tuple[bool, str]:
    """
    校验命令行参数安全性。

    检查项：
    - 禁止 shell 元字符（; & | ` $ ( ) { } < > \n）
    - 禁止路径遍历（../）
    - 参数长度限制（单参数 ≤ 4096 字符）
    """
    SHELL_METACHARS = set(';&|`$(){}<>\n')

    for i, arg in enumerate(args):
        # 长度检查
        if len(arg) > 4096:
            return False, f"参数 #{i} 超长 ({len(arg)} > 4096)"

        # Shell 元字符检查
        if any(c in SHELL_METACHARS for c in arg):
            return False, f"参数 #{i} 包含 shell 元字符: {arg[:50]}"

        # 路径遍历检查
        if ".." in arg:
            return False, f"参数 #{i} 包含路径遍历: {arg[:50]}"

    return True, "参数校验通过"
```

---

## 六、API Key 加密存储

### 6.1 威胁模型

凭据在以下环节存在泄露风险：
1. **存储**：SQLite 数据库中明文存储 headers（含 Authorization、API Key）
2. **内存**：进程内存转储可能暴露明文凭据
3. **日志**：调试日志可能意外打印 headers
4. **传输**：HTTP 模式下 headers 通过网络传输

### 6.2 加密方案：Fernet + 环境变量优先

源码中 `crypto.py` 已实现 `McpCrypto` 类，本节为安全规范补充。

```python
# ========== API Key 加密存储策略 ==========

# 1. 加密算法：Fernet (AES-128-CBC + HMAC-SHA256)
#    - 来自 cryptography 库
#    - 保证机密性 + 完整性

# 2. 密钥管理优先级：
#    优先级 1：环境变量 MCP_ENCRYPTION_KEY
#    优先级 2：自动生成（仅用于开发，日志中提示持久化）

# 3. 加密范围：
#    - headers 中匹配以下模式的字段：
#      Authorization, X-API-Key, X-Token, X-Secret
#      *.key.*, *.token.*, *.secret.*, *.password.*
```

### 6.3 环境变量配置

```bash
# 生产环境：必须通过环境变量设置加密密钥
# 密钥生成命令：python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# Linux / macOS
export MCP_ENCRYPTION_KEY="your-fernet-key-base64-encoded="

# Windows PowerShell
$env:MCP_ENCRYPTION_KEY = "your-fernet-key-base64-encoded="
```

### 6.4 存储流程

```
用户配置 API Key
       │
       ▼
┌──────────────────┐
│  encrypt_headers() │ ← 使用 McpCrypto（Fernet 加密）
│  敏感字段加密      │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│  SQLite 存储      │ ← 密文存储（__ENC__: 前缀标记）
│  mcp_servers 表   │
└──────────────────┘

读取时反向流程：
SQLite → decrypt_headers() → httpx 请求
```

### 6.5 加密标记格式

```python
# 加密后的值格式（明文可识别）：
# 密文：__ENC__:gAAAAABl...
# 明文：不加密，原样存储

# 判断逻辑：
if value.startswith("__ENC__:"):
    # 这是加密字段，需要解密
    decrypt(value)
else:
    # 这是明文字段（非敏感字段或加密不可用）
    pass
```

### 6.6 日志安全

```python
# 禁止在日志中打印敏感信息
def safe_log_headers(headers: dict) -> dict:
    """脱敏后的 headers 用于日志打印"""
    sanitized = {}
    for k, v in headers.items():
        if McpCrypto.SENSITIVE_KEYS.match(k):
            sanitized[k] = "[REDACTED]"
        else:
            sanitized[k] = v
    return sanitized

# 使用示例
logger.info(f"MCP 请求: url={url}, headers={safe_log_headers(headers)}")
```

---

## 七、安全文档章节

### 7.1 MCP 安全规则总览

| 规则 ID | 规则名称 | 触发条件 | 处理方式 |
|---------|----------|----------|----------|
| MCP-S01 | SSRF 防护 | HTTP 模式发起请求前 | URL 黑名单检查，命中则阻止 |
| MCP-S02 | 协议白名单 | HTTP 模式配置 URL 时 | 仅允许 http/https，否则拒绝 |
| MCP-S03 | 命令白名单 | stdio 模式启动子进程前 | 命令名+路径双重校验，不在白名单则拒绝 |
| MCP-S04 | 参数校验 | stdio 模式传递 args 时 | 禁止 shell 元字符和路径遍历 |
| MCP-S05 | 凭据加密 | 存储 headers 到数据库前 | 敏感字段 Fernet 加密 |
| MCP-S06 | 日志脱敏 | 打印 headers 到日志时 | 敏感字段替换为 `[REDACTED]` |
| MCP-S07 | 重定向限制 | HTTP 模式收到 30x 响应 | 禁止自动跟随，手动检查后最多 3 次 |
| MCP-S08 | 超时控制 | 所有 MCP 调用 | 默认 30 秒超时，可配置 |
| MCP-S09 | 进程退出保障 | stdio 模式断开连接时 | terminate → 等待 5 秒 → kill |
| MCP-S10 | 工具调用审批 | 调用 MCP 工具时 | L2_CONFIRM 级别（需确认后执行） |

### 7.2 安全初始化检查清单

在 MCP 模块初始化时，应按以下顺序执行安全检查：

```
□ 1. 检查 cryptography 库是否可用（Fernet 加密依赖）
□ 2. 检查 MCP_ENCRYPTION_KEY 环境变量是否设置（生产环境必须）
□ 3. 检查数据库文件权限（应限制为当前用户可读写）
□ 4. 加载已保存的服务器配置时，验证每条配置的 URL 和 command
□ 5. 自动连接（auto_connect）前，对 HTTP 模式执行 SSRF 预检
□ 6. 记录初始化安全状态到审计日志
```

### 7.3 运行时安全监控

```python
# 安全事件类型
class SecurityEventType(Enum):
    SSRF_BLOCKED = "ssrf_blocked"           # SSRF 攻击被阻止
    SCHEME_REJECTED = "scheme_rejected"     # 非法协议被拒绝
    COMMAND_REJECTED = "command_rejected"   # 非法命令被拒绝
    ARGS_REJECTED = "args_rejected"         # 非法参数被拒绝
    DECRYPT_FAILED = "decrypt_failed"       # 凭据解密失败
    CONNECT_TIMEOUT = "connect_timeout"     # 连接超时
    TOOL_CALL_REJECTED = "tool_call_rejected"  # 工具调用被拒绝


@dataclass
class SecurityEvent:
    event_type: SecurityEventType
    server_id: str
    detail: str
    timestamp: str
    severity: str  # "low" | "medium" | "high" | "critical"
```

### 7.4 依赖安全

| 依赖 | 用途 | 安全要求 |
|------|------|----------|
| `cryptography` | Fernet 加密 | ≥41.0（包含最新安全补丁） |
| `httpx` | HTTP 客户端 | ≥0.27（支持 TLS 1.3） |
| `sqlite3` | 本地持久化 | 使用 Python 内置版本，保持 Python 更新 |

### 7.5 安全测试用例

```python
class TestMcpSecurity:
    """MCP 模块安全测试"""

    # SSRF 防护测试
    def test_ssrf_blocks_loopback(self):
        """阻止 loopback 地址"""
        is_safe, _ = check_ssrf("http://127.0.0.1/mcp")
        assert not is_safe

    def test_ssrf_blocks_private_ip(self):
        """阻止私有网络地址"""
        is_safe, _ = check_ssrf("http://192.168.1.1/mcp")
        assert not is_safe

    def test_ssrf_blocks_metadata_endpoint(self):
        """阻止云元数据端点"""
        is_safe, _ = check_ssrf("http://169.254.169.254/latest/meta-data/")
        assert not is_safe

    def test_ssrf_allows_public_url(self):
        """允许公网地址"""
        is_safe, _ = check_ssrf("https://api.example.com/mcp")
        assert is_safe

    # 协议白名单测试
    def test_scheme_blocks_file_protocol(self):
        """阻止 file:// 协议"""
        is_allowed, _ = check_url_scheme("file:///etc/passwd")
        assert not is_allowed

    def test_scheme_blocks_gopher_protocol(self):
        """阻止 gopher:// 协议"""
        is_allowed, _ = check_url_scheme("gopher://evil.com")
        assert not is_allowed

    def test_scheme_allows_https(self):
        """允许 https:// 协议"""
        is_allowed, _ = check_url_scheme("https://api.example.com/mcp")
        assert is_allowed

    # 命令白名单测试
    def test_command_rejects_rm(self):
        """阻止危险命令"""
        is_safe, _ = validate_command("rm")
        assert not is_safe

    def test_command_rejects_bash(self):
        """阻止 shell"""
        is_safe, _ = validate_command("bash")
        assert not is_safe

    def test_command_allows_python3(self):
        """允许 python3"""
        is_safe, _ = validate_command("python3")
        assert is_safe

    def test_command_allows_full_path(self):
        """允许完整路径"""
        is_safe, _ = validate_command("/usr/bin/python3")
        assert is_safe

    # 参数校验测试
    def test_args_rejects_semicolon(self):
        """阻止命令注入参数"""
        is_safe, _ = validate_args(["--output", "; rm -rf /"])
        assert not is_safe

    def test_args_rejects_path_traversal(self):
        """阻止路径遍历参数"""
        is_safe, _ = validate_args(["../../etc/passwd"])
        assert not is_safe

    # 加密测试
    def test_encrypt_decrypt_roundtrip(self):
        """加密/解密往返一致性"""
        crypto = McpCrypto()
        if crypto.is_available:
            original = "sk-test-api-key-12345"
            encrypted = crypto.encrypt_value(original)
            assert encrypted != original
            decrypted = crypto.decrypt_value(encrypted)
            assert decrypted == original

    def test_encrypt_headers_preserves_non_sensitive(self):
        """非敏感 header 不被加密"""
        crypto = McpCrypto()
        headers = {
            "Authorization": "Bearer sk-xxx",
            "Content-Type": "application/json",
        }
        encrypted = crypto.encrypt_headers(headers)
        assert encrypted["Content-Type"] == "application/json"  # 明文保留
        assert encrypted["Authorization"].startswith("__ENC__:")
```

---

## 八、接口契约

> 详见 `STANDARD.md` 中的完整接口定义。

### McpClientManager 安全相关接口

```python
class McpClientManager:
    # 安全校验（连接前自动调用）
    def _validate_config(self, config: McpServerConfig) -> None
    """完整安全校验：URL/命令/参数/协议"""

    def _check_ssrf(self, url: str) -> None
    """SSRF 检查，失败抛出 SecurityError"""

    def _check_command(self, command: str) -> None
    """命令白名单检查，失败抛出 SecurityError"""

    def _encrypt_config_headers(self, config: McpServerConfig) -> McpServerConfig
    """加密 config 中的敏感 headers"""

    def _decrypt_config_headers(self, config: McpServerConfig) -> McpServerConfig
    """解密 config 中的敏感 headers"""
```

### McpConnection 安全相关接口

```python
class HttpMcpConnection(McpConnection):
    async def safe_send_and_receive(self, message: dict) -> dict
    """带 SSRF 重定向防护的安全请求"""

class StdioMcpConnection(McpConnection):
    async def safe_connect(self) -> None
    """带命令白名单校验的安全连接"""
```

---

## 九、依赖

- **全局标准**：`GLOBAL_STANDARDS.md`
- **依赖模块**：
  - `security`（SecurityGuard 输入过滤、ApprovalModule 审批）
  - `execution/tool_registry`（工具注册，MCP 工具以 L2_CONFIRM 级别注册）
  - `config`（环境变量读取、加密密钥管理）
- **被依赖模块**：`loop`（AgentLoop 通过 MCP 调用外部工具）
- **第三方依赖**：
  - `cryptography ≥ 41.0`（Fernet 加密）
  - `httpx ≥ 0.27`（HTTP 客户端）

---

## 十、变更记录

| 日期 | 版本 | 变更内容 |
|------|------|----------|
| 2026-05-05 | v1.0 | 初版创建：SSRF 防护、协议白名单、命令白名单加强、API Key 加密存储、安全规则总览、测试用例 |
