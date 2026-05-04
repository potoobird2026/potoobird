DONE: 文档对齐完成

执行摘要：
1. 已删除旧文档：D:\github\三家PK\qwenpaw\设计文档\10_Skill与MCP设计.md
2. 已删除旧代码：D:\github\三家PK\qwenpaw\代码\src\mcp\server.py
3. 已创建新文档：D:\github\三家PK\qwenpaw\设计文档\10_Skill管理模块设计.md
   - Skill 数据模型（11字段）
   - 核心API（register/unregister/enable/disable/configure/install_from_dir/export_skill）
   - 查询API（get/list_skills/get_active_skills）
   - Prompt注入（apply_prompt_injection）
   - 事件系统（registry.on/emit，支持async）
   - 存储（SQLite skills表，启动自动加载）
   - 目录结构（skills/{id}/SKILL.md + tools.py + config.json）
   - 安全（沙箱、用户确认、Fernet加密）
4. 已创建新文档：D:\github\三家PK\qwenpaw\设计文档\11_MCP客户端模块设计.md
   - 双传输方式（StdioMcpConnection + HttpMcpConnection）
   - 完整MCP协议流程（initialize → tools/list → tools/call）
   - 数据模型（McpServerConfig/McpToolInfo/McpServerInfo）
   - 核心API（8个方法）
   - 工具自动注册（mcp_{server_id}_{tool_name}，L2_CONFIRM）
   - 存储（mcp_servers + mcp_tools_cache表，启动自动重连）
   - 安全（命令/URL白名单、Fernet加密、L2确认）

完成时间：2026-05-04 22:44:04
