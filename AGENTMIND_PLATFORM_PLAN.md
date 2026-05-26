# AgentMind 平台化改造方案

> 目标：将 AgentMind 从"能跑的功能车"升级为"异构 Agent 指挥控制平台"
> 原则：先修地基，再盖楼；每阶段结束后系统都能正常运行

---

## 一、当前架构问题总览

三份复盘结论一致，核心问题只有 3 个字：**管不住**。

```
当前架构示意图：

  用户请求 ──→ main.py（总管 + 保安 + 清洁工 + 飞书接线员）
                  │
                  ├── api/router.py（HTTP/飞书/编排/讨论/attach 全管）
                  │       │
                  │       ├── routing/pipeline.py ──→ 5 个硬编码策略
                  │       ├── agents/4个executor ──→ 各干各的
                  │       ├── storage/memory.py ←──→ memory/service.py  ← 循环依赖
                  │       │       (老记忆)              (v4 新记忆)
                  │       └── panel/server.py ──→ 直接 __import__ 私有函数
                  │                             ──→ 直接读写 YAML 无锁
                  │
                  └── channels/feishu.py（唯一通道）

  问题：
  1. main/router/panel 三个"总管"互相伸手
  2. 新旧记忆双轨并存，循环依赖
  3. 配置散落 10+ 处，没有统一入口
  4. 抽象层（IMemoryStore）形同虚设，20+ 处绕过
  5. 162 处异常被吞，出错不可见
  6. 进程内状态（session/讨论/attach）重启即丢
```

---

## 二、目标架构

```
目标架构示意图：

  用户请求 ──→ ChannelHub（飞书/API/Web/Slack/...）
                  │
                  ├── ProtocolGateway（CLI/HTTP/MCP/A2A 统一调用）
                  │       │
                  │       └── AgentCapabilityRegistry（能力/成本/风险/延迟）
                  │
                  ├── RoutingPipeline ──→ RoutingStrategyManager（可插拔策略）
                  │       │
                  │       ├── PolicyEngine / AgentShield（权限/护栏/隔离）
                  │       └── OrchestrationEngine（DAG 并行/补偿/上下文）
                  │
                  ├── MemoryService（统一入口）
                  │       ├── 短期池（working memory）
                  │       ├── 长期池（episodic/semantic/procedural）
                  │       └── 冲突检测 + 双池隔离
                  │
                  ├── ConfigService（配置中心，统一读写）
                  ├── TaskService（任务全生命周期）
                  ├── AuditLogService（审计日志）
                  │
                  ├── EvolutionEngine（自进化闭环）
                  │       ├── 路由进化 / 记忆进化 / 本能进化
                  │       └── Prompt 进化 / DAG 进化
                  │
                  └── ControlPanel ──→ TemplateMarket（模板市场）

  关键变化：
  ┌──────────────────────┬─────────────────────┬──────────────────────────────────────┐
  │ 维度                 │ 现在                │ 目标                                 │
  ├──────────────────────┼─────────────────────┼──────────────────────────────────────┤
  │ 入口                 │ 3 个总管互相伸手    │ 每个模块单一职责，通过服务层交互     │
  │ 配置                 │ 10+ 处各自读 YAML   │ ConfigService 统一读写 + 加锁        │
  │ 记忆                 │ 新旧双轨 + 循环依赖 │ 单轨 MemoryService + 双池隔离        │
  │ 任务                 │ record_task_* 散落  │ TaskService 管全生命周期              │
  │ 协议                 │ 4 个独立 executor   │ ProtocolGateway + 能力注册表         │
  │ 路由                 │ 硬编码策略          │ 可插拔 + 可评估 + 自进化             │
  │ 安全                 │ 正则扫 API key      │ PolicyEngine + AgentShield + 审计    │
  │ 通道                 │ 只有飞书            │ ChannelHub + 多适配器                │
  │ 进化                 │ 无                  │ 5 类闭环 evolver                     │
  │ 可观测               │ P50/P90/P99         │ Metrics + Tracing + Health           │
  └──────────────────────┴─────────────────────┴──────────────────────────────────────┘
```

### 架构变化是否符合长远发展？

**符合，且是必要的。** 理由：

1. **从"函数调用"到"服务层"** —— 现在各模块之间直接 import 函数、直接写 SQL，这不是平台该有的样子。改为服务层后，未来加权限、加缓存、加集群都只改服务层，不动业务代码。

2. **从"双轨"到"单轨 + 双池"** —— 双轨是历史遗留，双池是设计。统一记忆入口后，公共池和私有池是同一个 MemoryService 的两种策略，而不是两套独立代码。未来加新的记忆类型（比如协作记忆、组织记忆）只需加策略，不用加代码库。

3. **从"硬编码策略"到"可插拔 + 自进化"** —— 这是平台和工具的核心区别。工具的策略是写死的，平台的策略是可以被评估和优化的。RoutingStrategyManager 是自进化的前提。

4. **从"只有飞书"到"多通道"** —— ChannelHub 让新增通道变成"写一个适配器"的事，而不是"改 router.py"的事。

5. **从"吞异常"到"可观测"** —— 自进化依赖三件事：任务有没有完整记录、路由决策是否可追溯、结果好不好。这三件事现在不够稳。AuditLogService + TaskService + 可观测性是自进化的地基。

---

## 三、分阶段执行方案

### 第一阶段：修地基（6-8 周）

> 目标：让底座稳定，消除双轨、总管、配置散落三大隐患
> 完成后：系统功能不变，但内部结构清晰，后续加模块不会越加越乱

#### 1.1 ConfigService（配置中心）⏱ 1 周

```
新增：src/agentmind/services/config_service.py

做什么：
- 启动时读一次 settings.yaml / agents.yaml / routes.yaml，缓存在内存
- 全项目从 ConfigService.get("memory.v4_enabled") 取值，不再各自 open yaml
- update() 方法：校验 + 加锁 + 写盘 + 通知订阅者
- 面板改配置 → 调 ConfigService.update()，不再直接写文件

干掉什么：
- 10+ 处 _load_settings() 副本
- panel/server.py 里的 inline yaml read-modify-write
- 特性开关每次从磁盘读的问题

为什么先做：后面所有服务（TaskService/MemoryService/EvolutionEngine）
           都依赖配置中心，它是最底层的砖。
```

#### 1.2 MemoryService 收口（统一记忆入口）⏱ 2-3 周

```
改什么：
- 评估 v4 是否稳定（看测试 + 实际运行数据）
  ├─ 稳定 → storage/memory.py 降级为薄兼容层（只转发，不写逻辑）
  └─ 不稳定 → 关掉 v4 开关，专心修 v4，不要双轨
- 打破 storage/memory.py ↔ memory/service.py 循环依赖
- MemoryService 改为显式单例（不是类变量伪单例）
- 所有 MemoryService() 改为从工厂/注入获取同一实例
- 收拢 _get_conn() 直连 SQL → 统一走 IMemoryStore 方法
  特别是级联删除（6 处重复合并为 1 个方法）

干掉什么：
- storage/memory.py 中和 v4 重叠的逻辑（约 400 行）
- 6 处级联删除重复代码
- MemoryService 类变量伪单例

为什么必须做：Agent 级共享记忆、双池记忆、冲突检测全部依赖单一记忆入口。
           双轨不改，后面加什么都会"写进去搜不到"。
```

#### 1.3 拆 api/router.py（入口拆分）⏱ 1-2 周

```
拆成：
src/agentmind/api/
├── routes/
│   ├── single.py          # 普通 /v1/route
│   ├── stream.py          # SSE 流式（和 single 共用核心决策函数）
│   ├── discussion.py      # 多 Agent 讨论（_run_discussion 独立）
│   ├── orchestration.py   # 编排触发（和现有 api/orchestration.py 合并）
│   └── attach.py          # attach 模式
├── models.py              # Pydantic 模型（保持不变）

核心：route_request 和 route_stream 合并为一个决策函数，
     只有输出格式不同（JSON vs SSE）。

干掉什么：
- router.py 570 行大文件
- route_request / route_stream 重复逻辑
- 编排执行的两套路径（router.py + orchestration.py）

为什么必须做：路由、编排、多通道、自进化不能挤在一个文件里。
           拆完才能独立迭代。
```

#### 1.4 拆 main.py 的 lifespan（启动拆分）⏱ 1 周

```
拆成：
src/agentmind/startup/
├── health_check.py    # Agent 健康检查（60s 周期）
├── feishu.py          # 飞书通道启动
├── memory_workers.py  # 记忆 Worker 启动
├── cleanup.py         # 周期清理任务
└── __init__.py        # 按顺序调用各启动器

main.py 只负责：创建 app → 注册路由 → 调用 startup

为什么做：lifespan 100 行管 5 件事，改一个容易影响其他。
```

#### 1.5 异常可观测化（清理静默异常）⏱ 1 周

```
改什么：
- 162 处 except Exception: pass → 至少 logger.exception(trace_id, module)
- 关键链路（记忆写入、路由决策）的失败返回错误码，不要静默
- 后台任务失败 → 记录到 task_history，而不是消失

原则：不是所有错误都要打断主流程，但必须记录清楚：
      哪个模块、哪个用户、哪个 trace_id、失败原因

为什么做：自进化依赖"结果到底好不好"这个信息。
         现在失败被吞掉，进化就无从谈起。
```

#### 1.6 TaskService（任务全生命周期）⏱ 1 周

```
新增：src/agentmind/services/task_service.py

做什么：
- 统一管理任务状态：start / update / complete / fail / cancel
- 干掉散落在 router.py、executors、side_effects 里的 record_task_* 调用
- 任务记录包含：trace_id、路由决策、Agent、耗时、结果质量
- 超时/重试策略集中管理

为什么做：可观测性、审计日志、自进化评估都依赖完整的任务记录。
         现在任务记录分散，容易漏记、错记。
```

#### 1.7 Session 持久化（进程内状态外置）⏱ 1 周

```
改什么：
- working memory / 讨论状态 / attach 绑定 → SQLite 表
- MemoryService 的类变量伪单例 → 显式 SessionStore
- 服务重启后状态不丢

为什么做：离线可用、多通道连续对话、Agent 记忆都需要持久化。
         现在重启就丢，这是平台的硬伤。
```

#### 第一阶段结束时的架构变化

```
修改前                              修改后
──────                              ──────
main.py (lifespan 100行)     →     main.py (20行) + startup/ (5个模块)
api/router.py (570行)        →     api/routes/ (5个独立模块)
storage/memory.py (741行)    →     兼容层(~100行) + memory/service.py (统一入口)
10+ 处各自读 settings.yaml   →     ConfigService (单一来源)
record_task_* 散落           →     TaskService (统一管理)
162 处吞异常                 →     全部 logger.exception + 错误码
session 在内存               →     SessionStore (SQLite 持久化)

代码量变化：
  删除约 800 行重复/废弃代码
  新增约 600 行（服务层 + startup 模块）
  净减约 200 行，但结构更清晰
```

---

### 第二阶段：平台化（4-6 周）

> 目标：从"能跑"变成"能管理"
> 完成后：系统能力不变，但可管理、可观测、可审计

#### 2.1 ProtocolGateway（协议网关）⏱ 1-2 周

```
新增：src/agentmind/connectors/

做什么：
- 统一 Connector 接口：connect / invoke / stream / health / capabilities
- 4 个现有 executor 改为实现该接口的 connector
- 补齐 MCP/A2A 的协议握手、能力发现、错误重试
- 调用格式归一化：任何协议进来的请求都变成统一的 TaskRequest

为什么做：多协议统一是你的核心目标。现在 4 个 executor 各干各的，
       新增协议类型要改 4 个地方。统一后加协议只加一个 connector。
```

#### 2.2 AgentCapabilityRegistry（能力注册表）⏱ 1 周

```
新增：src/agentmind/services/capability_registry.py

做什么：
- 不只记录 Agent 名字和类型
- 还记录：能力列表、成本估算、风险等级、平均延迟、可用性
- 路由决策时能根据"谁能做 + 谁便宜 + 谁快 + 谁安全"综合打分
- 支持动态更新（Agent 上报能力、健康检查更新可用性）

为什么做：智能编排的前提是知道每个 Agent 能干什么。
       现在的 registry 只知道名字，路由决策信息不够。
```

#### 2.3 RoutingStrategyManager（路由策略管理器）⏱ 1 周

```
新增：src/agentmind/services/strategy_manager.py

做什么：
- 策略注册表：启动时扫描 + 运行时热加载
- 策略元数据（优先级、置信度、适用场景）外化到配置
- 面板能开关策略、调整顺序
- 策略执行统计（命中率、平均置信度）供自进化使用

为什么做：热插拔是目标能力。现在改策略要改代码重启，
       以后面板拖拽即可。
```

#### 2.4 OrchestrationEngine（编排引擎升级）⏱ 1-2 周

```
改什么：
- 现有 DAG 执行只有顺序，加并行执行
- 加失败补偿（重试/跳过/回滚）
- 加上下文传递（前一步的输出自动注入下一步的输入）
- 编排执行的两套路径合并（router.py + orchestration.py → 统一走引擎）

为什么做：路由智能编排是你的目标能力。
       现在的 DAG 只有最基础的顺序执行，复杂编排撑不住。
```

#### 2.5 AuditLogService（审计日志）⏱ 1 周

```
新增：src/agentmind/services/audit_service.py

做什么：
- 记录：谁在什么时候让哪个 Agent 做了什么，结果是什么
- 覆盖：路由决策、记忆读写、配置变更、Agent 调用
- 查询接口：按 trace_id / 用户 / Agent / 时间范围
- 面板展示

为什么做：CPE + AgentShield + 双池记忆都需要审计。
       没有审计，安全策略就是空谈。
```

#### 2.6 控制面板升级 ⏱ 1 周

```
改什么：
- 面板 API 不再直接读写 YAML / SQL
- 全部改为调用 ConfigService / TaskService / AuditLogService
- 加：路由策略管理页、Agent 能力查看页、审计日志页
- 面板变成真正的"控制平面"，不是"直接操作数据库的客户端"

为什么做：面板直接碰底层是架构漏洞，未来权限/审计/稳定性都会出问题。
```

#### 第二阶段结束时的架构变化

```
新增 6 个核心服务：
  ProtocolGateway      → 统一协议调用
  CapabilityRegistry   → Agent 能力画像
  StrategyManager      → 路由策略可插拔
  OrchestrationEngine  → DAG 并行/补偿/上下文
  AuditLogService      → 全链路审计
  ControlPanel 2.0     → 真正的控制平面

依赖关系：
  ConfigService ──→ StrategyManager / AuditLogService / ControlPanel
  TaskService ──→ AuditLogService / OrchestrationEngine
  ProtocolGateway ──→ CapabilityRegistry ──→ StrategyManager

这些服务层是第三阶段"自进化"的地基。
没有它们，进化引擎没有数据源、没有决策点、没有评估依据。
```

---

### 第三阶段：智能化（6-8 周）

> 目标：从"能管理"到"能自我优化"
> 前提：第二阶段的 TaskService + AuditLogService + StrategyManager 已就绪

#### 3.1 EvolutionEngine 框架 ⏱ 2 周

```
新增：src/agentmind/evolution/

框架设计：
  evolver_base.py      # Evolver 基类：observe → analyze → decide → apply → rollback
  evolution_engine.py  # 管理所有 evolver 的生命周期
  metrics_collector.py # 采集成功率/延迟/命中率/用户反馈

为什么先搭框架：5 个 evolver 共用采集→分析→决策→下发→回滚的管道，
             框架搭好后加新 evolver 只需实现 analyze + decide。
```

#### 3.2 路由进化 ⏱ 1-2 周

```
新增：src/agentmind/evolution/route_evolver.py

做什么：
- 采集：每个路由决策的成功率、延迟、用户满意度
- 分析：哪些 Agent 在哪些场景表现好/差
- 决策：调整策略权重/优先级/置信度阈值
- 下发：更新 StrategyManager 的配置
- 回滚：如果新权重导致成功率下降，自动退回

为什么先做路由进化：
  1. 数据最充分（每个请求都有路由决策记录）
  2. 效果最可见（成功率/延迟可以直接量化）
  3. 风险最可控（回滚容易，不影响记忆/安全）
```

#### 3.3 记忆进化 ⏱ 1 周

```
新增：src/agentmind/evolution/memory_evolver.py

做什么：
- 采集：记忆召回命中率、相关度评分、用户是否采纳记忆内容
- 分析：哪些记忆类型/评分权重效果最好
- 决策：调整重要性评分权重、衰减速率、容量上限
- 下发：更新 MemoryService 的配置
```

#### 3.4 本能进化 ⏱ 1 周

```
新增：src/agentmind/evolution/instinct_evolver.py

做什么：
- 识别高频成功的路由路径（用户 X 总是让 Agent Y 做 Z）
- 沉淀为"本能"：直接匹配走快速通道，跳过策略链
- 类似人类"肌肉记忆"：不需要思考的熟练操作
```

#### 3.5 Prompt 进化 ⏱ 1 周

```
新增：src/agentmind/evolution/prompt_evolver.py

做什么：
- 采集：Agent 执行的 Prompt 和结果质量
- 分析：哪些 Prompt 模板效果好
- 优化：自动调整 Prompt 模板（比如加/减上下文、改措辞）
```

#### 3.6 DAG 进化 ⏱ 1 周

```
新增：src/agentmind/evolution/dag_evolver.py

做什么：
- 采集：DAG 编排的成功率和耗时
- 分析：哪些步骤可以并行、哪些可以跳过
- 优化：自动简化/重组 DAG
```

#### 第三阶段结束时的架构变化

```
新增 evolution/ 包，5 个闭环 evolver：

  数据流：
  TaskService + AuditLogService
        │
        ▼
  MetricsCollector（采集）
        │
        ▼
  Evolver.analyze()（分析）→ Evolver.decide()（决策）
        │
        ▼
  StrategyManager / ConfigService（下发）
        │
        ▼
  回滚机制（如果变差则退回）

这是 AgentMind 区别于普通调度器的核心差异化能力。
```

---

### 第四阶段：安全与通道（3-4 周）

> 目标：加安全护栏 + 多通道接入
> 前提：第二阶段的 AuditLogService + ProtocolGateway 已就绪

#### 4.1 PolicyEngine + AgentShield ⏱ 2 周

```
新增：src/agentmind/governance/

做什么：
- PolicyEngine：上下文隔离，防止跨 Agent 信息泄漏
- AgentShield：
  ├── 权限控制（哪个 Agent 能做什么）
  ├── 危险操作拦截（rm -rf、DROP TABLE 等）
  ├── 频次限制（防 Agent 循环调用）
  └── 风险分级（低/中/高风险操作不同审批流程）
- 所有安全事件写入 AuditLogService

为什么第四阶段才做：安全策略需要审计日志做基础，
                  没有审计就没有依据判断"谁越权了"。
```

#### 4.2 双池记忆策略 ⏱ 1 周

```
改什么：
- MemoryService 加双层：公共池（跨 Agent 共享）+ 私有池（Agent/用户隔离）
- 检索时根据上下文决定查哪个池
- 写入时根据内容敏感度决定放哪个池
- 跨池访问走 PolicyEngine 审批

为什么现在做：双池需要 PolicyEngine 做隔离控制，
           前面没做安全层，双池就是空谈。
```

#### 4.3 ChannelHub（多通道中心）⏱ 1 周

```
新增：src/agentmind/channels/
├── hub.py              # 统一入口：消息归一化
├── base.py             # ChannelAdapter 基类（已有，增强）
├── feishu.py           # 飞书（已有，迁入）
├── api_channel.py      # HTTP API（新增）
├── webhook.py          # 通用 Webhook（新增）
└── (future) slack.py / dingtalk.py / telegram.py

做什么：
- 不同通道的消息 → 统一 Message 模型
- 统一的认证/限流/错误处理
- 新增通道 = 写一个适配器，不动核心逻辑

为什么现在做：多通道依赖路由拆分和协议网关，
           前面的拆分没做完，加通道只会再挤到 router.py 里。
```

---

### 第五阶段：生态（2-3 周）

> 目标：模板市场 + 完善可观测性
> 前提：前面四阶段已完成

#### 5.1 TemplateMarket（模板市场）⏱ 1-2 周

```
新增：src/agentmind/marketplace/

做什么：
- 模板类型：路由规则模板、DAG 编排模板、Agent 配置模板、Prompt 模板
- 本地模板库（YAML/JSON）
- 一键导入/导出/分享
- 可选远程同步

为什么最后做：模板市场需要前面所有服务稳定后才有内容可卖。
```

#### 5.2 完善可观测性 ⏱ 1 周

```
新增/增强：src/agentmind/observability/
├── metrics.py     # Prometheus 兼容指标导出
├── tracing.py     # 全链路 trace（trace_id 已有，补完整）
├── health.py      # 系统健康（DB/嵌入/Worker/飞书/各通道）
└── dashboard.py   # 面板可视化（请求量/成功率/记忆命中率/进化效果）

为什么最后做：可观测性需要所有模块都有指标输出才有意义。
```

---

## 四、总览：阶段依赖关系

```
Phase 1：修地基 ────────────────────────────── 6-8 周
  │  ConfigService / MemoryService 收口 / 入口拆分
  │  异常可观测 / TaskService / Session 持久化
  │
  ▼
Phase 2：平台化 ────────────────────────────── 4-6 周
  │  ProtocolGateway / CapabilityRegistry
  │  StrategyManager / OrchestrationEngine
  │  AuditLogService / ControlPanel 2.0
  │
  ▼
Phase 3：智能化 ────────────────────────────── 6-8 周
  │  EvolutionEngine 框架 + 5 类 Evolver
  │  路由进化 → 记忆进化 → 本能 → Prompt → DAG
  │
  ▼
Phase 4：安全与通道 ────────────────────────── 3-4 周
  │  PolicyEngine + AgentShield + 双池记忆
  │  ChannelHub + 多通道适配器
  │
  ▼
Phase 5：生态 ──────────────────────────────── 2-3 周
     TemplateMarket + 可观测性完善

总工期：22-29 周（5-7 个月）
```

---

## 五、关键决策点

在执行过程中有几个需要做的决策，提前列出来：

| 决策点 | 时间 | 选项 | 建议 |
|---|---|---|---|
| v4 记忆是否稳定 | Phase 1.2 | 稳定→砍老代码 / 不稳定→关 v4 先修 | 先跑 v4 测试套件评估 |
| CPE 的定义 | Phase 4.1 | 上下文策略引擎 / 认知执行引擎 | 建议"上下文策略引擎"——控制什么信息能流向哪个 Agent |
| 自进化是否自动生效 | Phase 3.2 | 自动 / 半自动（人审批）| 先半自动，观察效果后再放开 |
| 多通道优先级 | Phase 4.3 | Webhook 优先 / Slack 优先 | Webhook 优先——最通用，其他通道可基于它封装 |

---

## 六、三件"现在不要做"的事

1. **不要现在加新 Agent 协议** —— 等 Phase 2 ProtocolGateway 做完再说
2. **不要现在做多进程/分布式** —— Session 持久化没做完，做了等于推倒重来
3. **不要现在做自进化** —— TaskService + AuditLogService + StrategyManager 是自进化的三个前提，缺一不可

---

## 七、一句话总结

> 地基不牢，楼越高越危险。Phase 1 修地基、Phase 2 建骨架、Phase 3 长大脑、Phase 4 穿铠甲、Phase 5 开商店。每阶段结束都能正常跑，不会改到一半挂掉。
