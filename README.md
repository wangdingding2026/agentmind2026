# AgentMind v1.0.0

带记忆的 AI 指挥中枢。不造 Agent，只编排 Agent。

你安装 Claude Code、Hermes、Codex 等 AI 工具后，AgentMind 自动发现并统一入口，按规则和语义意图路由到合适的 Agent，并把关键对话、任务结果写入共享记忆库。后续任务可以检索历史上下文，也可以直接询问“今天聊过什么”“当前会话聊过什么”。支持 Web 面板、HTTP API 和飞书入口。

## 快速开始

```bash
pip install -e .
agentmind
```

浏览器打开 `http://127.0.0.1:8765/panel/`。

## 功能

### Agent 管理

启动时扫描 PATH，识别 8 种已知工具（Claude Code、Hermes、Codex、Aider、Cursor、Warp、Ollama、OpenClaw），同时自动探测未知 CLI 工具并生成配置。支持 CLI 子进程、HTTP API、MCP JSON-RPC、A2A 四种调用协议。每 60 秒健康检查，Agent 下线自动从候选池移除。

### 智能路由

3 层管线架构：

- **L0 前置中间件**：敏感信息扫描（API Key / 密码）→ 云端 Agent 自动降级到本地 → 候选池过滤 → 记忆上下文检索
- **L1 策略管道**：`@agent` 显式指定（置信度 1.0）→ LLM 语义意图分类 → 成本/延迟/安全信号加权评分兜底
- 策略短路机制：任一策略置信度 ≥ 0.7 即返回，最终策略永不弃权

执行层支持失败自动 fallback_chain 重试，流式 SSE 输出带断线重连和 backlog 回溯。

### 共享记忆

- **写入管线**：类型识别（事实/操作/过程）→ simhash 去重 → 重要性评分 → conversation 归并 → chunking 分片 → 双写 raw_memory + memory_cards → 可选富化 → 容量检查
- **检索管线**：core_memory 画像 → working_memory 近期对话 → FTS5 关键词检索 → 最近记忆 → 去重排序 → 可选 reranker 重排 → 原文展开 → ContextAssembler 拼装
- **历史查询**：`ConversationHistoryExecutor` 已接入主路径，支持今天、昨天、指定日期、当前会话的结构化问答回顾
- 冲突检测：标记矛盾事实，不静默覆盖
- 结果集分页：「展开第 N 条」「还有别的吗」

### 飞书接入

WebSocket 长连接，面板填写 App ID / Secret 即连。消息到达加 reaction 动画表示处理中，完成后移除并回复，标注来源 Agent。支持讨论 stop 检测（「停」/「结束」关键词）和通道侧 replay 指令。

### 多 Agent 讨论

`@agent1 @agent2 讨论/辩论 xxx` 触发多 Agent 轮流发言，每位基于前一位的论点回应（同意补充或反对反驳）。支持字数限制和 `response_path` JSON 提取。结束时第一个 Agent 自动生成四段式结构化总结（核心结论 / 共识点 / 分歧点 / 行动建议）。

### DAG 编排

控制面板画布拖拽定义步骤和依赖，一键执行。引擎层：DFS 循环检测 → Kahn 拓扑排序 → 前置步骤结果注入 prompt → 串行执行。通过触发词匹配激活。

### 控制面板

- 仪表盘：Agent 健康状态、任务统计
- Agent 管理：查看/启停/编辑 Agent 配置，运行时热加载
- 路由规则：routes.yaml 可视化编辑
- 编排画布：DAG 节点拖拽，连线定义依赖
- 记忆检索：全文搜索、团队知识库、向量检索、统计、清理
- 任务追踪：执行状态、时间线、流式输出实时查看

### 配置与运维

- 配置写入前验证 + 运行时热重载，格式错误不写坏文件
- 路由策略运行时注册/启停/排序（核心策略受保护不可删除）
- 审计日志：路由决策、配置变更、记忆访问
- 会话管理：`/new` 开启新会话，清空 Working Memory，关闭旧 conversation
- 后台任务：每小时记忆清理、每 5 分钟流监听清理、每小时 workspace 过期清理
- 共同记忆：普通记忆、团队知识库、Core Memory、关系记忆、向量检索统一进入检索上下文；新记忆可通过 core LLM 抽取为团队知识，旧数据不回填
- 记忆 Worker 调度器：归档、蒸馏和 importance 重算具备调度入口；embedding 启用时支持向量写入、语义检索和索引重建，默认使用纯 SQLite 保底，sqlite-vec 可用时保留加速入口

## API

```bash
TOKEN=$(cat ~/.agentmind/config/auth.token)
curl -H "Authorization: Bearer $TOKEN" \
  -X POST http://127.0.0.1:8765/v1/route \
  -H "Content-Type: application/json" \
  -d '{"message":"写一个hello world","stream":false}'
```

## 配置

`~/.agentmind/config/`：

- `agents.yaml`——Agent 注册和命令模板（自动发现生成）
- `routes.yaml`——路由规则（默认空，可通过策略管理器扩展）
- `settings.yaml`——core LLM、embedding、飞书、记忆参数、时区

## 技术栈

Python 3.10+ / FastAPI / Uvicorn / SQLite (WAL + FTS5) / YAML / SSE

## v1 边界

- AgentMind v1.0.0 是“稳定中枢版”：重点保证多入口路由、共享记忆、历史查询、任务记录、控制面板和基础编排可用。
- v1.0.0 已提供 LLM 知识抽取式团队知识库；只处理功能上线后的新记忆，不对历史旧数据做自动回填。
- v1.0.0 已提供基础向量写入、语义检索和索引重建。默认不强制安装 `sqlite-vec`，网络受限环境会使用纯 SQLite 保底检索。
- 深度关系图谱、自主任务拆解、自进化治理不是 v1 的强承诺能力，后续版本继续推进。
- 版本提交前的验证基线是 `python -m compileall -q src tests` 和 `python -m pytest -q` 全量通过。
- 外部真实端到端验证（飞书、MCP、A2A、外部 LLM、Embedding API）已由用户在真实环境完成。
- 正式发布前仍需执行安装/打包验收：`pip install -e .`、wheel 构建与安装、启动 `agentmind`、打开面板并确认静态资源加载正常。
