# AgentMind 项目优化实施方案

> 版本：v1.0
> 日期：2026-05-26
> 依据：`AGENTMIND_OPTIMIZATION_PLAN.md`
> 目标：把 AgentMind 从“能跑的异构 Agent 原型”逐步升级为“本地优先、可治理、可观测、可进化的异构 Agent 指挥控制平台”。

---

## 1. 实施原则

### 1.1 不做大爆炸重写

整个项目必须分阶段演进。每个阶段结束后，系统都应该可以正常启动、正常路由、正常调用 Agent、正常打开控制面板。

```text
允许：
  先加服务层
  再迁移调用方
  最后删除旧路径

不允许：
  一次性重写 router/main/panel/memory
  一次性切换所有数据结构
  在没有测试基线时大改核心链路
```

### 1.2 本地优先不能被破坏

实施过程中必须保证：

```text
无外网时：
  本地服务能启动
  本地控制台能打开
  本地配置能读写
  本地 Agent 能调用
  本地记忆能写入和检索
  本地路由规则能生效
```

外部 LLM、外部 embedding、飞书、远程 HTTP/A2A Agent 都只能是增强能力，不能成为核心链路硬依赖。

### 1.3 先收口，再扩展

先做：

```text
ConfigService
TaskService
RoutingService
MemoryService 收口
main.py / router.py / panel.py 拆分
```

再做：

```text
ProtocolGateway
StrategyManager
ChannelHub
OrchestrationEngine
AuditService
```

最后做：

```text
CPE
AgentShield
EvolutionEngine
TemplateMarket
```

### 1.4 每个阶段都要有验收标准

每个阶段必须同时满足：

```text
功能不退化
测试可运行
新旧路径有兼容
关键错误可观察
文档同步更新
```

---

## 2. 总体阶段规划

```text
Phase 0：准备与基线
  建测试基线、架构依赖清单、记忆检索评测集

Phase 1：服务层地基
  ConfigService、TaskService、main.py 瘦身、RoutingService 初步抽离

Phase 2：记忆系统收口
  MemoryService 唯一入口、新旧记忆兼容层、session 持久化、冲突检测、trace 从 memory 中剥离

Phase 3：平台核心能力
  ProtocolGateway、AgentCapabilityRegistry、StrategyManager、OrchestrationEngine

Phase 4：控制台与通道
  控制面板服务化、ChannelHub、飞书桥接收口、多通道统一

Phase 5：安全治理
  CPE、AgentShield、双池记忆、AuditService 完整闭环

Phase 6：自进化与生态
  EvolutionEngine、五类 evolver、TemplateMarket、可观测性完善
```

---

## 3. Phase 0：准备与基线

### 目标

在动核心架构前，先知道当前系统什么能跑、哪些地方风险最大。

### 主要工作

#### 0.1 建立测试基线

现有测试目录：

```text
tests/test_router.py
tests/test_stream.py
tests/test_attach.py
tests/test_orchestration.py
tests/test_memory.py
tests/test_panel_api.py
tests/test_cli_executor.py
tests/test_api_executor.py
tests/test_mcp_executor.py
tests/test_a2a_executor.py
tests/test_feishu_channel.py
tests/test_auth_integration.py
tests/test_e2e_scenarios.py
```

执行基线：

```bash
pytest
```

如果全量测试当前不能通过，先记录失败清单，不急着修所有历史问题。后续每个阶段至少保证被修改模块相关测试通过。

#### 0.2 建立架构依赖清单

列出当前直接依赖底层资源的位置：

```text
直接读写 YAML 的位置
直接访问 app.state 的位置
直接调用 record_task_* 的位置
直接调用 storage.memory 的位置
直接访问 _get_memory_conn 的位置
直接吞掉异常的位置
```

这份清单用于指导后续迁移顺序。

#### 0.3 建立记忆检索评测集

新增建议文件：

```text
tests/fixtures/memory_retrieval_cases.yaml
tests/test_memory_retrieval_eval.py
```

评测集至少覆盖：

```text
当前 session 查询
历史 session 查询
按日期查询
按主题查询
按 Agent 来源查询
展开第 N 条
还有别的吗
冲突记忆
敏感记忆隔离
```

### 验收标准

```text
有测试基线记录
有架构依赖清单
有记忆检索评测集初版
没有修改核心业务逻辑
```

---

## 4. Phase 1：服务层地基

### 目标

把“谁都能直接碰底层”的状态改成“核心能力通过服务层访问”。

### 1.1 ConfigService

#### 建议新增

```text
src/agentmind/services/__init__.py
src/agentmind/services/config_service.py
tests/test_config_service.py
```

#### 职责

```text
统一读取 settings.yaml / agents.yaml / routes.yaml / orchestrations.yaml
统一写入配置
提供默认值合并
提供敏感字段脱敏
提供写入锁
提供配置变更通知接口
```

#### 第一阶段迁移范围

先不要全量替换所有配置读取。第一阶段先接管：

```text
main.py 加载 settings
panel/server.py 保存 settings
panel/server.py 保存 routes
panel/server.py 保存 feishu config
agents/registry.py 读取 agents
```

#### 验收标准

```text
面板保存配置必须经过 ConfigService
敏感字段返回前自动脱敏
配置写入不会破坏 YAML 结构
相关测试通过
```

### 1.2 TaskService

#### 建议新增

```text
src/agentmind/services/task_service.py
tests/test_task_service.py
```

#### 职责

```text
start_task
mark_routing
mark_executing
complete_task
fail_task
record_attached_turn
query_tasks
get_task_detail
get_task_stats
```

#### 第一阶段迁移范围

先把这些直接调用逐步转发到 TaskService：

```text
record_task_start
record_task_update
record_task_end
record_attached_turn
```

旧函数可以先保留，但内部调用 TaskService，避免一次性改太多调用方。

#### 验收标准

```text
任务开始、执行、完成、失败都经过 TaskService
旧 record_task_* 调用仍兼容
tests/test_db.py、tests/test_router.py、tests/test_stream.py 相关测试通过
```

### 1.3 main.py 瘦身

#### 建议新增

```text
src/agentmind/startup/__init__.py
src/agentmind/startup/app_factory.py
src/agentmind/startup/auth.py
src/agentmind/startup/background_tasks.py
src/agentmind/startup/channels.py
src/agentmind/startup/routes.py
```

#### 拆分方向

```text
auth.py
  认证 token、Origin 校验、auth middleware

background_tasks.py
  健康检查、记忆清理、workspace 清理、stream 清理、memory workers

channels.py
  飞书启动和停止

routes.py
  注册 v1 API、panel API、静态资源

app_factory.py
  组装 FastAPI app
```

#### 验收标准

```text
main.py 只保留初始化和启动 uvicorn
服务启动日志不变
面板仍可访问
API 鉴权仍生效
tests/test_auth_integration.py 通过
```

### 1.4 RoutingService 初步抽离

#### 建议新增

```text
src/agentmind/services/routing_service.py
tests/test_routing_service.py
```

#### 职责

```text
处理普通请求的主流程
调用 SessionService 判断 /new
调用 OrchestrationService 判断编排
调用 AttachService 判断 attach
调用 RoutingPipeline 得到 decision
调用执行器执行
调用 TaskService 和 TraceService 记录
```

第一阶段只抽普通 `/v1/route` 主路径，不急着抽飞书 `route_stream` 和讨论模式。

#### 验收标准

```text
api/router.py 不再直接组织完整普通请求流程
原有 /v1/route 行为保持
tests/test_router.py、tests/test_stream.py 通过
```

---

## 5. Phase 2：记忆系统收口

### 目标

让 MemoryService 成为唯一记忆入口，逐步废弃 `storage/memory.py` 的重逻辑。

### 2.1 MemoryService 唯一入口

#### 修改方向

```text
storage/memory.py
  降级为兼容层，只保留 write_memory/search_memory/get_memory_stats 等旧 API
  内部全部转发到 MemoryService

memory/service.py
  成为唯一对外服务

memory/sqlite_store.py
  只负责存储实现
```

#### 迁移调用方

优先迁移：

```text
routing/side_effects/memory_writer.py
routing/middleware/memory_retriever.py
routing/side_effects/trace_recorder.py
api/orchestration.py
api/router.py
panel/server.py
```

#### 验收标准

```text
业务模块不再直接调用 _get_memory_conn
新写入统一经过 MemoryService
tests/test_memory.py 通过
```

### 2.2 Session 状态持久化

#### 建议新增

```text
src/agentmind/services/session_service.py
tests/test_session_service.py
```

#### 职责

```text
创建 session
关闭 session
记录 working memory
读取当前 session 上下文
处理 /new
维护 attach 绑定
维护讨论状态
```

先把 MemoryService 中的类变量状态迁出：

```text
_active_sessions
_force_new_next
_working_memory
```

#### 验收标准

```text
/new 后旧 session 关闭
新 session 上下文清空
服务重启后关键 session 状态可恢复
tests/test_attach.py、tests/test_memory.py 相关测试通过
```

### 2.3 trace 从 memory 中剥离

#### 建议新增

```text
src/agentmind/services/trace_service.py
tests/test_trace_service.py
```

#### 职责

```text
record_decision
record_strategy_run
get_trace
query_traces
```

TraceService 可以先继续复用 SQLite，但逻辑上不能再写入用户记忆。

#### 验收标准

```text
路由 trace 不再作为 memory_entries 写入
面板 trace 查询改走 TraceService
旧 trace 查询保留兼容迁移
```

### 2.4 记忆分层落地

#### 建议新增或扩展

```text
memory/migrations/002_memory_layers.sql
memory/repository.py
memory/types.py
memory/pipeline/write_pipeline.py
memory/pipeline/recall.py
```

#### 新数据结构

```text
raw_memory
memory_cards
sessions
working_memory
core_memory
result_sets
```

#### 验收标准

```text
新写入可以双写 raw_memory + memory_cards
检索可以优先走 memory_cards
旧 memory_entries 保留兼容
记忆评测集通过率不低于旧实现
```

### 2.5 记忆冲突检测

#### 建议新增

```text
src/agentmind/memory/conflict_detector.py
tests/test_memory_conflict_detector.py
```

#### 职责

```text
发现同一主题下互相矛盾的记忆
标记过期事实、冲突事实、低可信事实
给检索结果附带冲突提示
把冲突事件写入审计日志
```

#### 验收标准

```text
新写入记忆时会检测潜在冲突
检索到冲突记忆时不会静默返回单一答案
控制台能看到冲突记忆列表
冲突判断不删除原始记忆，只增加状态和解释
```

---

## 6. Phase 3：平台核心能力

### 目标

把 AgentMind 从“多个功能模块”提升成“统一平台核心”。

### 3.1 ProtocolGateway

#### 建议新增

```text
src/agentmind/connectors/__init__.py
src/agentmind/connectors/base.py
src/agentmind/connectors/cli.py
src/agentmind/connectors/http.py
src/agentmind/connectors/mcp.py
src/agentmind/connectors/a2a.py
src/agentmind/services/protocol_gateway.py
tests/test_protocol_gateway.py
```

#### 迁移方式

现有 executor 不要直接删除。先让 connector 包装现有 executor：

```text
CLIConnector -> CLIExecutor
HTTPConnector -> APIExecutor
MCPConnector -> MCPExecutor
A2AConnector -> A2AExecutor
```

稳定后再决定是否合并 executor 和 connector。

#### 验收标准

```text
CLI/HTTP/MCP/A2A 都能通过统一 gateway 调用
现有 executor 测试继续通过
tests/test_cli_executor.py、test_api_executor.py、test_mcp_executor.py、test_a2a_executor.py 通过
```

### 3.2 AgentCapabilityRegistry

#### 建议新增

```text
src/agentmind/services/capability_registry.py
tests/test_capability_registry.py
```

#### 职责

```text
维护 Agent 能力画像
记录协议类型
记录能力标签
记录安全等级
记录平均延迟
记录估算成本
记录历史成功率
记录最近错误
```

#### 验收标准

```text
路由可读取能力画像
控制台可展示能力画像
健康检查可更新可用性
```

### 3.3 StrategyManager

#### 建议新增

```text
src/agentmind/services/strategy_manager.py
tests/test_strategy_manager.py
```

#### 职责

```text
注册四策略主干
管理策略启停
管理策略顺序
管理策略插件注册
支持运行时热插拔
记录命中率
记录成功率
提供控制台查询接口
```

#### 四策略主干

```text
显式指定
规则路由
语义路由
能力评分兜底
```

安全扫描、候选池过滤、记忆判断属于前置中间件。

#### 验收标准

```text
RoutingPipeline 不再硬编码策略列表
控制台可查看策略顺序和状态
新增策略不需要改 router.py
禁用策略不需要重启主服务
tests/test_rule_engine.py、tests/test_router.py 通过
```

### 3.4 OrchestrationEngine

#### 建议新增

```text
src/agentmind/services/orchestration_service.py
src/agentmind/orchestration/__init__.py
src/agentmind/orchestration/engine.py
src/agentmind/orchestration/models.py
tests/test_orchestration_engine.py
```

#### 迁移范围

合并：

```text
api/orchestration.py 中的 DAG 管理
api/router.py 中的编排触发和执行逻辑
```

#### 验收标准

```text
编排触发只有一条执行路径
DAG 校验和执行逻辑集中在 OrchestrationEngine
tests/test_orchestration.py 通过
```

---

## 7. Phase 4：控制台与通道

### 目标

控制面板升级为控制台，通道层升级为 ChannelHub。

### 4.1 控制台服务化

#### 修改方向

```text
panel/server.py
  不再直接读写 YAML
  不再直接修改 agent_registry
  不再直接删除 memory 表数据
  不再直接启动飞书
```

所有操作改为调用：

```text
ConfigService
AgentService
TaskService
TraceService
MemoryService
OrchestrationService
ChannelService
AuditService
```

#### 验收标准

```text
面板 API 行为保持
面板所有写操作都有审计记录
tests/test_panel_api.py 通过
```

### 4.2 ChannelHub

#### 建议新增

```text
src/agentmind/services/channel_service.py
src/agentmind/channels/hub.py
src/agentmind/channels/api_channel.py
src/agentmind/channels/webhook.py
tests/test_channel_hub.py
```

#### 迁移方向

```text
FeishuAdapter
  只负责飞书消息收发和格式转换

ChannelHub
  负责把不同通道消息转为标准 Message

RoutingService
  负责处理标准 Message
```

#### 验收标准

```text
飞书通道不再直接依赖 route_stream
API / Webhook / 飞书都能走统一 Message
tests/test_feishu_channel.py、tests/test_feishu_path.py 通过
```

---

## 8. Phase 5：安全治理

### 目标

建立 CPE、AgentShield、双池记忆和审计闭环。

### 5.1 CPE

#### 建议新增

```text
src/agentmind/governance/__init__.py
src/agentmind/governance/cpe.py
tests/test_cpe.py
```

#### 职责

```text
判断哪些上下文可以给哪个 Agent
判断哪些记忆可以被哪个 Agent 读取
判断敏感信息是否必须留在本地
判断远程 Agent 是否需要用户确认
```

### 5.2 AgentShield

#### 建议新增

```text
src/agentmind/governance/agent_shield.py
tests/test_agent_shield.py
```

#### 职责

```text
拦截高风险命令
限制 Agent 工具权限
限制外部 API 访问
限制循环调用
触发高风险审批
```

### 5.3 AuditService

#### 建议新增

```text
src/agentmind/services/audit_service.py
tests/test_audit_service.py
```

#### 职责

```text
记录配置变更
记录路由决策
记录记忆访问
记录 CPE 判断
记录 AgentShield 拦截
记录自进化建议、确认、回滚
```

审计日志必须本地可用，不能依赖外部服务。第一版可以先写入 SQLite，后续再扩展导出能力。

#### 验收标准

```text
控制台关键写操作都有审计记录
敏感记忆访问有审计记录
安全拦截有审计记录
自进化变更有审计记录
审计日志可以按时间、模块、Agent、风险等级查询
```

### 5.4 双池记忆

#### 目标

```text
公共池：跨 Agent 可共享
私有池：用户或 Agent 隔离
```

访问私有池必须经过 CPE 判断。

### 验收标准

```text
敏感信息默认不流向远程 Agent
私有记忆不会被无权限 Agent 检索
高风险行为会被 AgentShield 拦截或记录
所有安全判断写入 AuditService
```

---

## 9. Phase 6：自进化与生态

### 目标

在稳定的数据和服务层基础上，实现可回滚的自进化闭环。

### 6.1 EvolutionEngine

#### 建议新增

```text
src/agentmind/evolution/__init__.py
src/agentmind/evolution/base.py
src/agentmind/evolution/engine.py
src/agentmind/evolution/route_evolver.py
src/agentmind/evolution/memory_evolver.py
src/agentmind/evolution/instinct_evolver.py
src/agentmind/evolution/prompt_evolver.py
src/agentmind/evolution/dag_evolver.py
tests/test_evolution_engine.py
```

#### 五类 evolver

```text
RouteEvolver
MemoryEvolver
InstinctEvolver
PromptEvolver
DAGEvolver
```

#### 安全要求

第一版自进化建议半自动：

```text
系统提出调整建议
控制台展示影响范围
用户确认后生效
效果变差可回滚
```

### 6.2 TemplateMarket

#### 建议新增

```text
src/agentmind/marketplace/__init__.py
src/agentmind/marketplace/service.py
tests/test_template_market.py
```

#### 模板类型

```text
Agent 配置模板
路由策略模板
DAG 编排模板
Prompt 模板
记忆策略模板
通道配置模板
```

### 验收标准

```text
自进化建议可审计
自进化变更可回滚
模板可导入导出
控制台可查看自进化效果
```

### 6.3 可观测性完善

#### 建议新增

```text
src/agentmind/services/observability_service.py
tests/test_observability_service.py
```

#### 职责

```text
聚合任务状态
聚合路由耗时
聚合 Agent 成功率
聚合记忆命中率
聚合通道健康状态
聚合安全拦截和审计事件
```

#### 控制台需要展示

```text
系统健康总览
Agent 可用性
路由命中与失败原因
记忆检索质量
通道收发状态
安全事件趋势
自进化建议效果
```

#### 验收标准

```text
控制台能解释一次请求为什么被路由给某个 Agent
控制台能解释一次请求失败在哪个环节
控制台能看到 Agent、通道、记忆、安全、自进化的核心指标
无外网时可观测性仍然可用
```

---

## 10. 跨阶段测试策略

### 每次改动至少跑

```bash
pytest tests/test_router.py tests/test_stream.py tests/test_memory.py -q
```

### 改 Agent 协议时跑

```bash
pytest tests/test_cli_executor.py tests/test_api_executor.py tests/test_mcp_executor.py tests/test_a2a_executor.py -q
```

### 改面板时跑

```bash
pytest tests/test_panel_api.py tests/test_auth_integration.py -q
```

### 改飞书或通道时跑

```bash
pytest tests/test_feishu_channel.py tests/test_feishu_path.py -q
```

### 改编排时跑

```bash
pytest tests/test_orchestration.py -q
```

### 阶段结束必须跑

```bash
pytest
```

---

## 11. 风险控制

### 最大风险 1：重构范围失控

控制方式：

```text
每次只迁移一个入口
旧函数先保留兼容
新服务先包旧逻辑
确认测试通过后再删除旧路径
```

### 最大风险 2：记忆迁移导致数据不可查

控制方式：

```text
新旧双写
旧表只读兼容
评测集回归
提供回滚开关
迁移脚本可重复执行
```

### 最大风险 3：控制台绕过服务层

控制方式：

```text
面板所有写操作必须走服务
服务层写审计
禁止面板直接写 YAML / SQLite
```

### 最大风险 4：自进化误改系统行为

控制方式：

```text
第一版只给建议
用户确认后生效
所有变更可回滚
所有变更写审计
```

---

## 12. 推荐第一批实施包

第一批不要试图完成整个平台，建议只做“地基包”。

### 实施包 1：ConfigService + TaskService

交付：

```text
ConfigService 初版
TaskService 初版
main.py 和 panel/server.py 部分迁移
旧 record_task_* 兼容转发
相关测试
```

验收：

```text
配置写入走 ConfigService
任务写入走 TaskService
原有 API 行为不变
pytest tests/test_db.py tests/test_panel_api.py tests/test_router.py -q 通过
```

### 实施包 2：RoutingService 抽离

交付：

```text
RoutingService 初版
/v1/route 普通路径迁移
route_stream 暂时保留旧路径
```

验收：

```text
普通 HTTP 路由行为不变
SSE 行为不变
pytest tests/test_router.py tests/test_stream.py -q 通过
```

### 实施包 3：MemoryService 收口

交付：

```text
storage/memory.py 变薄兼容层
MemoryService 统一 write/search/stats/cleanup
MemoryWriter 和 MemoryRetriever 迁移
```

验收：

```text
记忆写入和检索行为不变
新入口统一
pytest tests/test_memory.py tests/test_pipeline_executors.py -q 通过
```

### 实施包 4：记忆冲突检测 + AuditService

交付：

```text
MemoryConflictDetector 初版
AuditService 初版
记忆写入和检索接入冲突提示
控制台增加冲突记忆和审计日志查询
```

验收：

```text
冲突记忆不会被静默覆盖
敏感操作和配置变更可追踪
pytest tests/test_memory_conflict_detector.py tests/test_audit_service.py tests/test_panel_api.py -q 通过
```

### 实施包 5：StrategyManager 热插拔

交付：

```text
策略注册接口
策略启停接口
策略顺序调整接口
RoutingPipeline 改为从 StrategyManager 获取策略
控制台展示策略状态
```

验收：

```text
四策略主干保持完整
新增策略不修改 router.py
策略启停不破坏现有请求
pytest tests/test_strategy_manager.py tests/test_router.py tests/test_rule_engine.py -q 通过
```

---

## 13. 最终验收

整个实施方案完成后，应满足：

```text
main.py 只负责启动组装
api/router.py 不再承载所有业务流程
panel/server.py 不直接读写底层资源
配置统一走 ConfigService
任务统一走 TaskService
记忆统一走 MemoryService
路由策略由 StrategyManager 管理
协议调用由 ProtocolGateway 统一
通道接入由 ChannelHub 统一
trace 和 audit 独立于用户记忆
记忆冲突可发现、可解释、可审计
本地离线核心能力可用
控制台能解释状态、路由、记忆、任务、通道、安全事件
自进化有审计、有确认、有回滚
```

---

## 14. 执行顺序建议

```text
第 1 步：Phase 0，建立基线
第 2 步：实施包 1，ConfigService + TaskService
第 3 步：实施包 2，RoutingService 抽离
第 4 步：实施包 3，MemoryService 收口
第 5 步：实施包 4，记忆冲突检测 + AuditService
第 6 步：实施包 5，StrategyManager 热插拔
第 7 步：main.py 完整瘦身
第 8 步：panel/server.py 服务化
第 9 步：ProtocolGateway + CapabilityRegistry
第 10 步：OrchestrationEngine
第 11 步：ChannelHub
第 12 步：CPE + AgentShield + 双池记忆
第 13 步：EvolutionEngine + TemplateMarket + 可观测性
```

这个顺序的核心逻辑是：

```text
先把地基稳住，
再把平台骨架立起来，
最后再做安全、自进化和生态。
```
