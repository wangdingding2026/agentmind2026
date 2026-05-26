# AgentMind 记忆与检索模块优化方案

> 核心目标：全量保存不丢失 + 快速精准检索 + 会话不膨胀
> 原则：不推倒重写，在现有基础上分层、收口、提精度

---

## 0. 硬原则（先于一切设计）

**这是整个记忆系统不可妥协的边界。后面所有设计都必须服从这条原则。**

```
┌────────────────────────────────────────────────────────┐
│                                                        │
│   上下文只服务当前 session，历史只服务检索；             │
│   原文、卡片、摘要分层存，不要混在一张表里。              │
│                                                        │
└────────────────────────────────────────────────────────┘
```

由此推导出 5 条硬规则：

| # | 硬规则 | 违反会怎样 |
|---|---|---|
| 1 | 当前 session 上下文 = 自动注入；历史 = 按需检索 | prompt 膨胀，token 爆炸 |
| 2 | 原文库和检索卡片库**必须是两张表**，不能混 | 检索慢、改一个维度影响全局 |
| 3 | 检索分"要答案"和"要背景"两类，**不混成统一 top-k** | 用数量弥补精度，结果都不准 |
| 4 | 冷库不是死档案，必须能按 card_id / raw_id 回查原文 | 全量保存 = 存了但用不上 |
| 5 | 检索评测集**先于优化**建立 | 优化没有标准，凭感觉调参 |

---

## 1. 现在的问题：一个表干了三件事

```
现在的 memory_entries 表：

  ┌───────────────────────────────────────────┐
  │  原始对话内容（大段文字）                    │  ← 存全量的地方
  │  摘要 / 标签 / 实体                         │  ← 检索用的索引
  │  向量嵌入                                   │  ← 语义搜索的依据
  │  重要性 / 访问次数 / 版本                    │  ← 排序的权重
  └───────────────────────────────────────────┘

  问题：
  1. 超量时 LRU 删除 → 记忆丢失，违反"全量保存"
  2. 检索时在大段原文里搜 → 慢且不精准
  3. 归档后不可检索 → 老记忆"还在硬盘但找不到"
  4. 一个表又存又搜又排 → 改一个维度影响全局
```

---

## 2. 目标架构：3 层存储 + 4 类内容

### 2.1 存储分层（3 张表，物理分离）

按"存什么 + 给谁用"来分，不按"功能"来分：

```
┌─────────────────────────────────────────────────────────┐
│  存储层 1：raw_memory（原文层）                            │
│  存什么：完整原文，所有参与者说的所有话                      │
│  给谁用：用户要看"当时到底说了什么"时回查                    │
│  特点：只写不删（超量搬冷库），按 raw_id 精确回查             │
├─────────────────────────────────────────────────────────┤
│  存储层 2：memory_cards（检索卡片层）← 注意：是新表，不是改造│
│  存什么：从原文生成的小卡片（主题+摘要+实体+标签+向量）       │
│  给谁用：检索引擎在这层搜，找到后按 raw_ids 回查原文          │
│  特点：永不删除，体积小（每条几百字节），索引密集             │
├─────────────────────────────────────────────────────────┤
│  存储层 3：sessions（会话状态层）                          │
│  存什么：会话摘要 + Working Memory + Core Memory             │
│  给谁用：当前 session 上下文注入 + 长期事实                  │
│  特点：滚动更新，结束时归档                                 │
└─────────────────────────────────────────────────────────┘

为什么要 3 张表物理分离？
  - 原文层大但读得少 → 可以压缩、可以搬冷库
  - 卡片层小但读得多 → 全部驻留热库，索引完整
  - 会话状态层频繁更新 → 单独管理，不影响其他层

之前的方案是"改造 memory_entries"，现在改为"新建 memory_cards"，
原 memory_entries 在迁移期保留，迁移完成后废弃。
```

### 2.2 4 类内容全部入库

每张表里都按 4 类内容标记来源：

| 内容来源 | role | agent_id | 例子 |
|---|---|---|---|
| 用户输入 | `user` | - | "项目X 部署失败" |
| AgentMind 自己的回复 | `assistant` | - | "我看看，让 Claude 查一下" |
| 被调用 Agent 的回复 | `agent` | claude/codex/aider | Claude 说"配置错误" |
| 工具调用结果 | `tool` | bash/api/file | 部署日志输出 |

**全部记忆 + 全部可检索 + 可按"谁说的"过滤。**

### 2.3 上下文注入预算（每轮 prompt 构成）

```
当前 session 上下文（自动注入，不经过检索）：
  Core Memory：           1-2KB   ← 长期事实
  当前会话摘要：           1-2KB   ← 防膨胀的关键
  最近 3-5 轮原文：        2KB     ← 含所有角色（用户/AM/被调Agent/工具）
  ──────────────────────
  小计：                  4-6KB

历史检索结果（按需注入，仅在触发时）：
  类型 A 精准搜索：        1KB    ← 1 条答案
  类型 B 上下文背景：      4KB    ← 3-5 条卡片
  类型 C 浏览类查询：      8KB    ← 5-10 条摘要
  ──────────────────────
  按场景取一种，最大 8KB

每轮 prompt 总量：4-14KB（远小于模型上下文窗口，留足空间给当前问题）
```

### 2.4 三层架构如何解决三大目标

| 目标 | 怎么解决 |
|---|---|
| 全量保存不丢失 | raw_memory 层只搬不删；冷库可按 raw_id 回查（硬规则 4） |
| 快速精准检索 | memory_cards 层小且索引密；检索只搜卡片，不搜原文 |
| 会话不膨胀 | sessions 层滚动摘要替代完整历史；prompt 预算严格控制 |

---

## 3. 数据模型变化

### 3.1 Raw Memory 表（新增）

```sql
CREATE TABLE raw_memory (
    raw_id         TEXT PRIMARY KEY,        -- raw-{uuid}
    user_id        TEXT NOT NULL,
    session_id     TEXT NOT NULL,           -- 关联 session
    conversation_id TEXT NOT NULL,          -- 关联 conversation
    role           TEXT NOT NULL,           -- user / assistant / agent / tool
    content        TEXT NOT NULL,           -- 完整原文，不截断
    trace_id       TEXT DEFAULT '',         -- 关联任务 trace
    agent_id       TEXT DEFAULT '',         -- 来源 Agent（role=agent/tool 时有值）
    intent_tag     TEXT DEFAULT 'general',  -- 意图标签：coding/recall/casual/orchestration
    created_at     TEXT NOT NULL,
    storage_tier   TEXT DEFAULT 'hot'       -- hot / warm / cold
);
CREATE INDEX idx_raw_session ON raw_memory(session_id);
CREATE INDEX idx_raw_conversation ON raw_memory(conversation_id);
CREATE INDEX idx_raw_user_time ON raw_memory(user_id, created_at DESC);
CREATE INDEX idx_raw_tier ON raw_memory(storage_tier, created_at);
CREATE INDEX idx_raw_role ON raw_memory(role, agent_id);  -- 按"谁说的"检索
```

### 3.2 memory_cards 表（新建，不再改造 memory_entries）

```sql
-- 新建独立表，不在 memory_entries 上加字段
-- memory_entries 在迁移期保留，迁移完成后废弃
CREATE TABLE memory_cards (
    card_id        TEXT PRIMARY KEY,        -- card-{uuid}
    user_id        TEXT NOT NULL,
    session_id     TEXT DEFAULT '',
    
    -- 检索内容（小而精）
    topic          TEXT NOT NULL,            -- 一句话主题（≤100 字）
    summary        TEXT NOT NULL,            -- 结构化摘要（≤300 字）
    entities       TEXT DEFAULT '[]',        -- 提取的实体列表（JSON）
    tags           TEXT DEFAULT '[]',        -- 标签
    
    -- 来源标识（按"谁说的"检索）
    role           TEXT NOT NULL,            -- user/assistant/agent/tool
    agent_id       TEXT DEFAULT '',          -- role=agent/tool 时有值
    
    -- 关联回查
    raw_ids        TEXT NOT NULL,            -- 关联的 raw_id 列表（JSON）
    
    -- 检索属性
    intent_tag     TEXT DEFAULT 'general',   -- coding/recall/casual/orchestration
    memory_type    TEXT DEFAULT 'episodic',  -- episodic/semantic/procedural
    importance     REAL DEFAULT 0.5,
    access_count   INTEGER DEFAULT 0,        -- 真正的访问计数（不是 version）
    last_accessed  TEXT DEFAULT '',
    
    -- 时间
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL,
    
    -- 权限
    access_level   TEXT DEFAULT 'private'    -- private/shared
);
CREATE INDEX idx_card_user ON memory_cards(user_id, created_at DESC);
CREATE INDEX idx_card_session ON memory_cards(session_id);
CREATE INDEX idx_card_intent ON memory_cards(intent_tag);
CREATE INDEX idx_card_topic ON memory_cards(topic);
CREATE INDEX idx_card_role ON memory_cards(role, agent_id);
CREATE INDEX idx_card_type ON memory_cards(memory_type);

-- FTS5 索引（强制使用 jieba 分词器）
CREATE VIRTUAL TABLE memory_cards_fts USING fts5(
    card_id UNINDEXED, topic, summary, entities, tags,
    tokenize = 'jieba'
);

-- 向量索引（dimension 配置自适配模型）
CREATE VIRTUAL TABLE vec_cards USING vec0(
    card_id TEXT PRIMARY KEY, embedding FLOAT[<auto>]
);
```

### 3.3 Sessions 表（新建，合并会话状态 + Core Memory + Working Memory）

```sql
CREATE TABLE sessions (
    session_id    TEXT PRIMARY KEY,         -- sess-{uuid}
    user_id       TEXT NOT NULL,
    topic         TEXT DEFAULT '',           -- LLM 提取的主题
    intent_tags   TEXT DEFAULT '[]',         -- 该 session 涉及的意图标签列表
    summary       TEXT DEFAULT '',           -- 滚动摘要（防膨胀的核心）
    status        TEXT DEFAULT 'active',     -- active / closed
    created_at    TEXT NOT NULL,
    closed_at     TEXT,
    last_active_at TEXT NOT NULL             -- 用于超时关闭
);

-- Working Memory 持久化（替代内存 dict）
CREATE TABLE working_memory (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id    TEXT NOT NULL,
    user_id       TEXT NOT NULL,
    role          TEXT NOT NULL,             -- user/assistant/agent/tool
    agent_id      TEXT DEFAULT '',
    content       TEXT NOT NULL,
    created_at    TEXT NOT NULL
);
CREATE INDEX idx_wm_session ON working_memory(session_id, created_at DESC);

-- Core Memory（用户长期事实）
CREATE TABLE core_memory (
    slot_id       TEXT PRIMARY KEY,         -- preferences/current_projects/profile/pinned_facts
    user_id       TEXT NOT NULL,
    value         TEXT NOT NULL,
    status        TEXT DEFAULT 'confirmed',  -- confirmed/pending
    updated_at    TEXT NOT NULL
);
CREATE INDEX idx_core_user ON core_memory(user_id, status);

CREATE INDEX idx_sessions_user ON sessions(user_id, status);
CREATE INDEX idx_sessions_active ON sessions(last_active_at, status);
```

### 3.4 容量策略：不再删除，改用冷热分层 + 可回查

```
现在的策略：超量 → LRU 删除 → 记忆丢失 ✗

优化后的策略：
  热库（hot）：  最近 30 天的 raw_memory，直接可查
  温库（warm）： 30-90 天，压缩存储（gzip），查时解压
  冷库（cold）： 90 天以上，搬到 archive.db，仍按 raw_id 索引

  memory_cards 永远不删除（它们很小，全部驻留热库）
  raw_memory 永远不删除，只是搬家

【硬规则 4：冷库必须可回查】
  archive.db 不是死档案，而是冷存储：
  - 按 raw_id 主键查询，30s 内返回原文
  - 与 memory_cards.raw_ids 关联永不失效
  - 用户问"展开原文"时，无论冷热都能回查

  检索流程：
  1. memory_cards 全库检索（不区分冷热，卡片都在热库）
  2. 找到目标卡片后，按需回查 raw_memory
     - tier=hot → 直接读
     - tier=warm → 解压读
     - tier=cold → 从 archive.db 读
  3. 用户用卡片摘要够用时，不回查（节省 IO）
```

---

## 4. 上下文与记忆检索：两件不同的事

> 这是整个记忆系统的核心边界。不分清楚，就会"塞一堆历史进 prompt"或者"该记的没记住"。

### 4.0 /new：session 的分界线

`/new` 是系统的一条上下文更新指令，由用户主动发起，作用是**切断当前 session，开启新 session**。

```
session A 进行中
  用户：[消息1]   ┐
  Agent：回复     │
  用户：[消息2]   │  这些都属于 session A
  Agent：回复     │  上下文持续注入，每轮自动携带
  用户：[消息3]   │  不需要任何触发词
  Agent：回复     ┘
  
  用户：/new   ←── 系统指令，session 分界线
                   ↓
                   1. session A 关闭（status=closed）
                   2. session A 的内容落入历史记忆
                   3. 当前上下文清空（最近几轮 + 会话摘要）
                   4. 创建 session B（status=active）

session B 开始
  用户：[消息4]   ┐
  Agent：回复     │  session B 的上下文从这里开始
                  │  看不到 session A 的内容
                  │  除非用户主动检索（"之前说的XX"）
  ...             ┘
```

**关键含义**：

| | 含义 |
|---|---|
| /new 之前 | 当前 session = 上下文持续注入 |
| /new 这一刻 | 旧 session 关闭，新 session 创建，上下文重置 |
| /new 之后 | 旧 session 内容进入历史记忆，需检索才能找回 |
| 上下文的生命周期 | = 一个 session 的生命周期 = 两个 /new 之间 |
| 触发判断 | 由用户决定，系统不会自动判断"该 /new 了" |

**用户聊了 100 轮没发 /new** → 这 100 轮都是当前 session，上下文都在（用摘要 + 最近几轮表达，不会膨胀）

**用户发了 /new** → 之前所有内容成为历史，新 session 干净开始

### 4.0.1 上下文 = 当前 session 里所有发生的事

当前 session 不只是"用户和 AgentMind 的对话"，而是**这个 session 里所有参与者说的话和做的事**。

```
session A 进行中

  用户：项目X 部署失败                              ┐
  AgentMind：我看看，让 Claude 查一下                │
   └→ 调用 Claude → "检查日志，发现配置错误"          │
  AgentMind：配置文件第 5 行写错了，要不要修？        │  全部都是当前
  用户：修一下                                      │  session 的上下文
  AgentMind：让 Codex 来改                          │  全部都要记忆
   └→ 调用 Codex → "已修改并提交"                    │  全部都可被检索
  AgentMind：改完了，部署看看                        │  全部按"谁说的"
  用户：还是失败                                    │  可以分维度查
  AgentMind：让 Aider 重新分析                      │
   └→ 调用 Aider → "环境变量缺失"                    │
  ...                                              ┘
```

**4 类内容全部入库、全部可检索**：

| 内容来源 | role | 入库 | 注入上下文 | 可被检索 |
|---|---|---|---|---|
| 用户输入 | `user` | ✅ | ✅ | ✅ |
| AgentMind 自己的回复 | `assistant` | ✅ | ✅ | ✅ |
| 被调用 Agent 的回复（Claude/Codex/Aider 等）| `agent` + `agent_id` | ✅ | ✅ | ✅ |
| 工具调用结果（API 返回、命令输出、文件等）| `tool` + `agent_id` | ✅ | ✅ | ✅ |

**带来的能力**：

```
按"谁说的"维度检索：
  "上次 Claude 是怎么说配置错误的？"
    → 搜 role=agent AND agent_id=claude AND 关键词=配置错误
  
  "之前 Codex 改了哪些文件？"
    → 搜 role=agent AND agent_id=codex AND 关键词=修改/文件
  
  "上次的部署日志说什么？"
    → 搜 role=tool AND 关键词=部署/日志
  
  "我之前问过什么？"
    → 搜 role=user
```

**上下文注入也包含所有角色**：注入到下一轮 Prompt 的"最近几轮对话"，不只是用户和 AgentMind 的对话，**还包含被调用 Agent 的回复和工具结果**。这样 Agent 拿到上下文才知道"之前 Claude 说了配置错误，Codex 改了第 5 行"，能延续之前的工作。

### 4.1 概念定义

| 概念 | 作用 | 是否默认注入 |
|---|---|---|
| **当前 Session 上下文** | 支撑当前连续对话，由 /new 定义边界 | ✅ 是，每轮自动注入 |
| **Core Memory** | 用户长期偏好、项目背景、稳定事实 | ✅ 是，但必须很小 |
| **历史记忆** | 之前 session 的长期记录 | ❌ 否，按需检索 |
| **检索结果** | 针对用户这次问题找出的精准几条 | ⚠️ 只在需要时注入 |

**核心边界**：当前 session 上下文和历史记忆**不能混在一起默认塞进上下文**。
- 上下文的生命周期 = 一个 session = 两个 /new 之间，每轮自动带着，不经过检索，不需要触发词
- /new 是用户主动的意图表达："换话题了"，系统不自动判断
- 检索是"翻档案"，找 /new 之前的旧 session 内容，需要触发条件（用户主动问 / 路由判断需要）

时间线上是一根线，不是两条线：当前 session 的内容在"正在发生"时是上下文，session 结束后变成历史记忆。

### 4.2 注入与检索规则

```
┌──────────────────────────────────────────────────────────┐
│  规则 1：当前 session 上下文持续注入                       │
│         最近几轮对话 + 当前会话摘要，每轮都自动带着         │
│         不需要任何触发词，用户发的每条消息都拥有完整上下文   │
│         session 的生命周期由 /new 定义：                    │
│           /new 之前 = 当前 session = 上下文一直在           │
│           /new 之后 = 新 session = 上下文清空重新开始        │
├──────────────────────────────────────────────────────────┤
│  规则 2：历史记忆不默认注入，按需检索                      │
│         只在两种情况进入 prompt：                          │
│         a) 用户明确问"之前/上次/历史/还记得"                │
│         b) 当前问题语义明显需要历史背景                     │
├──────────────────────────────────────────────────────────┤
│  规则 3：查询优先当前 session，找不到再查历史              │
││         "刚才/上面"     → 只查当前 session 最近几轮         │
│         "之前说的XX"    → 当前 session 全量 → 找不到再查历史 │
│         （任何当前session中的指代都自动有上下文，无需检索） │
│         "上次/昨天"     → 直接查历史                        │
├──────────────────────────────────────────────────────────┤
│  规则 4：查询尊重用户意图维度                              │
│         按时间："今天聊了什么"                              │
│         按主题："关于记忆模块的建议"                        │
│         按结果集："展开第 2 条""还有别的吗"                 │
├──────────────────────────────────────────────────────────┤
│  规则 5：检索结果精准返回，数量由意图决定                  │
│         找答案（"那个 bug 修了吗"）→ 精准 1 条 + 置信度     │
│         找方案（"之前的方案是什么"）→ 1-3 条                │
│         浏览（"最近聊了什么"）→ 5-10 条摘要                 │
├──────────────────────────────────────────────────────────┤
│  规则 6：结果集可导航，"展开/还有"不重新搜索               │
│         第 1 次查询返回 N 条，存 result_set_id              │
│         "展开第 2 条" → 按 result_set_id 直接取             │
│         "还有别的吗" → 在同一 result_set 翻页              │
│         省 token + 结果一致                                 │
└──────────────────────────────────────────────────────────┘
```

### 4.3 两类查询的不同处理

```
┌─ 类型 A：精准搜索（用户主动查，要确定答案）──────────┐
│                                                       │
│  例："之前那个 bug 修了吗？"                           │
│                                                       │
│  流程：                                               │
│   查询预处理 → 2 路搜索 → 重排 → LLM 验证            │
│                                              │        │
│                                              ▼        │
│   置信度 ≥ 0.8  →  返回那 1 条 + 原文回查              │
│   置信度 0.6-0.8 → 返回最相关 + "不太确定，还有 N 条" │
│   置信度 < 0.6   → "没找到确定答案，最相关几条如下"    │
│                                                       │
└───────────────────────────────────────────────────────┘

┌─ 类型 B：上下文注入（自动注入，给 Agent 背景）───────┐
│                                                       │
│  触发：用户在写代码，路由判断需要历史背景              │
│                                                       │
│  流程：                                               │
│   查询预处理 → 2 路搜索 → 重排 → 直接注入             │
│                                                       │
│  返回：                                               │
│   3-5 条相关卡片，作为背景信息                         │
│   不做 LLM 验证（不值得花 token）                     │
│                                                       │
└───────────────────────────────────────────────────────┘

关键区别：
  类型 A 要的是"那一个答案"，召回多 → 重排 → LLM 挑出最准的 1 条
  类型 B 要的是"相关背景"，召回多 → 重排 → 取 top 几条直接用
  把它们混在一起返回 top 5-10，本质是"用数量弥补精度"
```

### 4.4 结果集导航（新增机制）

```
用户：搜一下之前的部署方案
系统：查到 5 条候选，返回精排后的 top 3
      [存：result_set_xxx = {3 条结果, 总候选 5 条}]

用户：展开第 2 条
系统：从 result_set_xxx 直接取第 2 条原文，不重新搜索

用户：还有别的吗
系统：从 result_set_xxx 取剩下的 2 条候选

用户：（30 分钟后）展开第 2 条
系统：result_set 已过期，提示用户重新查询
```

数据模型：

```sql
CREATE TABLE result_sets (
    result_set_id   TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL,
    session_id      TEXT NOT NULL,
    query_text      TEXT NOT NULL,           -- 原始查询
    card_ids        TEXT NOT NULL,           -- 候选卡片 ID 列表（JSON）
    returned_top    INTEGER NOT NULL,        -- 已返回 top N
    created_at      TEXT NOT NULL,
    expires_at      TEXT NOT NULL            -- TTL 30 分钟
);
CREATE INDEX idx_resultset_session ON result_sets(session_id, created_at DESC);
```

---

## 5. 检索流程详解

### 整体流程

```
用户说："之前那个 bug 修了吗？"
    │
    ▼
┌─ 查询预处理（把模糊变精确）───────────────────────┐
│                                                    │
│  1. 读 Core Memory → 知道用户在做"项目X"            │
│  2. 读 Working Memory → 知道最近聊"登录模块"        │
│  3. LLM 改写查询：                                  │
│     "之前那个 bug 修了吗？"                          │
│     → "项目X 登录模块 bug 修复状态"                  │
│  4. 提取条件：                                      │
│     意图 = recall                                   │
│     实体 = [项目X, 登录模块]                         │
│     时间 = 上周（2026-05-19 ~ 2026-05-26）           │
│     类型 = EPISODIC                                 │
│                                                    │
└────────────────────────────────────────────────────┘
    │
    ▼
┌─ 第一段：快速召回（从 Recall Cards 中广撒网）──────┐
│                                                    │
│  路线 A：FTS5（jieba 分词）                         │
│    "项目X / 登录 / 模块 / bug / 修复 / 状态"        │
│    命中 30 张卡片                                   │
│                                                    │
│  路线 B：向量检索（中文模型 + 相似度阈值 0.5）       │
│    语义搜索命中 15 张卡片                            │
│                                                    │
│  过滤（在搜索前就过滤，不是搜完再筛）：               │
│    user_id = 当前用户                               │
│    intent_tag = recall                              │
│    时间范围 = 上周                                  │
│    实体匹配 = 项目X                                 │
│                                                    │
│  合并去重：50-80 张候选卡片                         │
│                                                    │
└────────────────────────────────────────────────────┘
    │
    ▼
┌─ 第二段：精准重排（从候选中挑最好的）─────────────┐
│                                                    │
│  信号加权排序（权重可配置）：                        │
│    相关性（FTS5/向量得分）  40%                     │
│    用户/权限匹配           20%                      │
│    时间匹配               15%                      │
│    重要性                 15%                      │
│    最近访问               10%                      │
│                                                    │
│  可选：Reranker 交叉编码器精排                      │
│                                                    │
│  取 top 5-10 张候选卡片                            │
│                                                    │
└────────────────────────────────────────────────────┘
    │
    ▼
┌─ 第三段：按查询类型决定最终输出（关键）──────────┐
│                                                    │
│  类型 A：精准搜索（要确定答案）                     │
│    LLM 验证：从 top 5-10 中挑最相关的 1 条          │
│    返回：1 条 + 置信度 + 原文回查                  │
│    置信度 < 0.6 时返回最相关几条 + 提示             │
│                                                    │
│  类型 B：上下文注入（要背景信息）                   │
│    直接取 top 3-5 注入                             │
│    不做 LLM 验证（省 token）                        │
│                                                    │
│  类型 C：浏览类查询（"最近聊了什么"）               │
│    取 top 5-10 摘要返回                            │
│                                                    │
│  存 result_set_id，支持后续"展开/还有"导航          │
│                                                    │
└────────────────────────────────────────────────────┘
    │
    ▼
┌─ 上下文组装（控制总量不膨胀）─────────────────────┐
│                                                    │
│  Core Memory：         1-2KB                       │
│  会话摘要：            1-2KB                       │
│  最近 3-5 轮原文：     2KB                         │
│  召回结果（按类型）：   1-8KB                      │
│    类型 A：1 条精准答案 ≈ 1KB                       │
│    类型 B：3-5 条卡片  ≈ 4KB                       │
│    类型 C：5-10 条摘要 ≈ 8KB                       │
│  ─────────────────────────                         │
│  总计：               5-14KB                       │
│                                                    │
│  卡片优先保，原文按需取                              │
│  超预算时砍原文保卡片，不是砍卡片保原文              │
│                                                    │
└────────────────────────────────────────────────────┘
```

### 为什么砍到 2 路就够了

| 搜索路 | 保留/砍 | 理由 |
|---|---|---|
| **FTS5（加 jieba）** | ✅ 保留 | 主力，负责字面匹配，修好分词后解决 80%+ 需求 |
| **向量检索（换中文模型）** | ✅ 保留 | 补足语义匹配，FTS5 找不到"意思相近"的它来补 |
| n-gram LIKE | ❌ 砍 | <1% 贡献，几乎全是噪音 |
| 图谱 1 跳 | ❌ 砍 | <1% 贡献，5 条正则太稀疏，等 LLM 抽关系再考虑 |
| 普通 LIKE | 🟡 降级 | 只在 FTS5 异常时做 fallback，不是独立搜索路 |

2 路搜索 + 好的查询预处理 > 5 路暴力搜。

---

## 6. 必须修的 bug 和小改动

不分阶段，做记忆模块时就要一起修。按优先级排序：

| # | 问题 | 修什么 | 对应硬规则 |
|---|---|---|---|
| 1 | **检索评测集先于优化** | 建立固定问答对（≥50 组），优化有标准可衡量；比加搜索路更重要 | 硬规则 5 |
| 2 | 冷库可按 raw_id 回查 | archive.db 按 raw_id 主键索引，30s 内返回原文；卡片 raw_ids 关联永不失效 | 硬规则 4 |
| 3 | 3 表物理分离 | 新建 raw_memory + memory_cards，不再改造 memory_entries；迁移期双写，完成后废弃旧表 | 硬规则 2 |
| 4 | 上下文/检索边界 | 当前 session 上下文持续注入 ≠ 历史检索按需触发；/new 是分界线 | 硬规则 1 |
| 5 | 查询分类型输出 | 类型 A 精准 1 条 + 验证 / 类型 B 3-5 条背景 / 类型 C 5-10 条浏览 | 硬规则 3 |
| 6 | 向量维度不匹配 | 配置 384 维 vs OpenAI 模型 1536 维，自动检测对齐 | - |
| 7 | 向量检索不按用户过滤 | 先加 user_id + access_level 条件再搜向量，防串记忆 | - |
| 8 | 日期范围 bug | start 和 end 别设成同一个值，支持真正范围 | - |
| 9 | Core Memory 自动确认 | importance >= 0.8 自动确认，不再空着 | - |
| 10 | Working Memory 持久化 | 从内存 dict → working_memory 表，重启不丢 | - |
| 11 | v4 默认开启 | v4_write_enabled / v4_retrieval_enabled 改为 true | - |
| 12 | Conversation 切分 | 不只按 30 分钟，还按意图变化（intent_tag 变化时切分） | - |
| 13 | FTS5 查询转义 | 用户输入的 `*`, `OR`, `AND` 等 FTS5 语法要转义 | - |
| 14 | 结果集导航 | 新增 result_sets 表，支持"展开/还有"不重复搜索 | - |
| 15 | 多角色入库 | role 字段支持 user/assistant/agent/tool，agent_id 标识具体来源 | - |
| 16 | 上下文注入完整性 | 注入"最近几轮"时包含所有角色（用户/AM/被调 Agent/工具） | - |

---

## 7. 写入流程变化

```
现在的写入：
  用户消息 → memory_entries（一个表又存又索引，违反硬规则 2）

优化后的写入（双写，物理分离）：
  session 中任何一方的发言（用户/AgentMind/被调 Agent/工具）
      │
      ├→ raw_memory 表（存完整原文，按 role + agent_id 区分来源）
      │   - role=user：用户输入
      │   - role=assistant：AgentMind 自己的回复
      │   - role=agent + agent_id=claude/codex/...：被调 Agent 的回复
      │   - role=tool + agent_id=...：工具调用结果
      │   - 永不删除，超量搬冷库（仍按 raw_id 可回查）
      │
      └→ Write Pipeline 处理后：
          ├→ memory_cards 表（生成检索卡片，新表，不写 memory_entries）
          │   - card_id：card-{uuid}
          │   - topic：一句话主题（LLM 提取，≤100 字）
          │   - summary：结构化摘要（≤300 字）
          │   - entities：实体列表（LLM 提取）
          │   - tags：标签
          │   - role + agent_id：继承自 raw_memory，用于按"谁说的"检索
          │   - raw_ids：关联的原文 id 列表（JSON）
          │   - intent_tag：从路由决策获取
          │   - 向量嵌入：基于 topic + summary 生成
          │   - 永不删除（小且全量驻留热库）
          │
          ├→ core_memory（如果检测到用户偏好/重要事实，importance ≥ 0.8 自动确认）
          │
          ├→ working_memory（当前 session 最近几轮，持久化到表，不再用内存 dict）
          │
          └→ sessions.summary（滚动更新当前会话摘要）

迁移策略（旧表平滑废弃）：
  阶段 1：新写入双写到 raw_memory + memory_cards，旧 memory_entries 同时写
  阶段 2：检索路径切换到 memory_cards，memory_entries 只读
  阶段 3：批量回填 memory_entries → raw_memory + memory_cards
  阶段 4：废弃 memory_entries（保留 view 兼容旧 API，逐步移除）
```

---

## 8. 与整体方案的衔接

本方案是 Phase 1（修地基）中记忆模块的详细设计。完成后：

```
Phase 1 记忆模块优化
  ├─ 3 表物理分离（raw_memory / memory_cards / sessions）← 硬规则 2
  ├─ 上下文 vs 检索边界（5 条硬规则 + /new 分界线）← 硬规则 1
  ├─ 多角色入库（user/assistant/agent/tool 全部记忆 + 可检索）
  ├─ 2 路搜索 + 查询预处理 + 三段式检索
  ├─ 按查询类型决定输出（精准 1 条 / 上下文 3-5 条 / 浏览 5-10 条）← 硬规则 3
  ├─ 结果集导航（"展开/还有"不重复搜索）
  ├─ 冷热分层 + 冷库可回查（不再删除）← 硬规则 4
  ├─ 检索评测集先于优化建立 ← 硬规则 5
  ├─ 16 个 bug/小改动（优先级排序）
  └─ Session 持久化 + 意图标签 + 迁移策略

代码量变化：
  删除：n-gram LIKE + 图谱搜索 + 3 路融合 + memory_entries 旧逻辑 ≈ 300 行
  新增：raw_memory 层 + memory_cards 生成 + 冷热迁移 + 结果集导航 + 评测集 ≈ 600 行
  改造：写入双写 + 检索切换到 cards + 上下文注入边界 + 迁移脚本 ≈ 500 行
  净增：约 800 行，但 3 表分离 + 评测集让结构更清晰、检索精度可衡量

工作量：5-7 周
  第 1 周：建评测集（≥50 组问答对）+ 新表 DDL + 迁移脚本
  第 2-3 周：写入双写（raw_memory + memory_cards）+ 旧表兼容
  第 4-5 周：检索切换到 memory_cards + 上下文/检索边界 + 结果集导航
  第 6 周：冷热分层 + 冷库回查 + 评测集回归
  第 7 周：16 个 bug 逐个修复 + 全量回归
```

### 8.1 架构变化是否符合长远发展

```
┌─ 变化点 ────────────────┬─ 短期代价 ────────┬─ 长期收益 ──────────────────────┐
│ 3 表物理分离             │ 迁移双写 2-3 周    │ 原文/卡片/会话独立演进，互不干扰  │
│ memory_cards 新表        │ 重写写入逻辑       │ 检索只查小卡片，速度和精度都提升   │
│ 评测集先于优化           │ 1 周建集           │ 优化有数据支撑，不再凭感觉调参     │
│ 冷库可回查               │ 额外索引维护       │ 全量保存真正可用，记忆永不丢失     │
│ 查询分类型输出           │ 额外判断逻辑       │ 精准查不浪费 token，浏览查有广度   │
│ 迁移期双写 + 4 阶段废弃  │ 短期写入量翻倍     │ 平滑过渡，不冒一次性切换风险       │
└──────────────────────────┴────────────────────┴──────────────────────────────────┘

关键判断：3 表分离是"现在多花 3 周，以后每次改一层不影响其他层"。
          如果不做，未来每次加字段、改索引、调存储策略都要动 memory_entries 全表。
```

---

## 9. 核心边界总结（一图看清）

```
                    AgentMind 记忆系统
                          │
        ┌─────────────────┼─────────────────┐
        ▼                 ▼                 ▼
   实时上下文          长期记忆            检索能力
   （会呼吸的）        （档案库）          （翻档案的工具）
        │                 │                 │
   ┌────┴────┐       ┌────┴────┐       ┌───┴────┐
   ▼         ▼       ▼         ▼       ▼        ▼
 core_     working_ raw_     memory_  精准搜索  上下文
 memory    memory   memory   cards    类型 A    注入
 长期事实  最近     全量     检索     1 条      类型 B
 每次注入  几轮     原文     卡片     答案      3-5 条
                   不删     小而准   + 验证

   持续注入 ────→         按需检索 ────→
   每轮带着              用户问 / 路由判断时

3 层物理分离（硬规则 2）：
  raw_memory      = 原文层，只写不删，超量搬冷库
  memory_cards    = 检索层，新表，永不删除，全量驻留热库
  sessions        = 会话状态层，滚动更新

边界（硬规则 1）：
  上下文 = 当前 session 实时携带，不经过检索
           生命周期 = 两个 /new 之间
  检索   = 翻历史档案（/new 之前的旧 session 内容），需要触发条件
  /new   = 用户主动的 session 分界线，关闭当前、开启新的
```
