# AgentMind

本地 AI 指挥中枢——智能路由 + 多 Agent 编排 + 飞书接入。

## 是什么

AgentMind 不"造"Agent，而是**指挥已有 Agent**。你安装 Claude Code、Hermes 等工具后，AgentMind 自动发现并提供统一入口，根据指令内容智能路由到最合适的 Agent 执行，结果通过控制面板、API 或飞书返回。

## 快速开始

```bash
pip install -e .
agentmind
```

启动后自动扫描已安装的 Agent，浏览器打开 `http://127.0.0.1:8765/panel/` 进入控制面板。

## 核心功能

- **6 步智能路由**：显式前缀 → 安全检测 → 规则引擎 → 语义路由 → 信号评分 → 兜底
- **DAG 可视化编排**：拖拽 Agent 节点，连线定义依赖，一键执行
- **飞书接入**：WebSocket 长连接，面板配置即连，消息回复标注 Agent 来源
- **共享记忆**：任务结果自动写入记忆库，支持检索和统计
- **控制面板**：仪表盘、Agent 管理、记忆审计、执行预览、编排画布
- **4 种协议**：CLI 子进程、HTTP API、MCP JSON-RPC、A2A

## API 测试

```bash
TOKEN=$(cat ~/.agentmind/config/auth.token)
curl -H "Authorization: Bearer $TOKEN" \
  -X POST http://127.0.0.1:8765/v1/route \
  -H "Content-Type: application/json" \
  -d '{"message":"写一个hello world","stream":false}'
```

## 配置

- `~/.agentmind/config/agents.yaml` — Agent 注册和命令模板
- `~/.agentmind/config/routes.yaml` — 路由规则
- `~/.agentmind/config/settings.yaml` — 语义路由 LLM、飞书通道等

## 技术栈

Python 3.12+ / FastAPI / Uvicorn / SQLite / React Flow
