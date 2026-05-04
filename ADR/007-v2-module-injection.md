# ADR-007: V2模块接入AgentLoop决策

## 状态
Accepted

## 日期
2026-05-03

## 背景
V2新增了BSupervisor、ContextCompressor、ResultVerifier、ReportGenerator等模块，
需要决定如何接入现有的AgentLoop主循环。

## 决策
采用"可选注入+降级"策略：
- 所有V2模块通过构造函数参数注入
- 未注入时自动降级为V1行为
- 不破坏V1已有的410个测试

## 后果
- ✅ 向后兼容，V1功能不受影响
- ✅ 渐进式升级，可按需启用V2模块
- ⚠️ 构造函数参数增多（当前11个参数）

## 相关
- DESIGN-V2.md 第十七章
- src/loop/agent_loop.py 构造函数
