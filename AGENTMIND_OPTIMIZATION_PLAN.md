# AgentMind 完整优化建议方案

> 版本：v1.0
> 日期：2026-05-26
> 输入依据：
> - `AGENTMIND_PLATFORM_PLAN.md`
> - `AGENTMIND_MEMORY_RETRIEVAL_PLAN.md`
> - 当前代码结构审查结论

---

## 一句话结论

AgentMind 现在不是“功能不够”，而是已经进入了“需要收口架构”的阶段。

当前系统能跑，也已经有路由、编排、飞书、记忆、面板、Agent 执行等核心能力。但这些能力很多都挤在少数几个大文件里，模块之间互相直接调用、直接读写配置和数据库。继续这样加功能，会越来越像一团线。

优化目标不是推倒重写，而是：

```text
让入口只负责接收请求，
让服务层负责办事，
让底层只负责存储、协议和执行。
```

---

## 当前主要问题

### 1. 三个“总管”太重

现在项目里有三个地方在承担过多职责：

```text
main.py
  负责启动，也负责鉴权、飞书启动、后台任务、清理任务、页面挂载

api/router.py
  负责 HTTP 路由，也负责普通请求、流式请求、编排、讨论、Attach、任务记录

panel/server.py
  负责面板接口，也直接读写配置、修改 Agent 注册表、控制飞书连接、删除记忆
```

这三个文件都在“顺手管别人的事”。短期方便，长期会让任何改动都变危险。

### 2. 配置没有统一入口

`settings.yaml`、`agents.yaml`、`routes.yaml` 被多个模块直接读取和写入。

结果是：

- 不知道谁最后改了配置
- 修改配置时缺少统一校验
- 热加载逻辑分散
- 未来加权限和审计会很难

### 3. 记忆系统新旧双轨并存

现在有旧的 `storage/memory.py`，也有新的 `memory/service.py`、`memory/sqlite_store.py` 和 v4 pipeline。

很多地方会先判断开关，再决定走旧实现还是新实现。

这会带来几个问题：

- 写进去的东西不一定从同一路径搜出来
- 一处 bug 可能要在两套逻辑里修
- 新记忆架构很难真正成为唯一入口

### 4. trace、memory、task 边界不清

现在路由 trace 会写进记忆库。任务历史、路由追踪、用户记忆有混在一起的趋势。

这三类数据应该分开：

```text
用户记忆：用户说过什么、Agent 做过什么、历史事实是什么
任务历史：某次任务何时开始、何时结束、成功还是失败
路由追踪：为什么这次请求路由到这个 Agent
```

混在一起会污染检索，也会影响后续审计和排错。

### 5. 进程内状态太多

Working Memory、讨论状态、Attach 绑定、流监听等，有不少存在内存里。

这意味着：

- 服务重启后状态丢失
- 多通道连续对话不稳定
- 后续如果支持多进程，会遇到更大问题

### 6. 异常经常被吞

项目里很多地方采用“失败就跳过”的方式。主流程确实不容易被打断，但代价是出错后很难查。

优化方向不是所有错误都打断用户，而是至少要知道：

```text
哪个用户
哪个任务
哪个模块
什么时候
因为什么失败
有没有影响主流程
```

---

## 目标架构

### 总体结构

```text
用户 / 面板 / 飞书 / API
        |
        v
通道层：只负责接消息、发消息、做通道认证
        |
        v
入口层：只负责把请求变成标准请求
        |
        v
应用服务层：负责真正办事
        |
        |-- RoutingService：路由决策
        |-- OrchestrationService：多 Agent 编排
        |-- TaskService：任务生命周期
        |-- MemoryService：记忆写入、检索、上下文
        |-- ConfigService：配置读写和热加载
        |-- AgentService：Agent 发现、注册、健康检查
        |-- AuditService：审计和追踪
        |
        v
核心规则层：路由策略、记忆流水线、编排规则、安全策略
        |
        v
基础设施层：SQLite / YAML / CLI / HTTP / MCP / A2A / 飞书 SDK
```

### 改造后的核心原则

| 原则 | 含义 |
|---|---|
| 单一入口 | 配置、记忆、任务、trace 都要有统一服务入口 |
| 单一职责 | 一个模块只管一类事情 |
| 服务层收口 | 面板、飞书、API 不直接碰数据库和配置文件 |
| 状态可恢复 | 重要状态从内存迁到 SQLite |
| 错误可追踪 | 不影响主流程的错误也要记录 |
| 本地优先 | 核心能力不能依赖外网，外部服务只能作为增强能力 |
| 每阶段可运行 | 不做大爆炸重写，每阶段结束系统都能跑 |

### 本地优先与离线可用

AgentMind 的基础定位是本地优先的异构 Agent 指挥控制平台。优化过程中必须保护这个前提。

```text
无外网时必须可用：
  本地控制台
  本地配置读写
  本地 Agent 调用
  本地任务记录
  本地记忆写入和检索
  本地路由规则和编排模板

有外网时增强：
  外部 LLM
  外部 embedding
  飞书桥接
  远程 HTTP / A2A Agent
  远程模板同步
```

也就是说，外部 LLM、外部 embedding、飞书、多通道、远程 Agent 都可以提升体验，但不能成为系统启动和核心链路运行的硬依赖。

---

## 重点优化一：服务层收口

这是所有优化的地基。

### 目标

把现在散落在各处的核心能力，收口成几个稳定服务：

```text
ConfigService
TaskService
MemoryService
RoutingService
OrchestrationService
AgentService
AuditService
ChannelService
```

### 改造前

```text
面板接口 -> 直接写 YAML
路由接口 -> 直接调数据库记录任务
飞书通道 -> 直接调用 route_stream
执行器 -> 直接写任务结果和记忆
记忆模块 -> 自己读 settings.yaml
```

### 改造后

```text
面板接口 -> ConfigService / AgentService
路由接口 -> RoutingService / TaskService
飞书通道 -> ChannelService -> RoutingService
执行器 -> TaskService / MemoryService
记忆模块 -> ConfigService
```

### 收益

- 后续新增功能不再到处改
- 配置变更可校验、可审计
- 任务和记忆行为更一致
- 测试更容易写
- 以后做权限、安全、审计有落点

---

## 重点优化二：主请求链路重构

现在主请求链路混在一个大路由文件里。建议拆成清晰流程。

### 目标流程

```text
收到请求
  |
  v
标准化请求
  |
  v
判断系统命令
  |-- /new：交给 SessionService
  |
  v
判断是否命中编排
  |-- 命中：交给 OrchestrationService
  |
  v
判断是否 Attach 接管
  |-- 命中：交给 AttachService
  |
  v
安全扫描
  |
  v
记忆上下文准备
  |
  v
路由决策
  |
  v
执行 Agent
  |
  v
记录任务、trace、记忆
  |
  v
按通道返回结果
```

### 关键拆分

| 当前职责 | 建议归属 |
|---|---|
| `/new` 命令 | SessionService |
| Attach 接管 | AttachService |
| 编排触发与执行 | OrchestrationService |
| 多 Agent 讨论 | DiscussionService |
| 路由决策 | RoutingService |
| SSE / JSON / 飞书文本输出 | ResponseAdapter |
| 任务开始、更新、结束 | TaskService |
| 路由 trace | AuditService 或 TraceService |

### 收益

以后要改“飞书怎么返回”，不影响“路由怎么判断”；要改“编排怎么执行”，不影响“普通请求怎么走”。

---

## 重点优化三：记忆与检索重构

记忆模块是 AgentMind 的长期核心能力，需要优先收口。

### 记忆系统硬原则

```text
上下文只服务当前 session；
历史只服务检索；
原文、卡片、会话状态分层存储；
不要混在一张表里。
```

### 目标结构

```text
MemoryService
    |
    |-- Session Context：当前 session 上下文
    |-- Core Memory：长期稳定事实
    |-- Raw Memory：完整原文
    |-- Memory Cards：检索卡片
    |-- Result Sets：检索结果集导航
    |-- Archive：冷库原文回查
```

### 三层存储

```text
raw_memory
  存完整原文
  用户、AgentMind、被调用 Agent、工具结果都入库
  只搬迁，不删除

memory_cards
  存检索用小卡片
  包含主题、摘要、实体、标签、向量
  检索只搜卡片，不搜大段原文

sessions / working_memory / core_memory
  存当前会话摘要、最近几轮、长期事实
  用于自动上下文注入
```

### `/new` 的意义

`/new` 是 session 分界线。

```text
/new 之前：
  属于当前 session
  上下文持续注入

/new 之后：
  旧 session 关闭
  旧内容进入历史记忆
  新 session 干净开始
```

### 检索分三类

| 类型 | 用户意图 | 返回方式 |
|---|---|---|
| 精准搜索 | “之前那个 bug 修了吗？” | 找最相关 1 条，必要时回查原文 |
| 背景注入 | 当前任务需要历史背景 | 注入 3-5 条相关卡片 |
| 浏览查询 | “最近聊了什么？” | 返回 5-10 条摘要 |

### 必须先做评测集

记忆检索不能靠感觉优化。建议先建立固定评测集：

```text
至少 50 组问题
覆盖：日期、主题、用户、Agent 来源、展开原文、当前 session、历史 session
每次改检索后跑评测
看命中率、误召回、响应时间、上下文长度
```

### 冲突检测

MemoryService 必须支持记忆冲突检测，不能简单用新内容覆盖旧内容。

需要识别的冲突包括：

```text
同一事实出现多个版本
不同 Agent 给出相反结论
新旧记忆在时间线上冲突
高可信 Agent 与低可信 Agent 结论冲突
用户显式纠正了旧记忆
```

冲突处理原则：

```text
保留所有版本
记录来源 Agent
记录来源任务 trace
记录写入时间
记录可信度
不要静默覆盖
检索时优先返回更可信、更近、更明确的版本
必要时提示“存在冲突记忆”
```

这条能力是 Agent 级共享记忆的底线。多个 Agent 共享记忆时，系统必须知道“谁说了什么、什么时候说的、是否和其他记忆冲突”。

### 迁移策略

不要一次切断旧记忆。

```text
阶段 1：新旧双写
阶段 2：检索优先走 memory_cards
阶段 3：旧 memory_entries 回填到 raw_memory + memory_cards
阶段 4：旧入口变成薄兼容层
阶段 5：确认稳定后废弃旧逻辑
```

---

## 重点优化四：配置中心

### 目标

所有配置统一通过 ConfigService 读取和写入。

```text
ConfigService
  |-- settings
  |-- agents
  |-- routes
  |-- orchestrations
  |-- feature flags
```

### 必须具备的能力

| 能力 | 说明 |
|---|---|
| 统一读取 | 其他模块不再自己打开 YAML |
| 统一写入 | 面板保存配置必须经过 ConfigService |
| 校验 | 防止写入非法结构 |
| 加锁 | 避免两个请求同时写坏配置 |
| 热加载 | 配置变化后通知相关服务 |
| 脱敏 | API key、token、secret 对外展示时自动打码 |
| 审计 | 谁改了什么配置要能查 |

### 收益

配置中心做好后，后续路由策略开关、Agent 配置、记忆参数、飞书配置、安全策略都能统一管理。

---

## 重点优化五：任务、trace、审计分层

### 三类数据分开

```text
TaskService
  管任务生命周期：pending / routing / executing / completed / failed

TraceService
  管路由决策：为什么选这个 Agent，候选有哪些，置信度多少

AuditService
  管审计：谁在什么时候触发了什么操作，是否涉及敏感信息
```

### 推荐数据边界

```text
history.db
  task_history
  attached_conversations

trace.db
  routing_traces
  strategy_runs

memory.db
  raw_memory
  memory_cards
  sessions
  core_memory
  working_memory

audit.db
  audit_events
```

也可以先不拆成多个物理数据库，但逻辑边界要先建立。

### 为什么重要

如果 trace 继续写进 memory，记忆检索会混入系统日志。  
如果任务记录继续散落在执行器和路由里，就很难保证每个任务都有完整生命周期。

---

## 重点优化六：Agent 与协议网关

### 当前状态

Agent 执行层已经支持 CLI、HTTP API、MCP、A2A，但它们还是各自处理执行、健康检查、错误格式和流式返回。

### 目标

建立 ProtocolGateway：

```text
ProtocolGateway
  |-- CLIConnector
  |-- HTTPConnector
  |-- MCPConnector
  |-- A2AConnector
```

对上层暴露统一接口：

```text
invoke
stream
health
capabilities
```

### 同时建立 AgentCapabilityRegistry

记录每个 Agent 的能力画像：

```text
能做什么
适合什么场景
成本多少
延迟多少
安全等级
最近健康状态
历史成功率
```

### 收益

路由不再只靠标签和关键词，而是可以真正根据能力、成本、速度、安全、历史表现综合决策。

---

## 重点优化七：路由策略管理

### 当前问题

路由策略顺序基本写死，配置注入方式也比较隐式。后续要调整策略顺序、开关策略、统计策略效果会很麻烦。

### 目标

建立 StrategyManager：

```text
StrategyManager
  |-- 注册策略
  |-- 控制启停
  |-- 调整优先级
  |-- 记录命中率
  |-- 记录成功率
  |-- 支持后续自进化
```

### 四策略主干

路由管道要保护“四策略主干”，其他能力作为前置中间件或辅助信号存在。

```text
四策略主干：
  1. 显式指定
  2. 规则路由
  3. 语义路由
  4. 能力评分兜底
```

其中：

```text
安全扫描
当前 session / 历史记忆判断
上下文准备
候选 Agent 过滤
```

属于路由前置中间件，不算主策略。这样能避免策略概念膨胀，也方便在控制台里清晰展示“这次到底是哪条主策略做出的选择”。

### 推荐执行链

```text
安全扫描
  |
  v
候选 Agent 过滤
  |
  v
当前 session / 历史记忆判断
  |
  v
显式指定
  |
  v
规则路由
  |
  v
LLM 语义路由
  |
  v
能力评分兜底
```

### 收益

未来可以通过面板看到：

```text
哪个策略命中了
为什么命中
置信度多少
最后执行是否成功
这个策略最近表现好不好
```

这也是后续“路由自进化”的前提。

---

## 重点优化八：编排引擎

### 当前状态

已有 DAG 编排和可视化基础，但执行逻辑还偏简单，并且和主路由有重复路径。

### 目标

建立 OrchestrationService / OrchestrationEngine：

```text
编排计划管理
  |
  v
DAG 校验
  |
  v
依赖分析
  |
  v
可并行步骤并行执行
  |
  v
失败处理：重试 / 跳过 / 停止
  |
  v
步骤结果写入任务和记忆
```

### 后续能力

- 并行执行无依赖节点
- 每个节点独立 trace
- 编排整体 trace
- 上下文传递可配置
- 编排模板可复用
- 执行失败可恢复

---

## 重点优化九：面板控制平面

### 当前问题

面板现在更像“直接操作底层的管理脚本集合”。

它现在承担了太多后台职责：

```text
直接读写配置文件
直接修改 Agent 注册表
直接控制飞书连接
直接查询和删除记忆
直接访问任务和 trace 数据
```

这和服务层收口的目标冲突。后端如果已经拆成 ConfigService、TaskService、MemoryService 等服务，但面板还继续绕过这些服务直接操作底层，架构边界依然会被打穿。

### 目标

面板只作为控制平面，不直接碰底层。

```text
面板
  -> ConfigService
  -> AgentService
  -> TaskService
  -> MemoryService
  -> AuditService
  -> OrchestrationService
```

也就是说，控制面板要从“仪表盘”升级为“控制台”。

```text
现在的面板：
  看状态 + 直接改后台

优化后的面板：
  看状态 + 调用服务 + 展示审计 + 管理策略
```

### 建议面板模块

```text
系统概览
Agent 管理
路由策略管理
记忆检索与审计
任务历史
路由 trace
编排画布
配置中心
通道管理
审计日志
```

### 面板优化内容

#### 1. 配置中心页

统一管理系统配置，但保存动作必须走 ConfigService。

```text
可管理：
  settings 配置
  agents 配置
  routes 配置
  编排模板配置
  通道配置
  feature flags

必须具备：
  修改前校验
  敏感字段脱敏
  保存后热加载
  修改记录写审计
```

#### 2. Agent 管理页

从“列出 Agent”升级为“管理 Agent 能力画像”。

```text
展示：
  Agent 名称
  协议类型
  能力标签
  健康状态
  平均延迟
  估算成本
  安全等级
  历史成功率
  最近错误

操作：
  手动健康检查
  启用 / 禁用
  编辑能力标签
  查看调用历史
```

#### 3. 路由策略页

让用户能看懂系统为什么这样路由。

```text
展示：
  策略顺序
  策略启停状态
  策略命中次数
  命中后成功率
  平均置信度
  最近命中样例

操作：
  开启 / 关闭策略
  调整优先级
  调整部分阈值
  查看某次请求的路由链路
```

#### 4. 记忆管理页

记忆页要跟新的记忆分层一致，不能继续把所有内容混在一起展示。

```text
分区展示：
  当前 session 上下文
  Working Memory
  Core Memory
  历史原文 raw_memory
  检索卡片 memory_cards
  冷库 archive
  检索结果集 result_sets

能力：
  按用户查
  按时间查
  按主题查
  按 Agent 来源查
  从卡片展开原文
  查看某条记忆来自哪次任务
```

#### 5. 任务与 trace 页

把“任务执行结果”和“为什么这么路由”分开展示。

```text
任务页：
  请求内容
  当前状态
  目标 Agent
  执行耗时
  输出摘要
  错误原因
  是否可重试

trace 页：
  候选 Agent
  命中的路由策略
  每个策略的判断结果
  最终选择原因
  fallback 链路
  是否触发安全策略
```

#### 6. 编排管理页

编排页不只是画 DAG，还要能管理 DAG 的执行结果。

```text
展示：
  编排模板列表
  DAG 节点状态
  每个节点的输入输出
  每个节点调用的 Agent
  编排整体耗时
  失败节点和失败原因

操作：
  新建模板
  编辑模板
  运行模板
  查看历史执行
  从失败节点重试
```

#### 7. 通道管理页

通道页负责管理外部入口，不负责业务规则。

```text
展示：
  飞书连接状态
  API 通道状态
  Webhook 状态
  最近消息
  最近错误

操作：
  配置通道
  测试连接
  启用 / 禁用通道
  查看通道日志
```

#### 8. 审计日志页

所有关键操作都应该能查到。

```text
记录：
  谁修改了配置
  谁启停了 Agent
  谁删除或修改了记忆
  谁触发了高风险操作
  哪次请求涉及敏感信息
  哪次外部通道调用失败
```

### 面板与后端服务关系

```text
控制面板
  |
  |-- 配置中心页      -> ConfigService
  |-- Agent 管理页    -> AgentService / CapabilityRegistry
  |-- 路由策略页      -> StrategyManager / RoutingService
  |-- 记忆管理页      -> MemoryService
  |-- 任务与 trace 页 -> TaskService / TraceService
  |-- 编排管理页      -> OrchestrationService
  |-- 通道管理页      -> ChannelService / ChannelHub
  |-- 审计日志页      -> AuditService
```

面板本身不保存业务规则，也不直接改底层文件。它只是把用户操作转交给对应服务，并展示服务返回的结果。

### 收益

以后做权限控制时，可以限制“谁能改配置、谁能删记忆、谁能连飞书”，而不是面板接口天然拥有所有底层权限。

同时，用户能在面板里看懂三件关键事情：

```text
系统现在是什么状态
系统为什么这么判断
出了问题应该从哪里查
```

---

## 重点优化十：通道层

### 当前状态

飞书通道已经可用，但它知道太多业务细节，比如讨论停止词、route_stream、消息处理流程。

### 目标

建立 ChannelHub：

```text
FeishuAdapter
APIChannel
WebhookChannel
未来的 Slack / DingTalk / Telegram
        |
        v
ChannelHub
        |
        v
标准 Message
        |
        v
RoutingService
```

通道只负责：

- 收消息
- 发消息
- 通道认证
- 通道格式转换
- 通道限流

通道不负责：

- 路由策略
- 编排执行
- 记忆检索
- 多 Agent 讨论规则

---

## 重点优化十一：安全治理

### 当前状态

已有基础敏感词扫描，会检测 API key、password 等内容，然后优先路由到本地 Agent。

### 目标

逐步升级为 CPE + AgentShield。

```text
CPE（Context Policy Engine，上下文策略引擎）
  判断什么上下文、记忆、敏感信息可以流向哪个 Agent

AgentShield
  判断哪个 Agent 能做什么操作
```

二者分工：

```text
CPE：控制信息流
  哪些记忆可以给这个 Agent
  哪些上下文可以带入 Prompt
  哪些敏感内容必须留在本地
  哪些内容需要用户确认后才能发给远程 Agent

AgentShield：控制行为权限
  哪个 Agent 能调用哪些工具
  哪些命令属于高风险
  哪些外部 API 可以访问
  触发危险操作时是否需要审批

AuditService：记录判断和操作
  CPE 做了什么判断
  AgentShield 拦截了什么行为
  谁批准了高风险操作
  哪次请求访问了哪类记忆
```

### 需要覆盖

| 场景 | 策略 |
|---|---|
| 敏感信息 | 只允许本地 Agent 或用户确认 |
| 高风险命令 | 拦截或要求审批 |
| 跨 Agent 记忆访问 | 按权限和用户隔离 |
| 双池记忆访问 | 公共池默认可检索，私有池必须经过 CPE 判断 |
| 配置修改 | 写审计日志 |
| 外部 API 调用 | 记录目标和结果 |

### 注意

安全治理不建议第一阶段就做重。它依赖 TaskService、AuditService、ConfigService 先稳定。

---

## 重点优化十二：后台任务统一管理

现在后台任务包括：

- Agent 健康检查
- 记忆清理
- stream 清理
- workspace 清理
- memory workers

建议建立 BackgroundTaskManager：

```text
BackgroundTaskManager
  |-- 注册任务
  |-- 启动任务
  |-- 停止任务
  |-- 记录最近执行时间
  |-- 记录最近失败原因
  |-- 面板可查看状态
```

这样后台任务失败不会悄悄消失。

---

## 分阶段执行路线

### Phase 0：准备与基线

目标：先知道现在系统表现如何，避免重构后不知道好坏。

建议工作：

```text
1. 建立基础测试命令清单
2. 建立记忆检索评测集
3. 记录当前核心链路表现
4. 标记所有直接读写配置的位置
5. 标记所有直接写数据库的位置
```

交付物：

- 测试基线
- 记忆检索评测集
- 架构依赖清单
- 重构风险清单

### Phase 1：修地基

目标：先把最容易失控的边界收住。

建议顺序：

```text
1. ConfigService：统一配置读写
2. TaskService：统一任务生命周期
3. main.py 瘦身：启动逻辑模块化
4. api/router.py 拆分：主请求链路服务化
5. MemoryService 收口：旧记忆入口变薄
6. Session 状态持久化
7. 异常可观测化
```

阶段结束状态：

```text
入口变薄
配置统一
任务统一
记忆入口统一
关键状态可恢复
错误可追踪
```

### Phase 2：记忆与检索升级

目标：把 AgentMind 的长期记忆能力做扎实。

建议顺序：

```text
1. 建 raw_memory / memory_cards / sessions 分层结构
2. 写入路径双写
3. 检索路径切到 memory_cards
4. 明确当前 session 上下文与历史检索边界
5. 加 result_sets，支持“展开第 N 条”“还有吗”
6. 加冷库回查能力
7. 用评测集持续回归
```

阶段结束状态：

```text
原文不丢
检索搜卡片
当前上下文不膨胀
历史按需召回
检索效果可衡量
```

### Phase 3：平台化能力

目标：从“能跑”升级到“能管理”。

建议顺序：

```text
1. ProtocolGateway：统一 CLI / HTTP / MCP / A2A
2. AgentCapabilityRegistry：建立 Agent 能力画像
3. StrategyManager：路由策略可管理
4. OrchestrationEngine：编排执行统一
5. AuditService：审计日志
6. 面板升级为控制平面：不再直接操作底层，统一调用服务
```

阶段结束状态：

```text
Agent 能力可见
协议调用统一
路由策略可管理
编排可追踪
配置和操作可审计
面板能解释系统状态、路由原因、任务失败原因
```

### Phase 4：安全与多通道

目标：让平台具备可控扩展能力。

建议顺序：

```text
1. CPE：信息流控制
2. AgentShield：危险操作拦截
3. 双池记忆：公共池 + 私有池
4. ChannelHub：统一多通道接入
5. Webhook 通道优先
```

阶段结束状态：

```text
敏感信息不乱流
危险操作有拦截
多通道不挤进 router
记忆权限更清晰
```

### Phase 5：智能化与生态

目标：在稳定平台上做自优化，而不是在混乱结构上加智能。

建议顺序：

```text
1. EvolutionEngine 框架
2. 路由进化：调整策略权重
3. 记忆进化：调整召回和重要性权重
4. 本能进化：沉淀高频成功路径为快速规则
5. Prompt 进化：优化提示词模板
6. DAG 进化：优化编排路径
7. TemplateMarket：模板导入导出
8. 可观测性完善
```

阶段结束状态：

```text
系统能基于历史表现优化路由、记忆和编排
模板可复用
指标可观察
问题可定位
```

自进化闭环必须包含五类 evolver：

```text
路由进化：
  根据成功率、延迟、用户反馈调整路由权重

记忆进化：
  根据命中率、采纳率、冲突率调整记忆召回和重要性权重

本能进化：
  把高频、稳定、成功率高的路径沉淀为快速规则
  例如“某用户的代码修复任务总是优先走本地 Codex”

Prompt 进化：
  根据执行结果优化提示词模板和上下文组织方式

DAG 进化：
  根据编排执行历史优化步骤顺序、并行度和失败处理策略
```

---

## 建议优先级总表

| 优先级 | 优化项 | 为什么排这里 |
|---|---|---|
| P0 | ConfigService | 其他所有服务都依赖配置统一 |
| P0 | TaskService | 任务生命周期是可观测和自进化地基 |
| P0 | 主请求链路拆分 | 当前最大复杂度集中点 |
| P0 | MemoryService 收口 | 新旧双轨会阻碍所有记忆优化 |
| P0 | 记忆评测集 | 没有评测就无法判断检索优化好坏 |
| P0 | 本地优先保护 | 防止核心能力依赖外网 |
| P1 | main.py 瘦身 | 降低启动和生命周期风险 |
| P1 | Session 持久化 | 支撑多通道和连续上下文 |
| P1 | trace 与 memory 分离 | 避免记忆库污染 |
| P1 | 面板服务化 | 防止面板继续绕过架构 |
| P1 | 异常可观测化 | 排错和审计基础 |
| P2 | ProtocolGateway | 支撑更多 Agent 协议 |
| P2 | StrategyManager | 支撑策略管理和路由进化 |
| P2 | OrchestrationEngine | 支撑复杂 DAG |
| P2 | AgentCapabilityRegistry | 路由需要能力画像 |
| P3 | CPE / AgentShield | 安全治理依赖前面审计和任务地基 |
| P3 | ChannelHub | 多通道扩展 |
| P4 | EvolutionEngine | 最后做，避免在不稳结构上加智能 |
| P4 | TemplateMarket | 生态层，等核心稳定后再做 |

---

## 不建议现在做的事

### 1. 不建议现在继续加新 Agent 协议

先做 ProtocolGateway。否则每加一个协议，都会把现在的执行层复杂度再放大一倍。

### 2. 不建议现在直接做自进化

自进化需要数据基础：

```text
任务是否成功
为什么这么路由
Agent 表现如何
用户是否满意
记忆是否命中
```

这些数据现在还没有统一收口。

### 3. 不建议马上做分布式

当前 session、讨论、attach 等状态还没有完全持久化。先做状态外置，再谈多进程或分布式。

### 4. 不建议在旧记忆表上继续堆字段

记忆方案的核心是原文、卡片、session 分层。如果继续在 `memory_entries` 上加字段，会把问题拖得更久。

---

## 成功标准

### 架构层面

```text
main.py 只负责组装应用
api/router 不再是所有请求逻辑的中心
面板不直接读写 YAML 和 SQLite
面板所有操作都通过 ConfigService / TaskService / MemoryService 等服务
配置统一走 ConfigService
任务统一走 TaskService
记忆统一走 MemoryService
trace 不再写进用户记忆
重要状态重启后可恢复
无外网时本地控制台、本地路由、本地记忆、本地 Agent 仍可用
```

### 记忆层面

```text
当前 session 自动上下文注入
历史记忆按需检索
原文完整保存不丢
检索只搜 memory_cards
支持按用户、时间、主题、Agent 来源检索
支持“展开第 N 条”“还有吗”
支持记忆冲突检测，不静默覆盖冲突事实
检索评测集持续可跑
```

### 平台层面

```text
Agent 能力画像可查看
路由策略命中和成功率可查看
四策略主干清晰可见，并支持热插拔管理
编排执行过程可追踪
后台任务状态可查看
配置修改可审计
面板可以查看任务详情、路由 trace、记忆来源和通道状态
通道接入不影响核心路由
CPE、AgentShield、双池记忆、审计日志形成安全闭环
```

---

## 最推荐的第一步

如果只能从一个地方开始，我建议从 **ConfigService + TaskService** 开始。

原因很简单：

```text
ConfigService 解决“谁都在读写配置”的问题。
TaskService 解决“任务状态到处散落”的问题。
```

这两个服务建好后，再拆路由、面板、记忆都会更稳。

推荐第一批交付：

```text
1. ConfigService 接管 settings.yaml / agents.yaml / routes.yaml
2. TaskService 接管 record_task_start / update / end
3. main.py 只做应用装配
4. api/router.py 的普通请求流程抽到 RoutingService
5. 建立记忆检索评测集
```

第一批做完，项目内部会从“很多模块互相伸手”，变成“核心服务统一办事”。这就是后续所有优化的基础。

---

## 最终路线图

```text
Phase 0：准备与基线
  建测试基线、记忆评测集、依赖清单

Phase 1：修地基
  ConfigService、TaskService、入口拆分、MemoryService 收口、Session 持久化

Phase 2：记忆升级
  raw_memory、memory_cards、sessions、result_sets、冷库回查、评测回归

Phase 3：平台化
  ProtocolGateway、Agent 能力画像、StrategyManager、OrchestrationEngine、AuditService、控制面板升级

Phase 4：安全与通道
  CPE、AgentShield、双池记忆、ChannelHub

Phase 5：智能化与生态
  EvolutionEngine、路由进化、记忆进化、本能进化、Prompt/DAG 进化、模板市场、可观测性完善
```

---

## 结束语

AgentMind 的方向是对的：它不是再造一个 Agent，而是做 Agent 的指挥中心。

但指挥中心最怕“所有线都接到同一个插排上”。现在的优化重点，就是把线理清楚：

```text
入口归入口，
服务归服务，
记忆归记忆，
任务归任务，
通道归通道，
底层归底层。
```

把这些边界先立起来，后面再做多 Agent 编排、自进化、多通道、安全治理，才不会越做越重。
