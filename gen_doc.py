"""Generate AgentMind project overview Word document."""
from docx import Document
from docx.shared import Inches, Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
import os

doc = Document()

# -- Style config --
style = doc.styles['Normal']
font = style.font
font.name = 'Microsoft YaHei'
font.size = Pt(11)
style.paragraph_format.space_after = Pt(6)
style.paragraph_format.line_spacing = 1.35

for level in range(1, 4):
    h = doc.styles[f'Heading {level}']
    h.font.color.rgb = RGBColor(0x1a, 0x56, 0xdb)
    h.font.name = 'Microsoft YaHei'

def add_table(doc, headers, rows, col_widths=None):
    table = doc.add_table(rows=1 + len(rows), cols=len(headers))
    table.style = 'Light Grid Accent 1'
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, h in enumerate(headers):
        cell = table.rows[0].cells[i]
        cell.text = h
        for p in cell.paragraphs:
            for run in p.runs:
                run.bold = True
    for ri, row in enumerate(rows):
        for ci, val in enumerate(row):
            table.rows[ri + 1].cells[ci].text = str(val)
    if col_widths:
        for ri, row in enumerate(table.rows):
            for ci, w in enumerate(col_widths):
                row.cells[ci].width = Cm(w)
    doc.add_paragraph()
    return table

def add_code(doc, text):
    p = doc.add_paragraph()
    run = p.add_run(text)
    run.font.name = 'Courier New'
    run.font.size = Pt(10)
    return p

# ============================================================
# TITLE PAGE
# ============================================================
title = doc.add_heading('AgentMind 项目介绍', level=0)
title.alignment = WD_ALIGN_PARAGRAPH.CENTER

sub = doc.add_paragraph()
sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
run = sub.add_run('本地 AI 指挥中枢 — 智能路由 + 多 Agent 编排 + 飞书接入')
run.font.size = Pt(14)
run.font.color.rgb = RGBColor(0x55, 0x55, 0x55)

meta = doc.add_paragraph()
meta.alignment = WD_ALIGN_PARAGRAPH.CENTER
meta.add_run('版本 1.0.0  |  2026-05-25  |  Python 3.12+').font.size = Pt(10)

doc.add_page_break()

# ============================================================
# 1. 项目概述（含设计亮点）
# ============================================================
doc.add_heading('1. 项目概述', level=1)

doc.add_paragraph(
    'AgentMind 是一个运行在本地的 AI 指挥中枢。它不"制造"Agent，而是指挥用户已安装的 AI 工具。'
    '当用户在电脑上安装了 Claude Code、Hermes、Codex、Aider 等多个 AI 编程助手后，'
    'AgentMind 会自动发现这些工具，提供一个统一入口，并根据用户指令的内容智能路由到最合适的 Agent 去执行，'
    '最终将结果通过控制面板、REST API 或飞书消息返回给用户。'
)

doc.add_heading('一句话定位', level=2)
doc.add_paragraph(
    'AgentMind = Agent 路由器 + 进程管理器 + 共享记忆 + 飞书桥接。'
    '本身不做 AI 推理，所有 AI 能力由用户安装的外部工具提供。'
)

doc.add_heading('解决什么痛点', level=2)
problems = [
    '多 Agent 工具之间需要手动切换，记住每个工具的调用方式和适用场景',
    '上下文断裂：在 Claude Code 里讨论的需求，换到 Hermes 时无法延续',
    '缺乏统一管理：不知道哪些 Agent 可用、健康状态如何、谁更适合当前任务',
    '飞书通知需求：希望从飞书发起任务，结果也回到飞书',
]
for p in problems:
    doc.add_paragraph(p, style='List Bullet')

doc.add_heading('设计亮点', level=2)

highlights = [
    ('多协议统一抽象',
     'CLI 子进程、HTTP API、MCP JSON-RPC、A2A 四种 Agent 协议全部通过统一的 BaseAgentExecutor 接口接入，新增协议只需实现三个方法（execute / execute_stream / health_check）。'),
    ('策略管道热插拔',
     '四种路由策略按优先级链式执行，各自独立封装，添加新策略只需实现 RoutingStrategy 接口并注册到管道，无需修改现有代码。首个置信度 ≥0.7 即命中返回，兼顾精度与性能。'),
    ('混合记忆检索',
     'FTS5 全文搜索 + sqlite-vec 向量搜索的 RRF 融合，兼顾精确匹配和语义相似。冲突检测同时考虑语义相似度和可信度，避免错误信息覆盖正确记忆。'),
    ('飞书非侵入集成',
     'WebSocket 出站连接，不需要公网暴露。SDK 阻塞调用隔离在独立线程，不影响异步主循环。配置热加载，保存即生效。'),
    ('本地优先，零外部依赖',
     'SQLite 嵌入式数据库、本地 Embedding 模型后备、自动生成的认证令牌，整个系统可以完全离线运行。Core LLM 是唯一需要外部服务的组件，但也是可选的。'),
    ('崩溃恢复',
     '启动时自动检测并标记超时任务为可重试，保留重试上下文。心跳超时可配置，兼容不同运行环境。'),
    ('可观测性内置',
     'P50/P90/P99 延迟统计、Agent 错误率、1 小时吞吐量、路由决策全链路追踪，所有指标通过面板 API 暴露。'),
]

for title_text, desc in highlights:
    p = doc.add_paragraph()
    run = p.add_run(f'{title_text}：')
    run.bold = True
    p.add_run(desc)

doc.add_page_break()

# ============================================================
# 2. 技术架构
# ============================================================
doc.add_heading('2. 技术架构', level=1)

doc.add_heading('2.1 技术栈', level=2)
add_table(doc,
    ['层次', '技术选型', '说明'],
    [
        ['语言', 'Python 3.12+', '异步生态成熟，CLI 子进程管理方便'],
        ['Web 框架', 'FastAPI + Uvicorn', '高性能异步 REST API + SSE 流式响应'],
        ['数据库', 'SQLite (history.db + memory.db)', '零配置、嵌入式、FTS5 全文搜索 + sqlite-vec 向量索引'],
        ['前端', 'Pico CSS + React Flow (CDN)', '单文件 HTML 控制面板 + DAG 编排画布'],
        ['飞书通道', 'lark-oapi SDK', 'WebSocket 长连接（出站，无需公网 IP）'],
        ['测试', 'pytest + pytest-asyncio', '343 个测试，覆盖单元/集成/端到端'],
    ],
    col_widths=[2.5, 5, 7.5]
)

doc.add_heading('2.2 目录结构', level=2)
doc.add_paragraph('项目采用清晰的分层结构，核心源码位于 src/agentmind/：')

dirs = [
    ('api/', 'REST API 层 — 路由端点、Agent 管理、编排执行、认证中间件'),
    ('routing/', '路由决策引擎（v2 核心） — L0-L4 四层管道，24 个文件'),
    ('agents/', 'Agent 执行器 — CLI / API / MCP / A2A 四种协议实现 + 自动发现'),
    ('core/', '核心能力 — Core LLM、规则引擎、Trace ID 生成'),
    ('storage/', '持久化存储 — 数据库 CRUD、记忆引擎（FTS5+向量）、Embedding'),
    ('channels/', '消息通道适配器 — 飞书 WebSocket 长连接'),
    ('panel/', 'Web 控制面板 — 39 个 API 端点 + 静态前端页面 + DAG 编排画布'),
    ('config/', '配置管理 — 默认配置生成'),
]
for name, desc in dirs:
    p = doc.add_paragraph()
    run = p.add_run(f'{name}')
    run.bold = True
    run.font.name = 'Courier New'
    run.font.size = Pt(10)
    p.add_run(f'  {desc}')

doc.add_heading('2.3 运行时数据目录', level=2)
doc.add_paragraph('所有运行时数据存储在 ~/.agentmind/ 下：')
add_table(doc,
    ['路径', '内容'],
    [
        ['config/agents.yaml', 'Agent 注册配置（自动发现生成）'],
        ['config/routes.yaml', '路由规则（关键词/正则匹配）'],
        ['config/settings.yaml', '全局设置（LLM、记忆、飞书配置）'],
        ['config/auth.token', '本地认证令牌（64 位 hex，0o600 权限）'],
        ['data/history.db', '任务历史记录'],
        ['data/memory.db', '共享记忆库（含 FTS5 全文索引 + 向量索引）'],
        ['data/results/', '任务结果全文（{trace_id}.txt）'],
    ],
    col_widths=[5, 10]
)

doc.add_page_break()

# ============================================================
# 3. 路由决策引擎
# ============================================================
doc.add_heading('3. 路由决策引擎（v2 四层架构）', level=1)

doc.add_paragraph(
    '路由是 AgentMind 最核心的能力。v2 版本将旧的 6 步拍平管道重构为四层架构，'
    '每层职责清晰、可独立测试、策略可按优先级热插拔。'
)

doc.add_heading('3.1 处理流程', level=2)
doc.add_paragraph(
    '用户指令进入后，首先经过前置拦截器判断是否为编排/讨论/Attach 等特殊模式；'
    '否则进入四层管道：'
)

pipeline_steps = [
    ('L0 前置中间件', '敏感信息扫描（检测 API Key/密码）→ 候选池过滤（健康+安全等级）→ 记忆检索（双路召回：近期+关键词）'),
    ('L1 意图分类', '当前统一归类为 SINGLE_TASK（编排/讨论等已在入口拦截）'),
    ('L2 策略管道', '四种路由策略按优先级依次执行，首个置信度 ≥ 0.7 即命中'),
    ('L3 执行调度', '调用目标 Agent 执行，含 fallback_chain 自动重试机制'),
    ('L4 副作用', '任务记忆写入 + 原子事实提取 + 决策链路追踪 + 会话状态更新'),
]
for title_text, desc in pipeline_steps:
    p = doc.add_paragraph()
    run = p.add_run(f'{title_text}：')
    run.bold = True
    p.add_run(desc)

doc.add_heading('3.2 四种路由策略', level=2)
add_table(doc,
    ['策略', '优先级', '置信度', '原理'],
    [
        ['ExplicitDirective（显式指定）', '0（最先）', '1.0', '用户输入中 @agent_name 直接指定目标'],
        ['RuleEngineStrategy（规则匹配）', '10', '0.85–0.90', '关键词/正则匹配 routes.yaml 中预定义规则'],
        ['LLMRoutingStrategy（语义路由）', '20', '0.80–0.90', '调用 Core LLM 理解语义，判断自答还是路由到哪个 Agent'],
        ['SignalScoringStrategy（信号评分）', '100（兜底）', '0.20–0.30', '综合成本/延迟/安全评分，永不弃权，保证必定选出 Agent'],
    ],
    col_widths=[4.5, 2, 2, 6.5]
)

doc.add_paragraph(
    '策略采用"首胜即退"模式：前面的策略给出足够置信度就直接返回，不继续执行后续策略。'
    '最后一道 SignalScoring 永不弃权（confidence > 0），保证任何请求都有 Agent 承接。'
)

doc.add_heading('3.3 特性开关', level=2)
doc.add_paragraph(
    '路由管道版本通过 settings.yaml 中的 routing.use_new_pipeline 控制，新管道默认开启。'
    '语义路由 LLM 需用户手动配置 settings.yaml 中的 Core LLM 参数才激活。'
)

doc.add_page_break()

# ============================================================
# 4. Agent 管理
# ============================================================
doc.add_heading('4. Agent 管理与执行', level=1)

doc.add_heading('4.1 四种连接协议', level=2)
add_table(doc,
    ['协议', '通信方式', '适用场景', '实现类'],
    [
        ['CLI', 'subprocess + pipe', '本地命令行工具（Claude Code、Hermes 等）', 'CLIExecutor'],
        ['API', 'HTTP REST', '远程 HTTP 服务', 'APIExecutor'],
        ['MCP', 'JSON-RPC 2.0 over stdio', 'Model Context Protocol 服务器', 'MCPExecutor'],
        ['A2A', 'HTTP POST', 'Agent-to-Agent 远程端点', 'A2AExecutor'],
    ],
    col_widths=[2, 3, 5, 3]
)

doc.add_heading('4.2 自动发现机制', level=2)
doc.add_paragraph('AgentMind 内置两层的 Agent 自动发现策略：')

discovery = [
    '第一层 — 已知 Agent 快路径：内置 9 个已知 AI 工具的特征库（Claude Code、Hermes、Codex、Aider、Cursor Agent、Warp AI、Ollama、OpenClaw），每个包含检测命令、标签、配置模板，命中即直接注册。',
    '第二层 — 通用探测：扫描 PATH 中所有可执行文件，通过 --version 验证 + 多种常见 CLI 调用模式探测（-p, exec, ask 等），命中则自动生成配置模板。限 20 个/30 秒。',
    '非首次启动时合并新 Agent 到已有配置，不覆盖用户手动修改。',
]
for d in discovery:
    doc.add_paragraph(d, style='List Bullet')

doc.add_heading('4.3 运行时约束', level=2)
doc.add_paragraph('最多 5 个并发执行槽位 | 单任务输出上限 1MB | 超时 120 秒 | 崩溃恢复（心跳超时可配置）')

doc.add_page_break()

# ============================================================
# 5. 记忆系统
# ============================================================
doc.add_heading('5. 共享记忆系统', level=1)

doc.add_heading('5.1 核心能力', level=2)
mem_features = [
    '混合检索：FTS5 全文搜索 + sqlite-vec 向量语义搜索，通过 RRF（Reciprocal Rank Fusion）融合排序',
    '双路召回：近期记忆（按时间倒序 2 条）+ 关键词匹配（3 条），去重合并上限 5 条',
    '原子事实提取：通过 Core LLM 从对话中自动提取 knowledge / preference / decision 三类事实',
    '语义冲突检测：新记忆写入时检测与已有记忆的向量相似度（阈值 0.85），冲突时根据可信度择优保留',
    'LRU 淘汰：存满时淘汰 10% 最不常用记忆',
    '热度分级：hot / warm / cold 三级统计（基于 last_accessed_at）',
]
for f in mem_features:
    doc.add_paragraph(f, style='List Bullet')

doc.add_heading('5.2 数据库结构', level=2)
add_table(doc,
    ['表名', '存储内容', '索引'],
    [
        ['memory_entries', '记忆条目（ID、内容、类型、标签、可信度、时间戳）', '主键 + user_id + memory_type + 时间索引'],
        ['memory_fts', 'FTS5 全文搜索索引', '全文索引（content + tags）'],
        ['vec_memory', '向量嵌入（384 维）', 'sqlite-vec 向量索引'],
    ],
    col_widths=[3, 7, 5]
)

doc.add_page_break()

# ============================================================
# 6. 飞书集成
# ============================================================
doc.add_heading('6. 飞书集成', level=1)

doc.add_paragraph(
    'AgentMind 通过飞书 WebSocket 长连接实现消息收发，出站连接飞书服务器，不需要公网 IP 或端口暴露。'
)

feishu_features = [
    '面板配置：在控制面板填写 App ID / App Secret，保存即连接，无需重启服务',
    '消息路由：用户在飞书给机器人发消息 → AgentMind 路由 → 执行结果回复到飞书',
    '@Agent 指定：消息中包含 @agentname 可直接指定由哪个 Agent 处理',
    '表情反馈：处理中自动添加 💪 表情，完成后移除',
    '讨论模式：支持多 Agent 轮流讨论，用户可发送"停"/"stop"终止',
    '消息分片：回复以 4000 字符为上限自动分片发送',
    '去重保护：deque 记录最近 1000 条 msg_id 防止重复处理',
]
for f in feishu_features:
    doc.add_paragraph(f, style='List Bullet')

doc.add_paragraph(
    '技术实现：lark-oapi SDK 的阻塞调用隔离在独立线程中，通过 asyncio.Queue 与异步主循环通信，保证不阻塞 Web 服务。'
)

# ============================================================
# 7. 控制面板
# ============================================================
doc.add_heading('7. Web 控制面板', level=1)

doc.add_paragraph(
    'AgentMind 启动后自动在 http://127.0.0.1:8765/panel/ 提供 Web 管理界面：'
)

panel_pages = [
    ('仪表盘', '任务统计、最近错误、活跃讨论、Agent 健康状态概览'),
    ('Agent 管理', '已注册 Agent 列表、健康检查、标签编辑、启用/禁用、手动添加、扫描新 Agent'),
    ('路由矩阵', '关键词/正则路由规则的增删改查，热加载到运行中的引擎'),
    ('记忆审计', '记忆条目搜索/查看/删除、统计信息、批量清理'),
    ('编排画布', '基于 React Flow 的 DAG 拖拽式编排器，拖入 Agent 节点，连线定义执行依赖'),
    ('飞书配置', 'App ID / App Secret 配置，连接状态查看，一键连接/断开'),
    ('系统设置', 'Core LLM 配置、记忆引擎参数、Embedding 设置、管道版本开关'),
]
for name, desc in panel_pages:
    p = doc.add_paragraph()
    run = p.add_run(f'{name}：')
    run.bold = True
    p.add_run(desc)

doc.add_paragraph(
    '面板后端提供 39 个 REST API 端点，前端为单文件 HTML（Pico CSS），编排器独立页面使用 React + React Flow CDN 实现。'
    'API 认证采用 Bearer Token + Cookie 双重认证机制。'
)

doc.add_page_break()

# ============================================================
# 8. API 端点
# ============================================================
doc.add_heading('8. 核心 API 端点', level=1)

add_table(doc,
    ['方法', '路径', '功能'],
    [
        ['POST', '/v1/route', '核心路由（支持流式/非流式，编排/讨论/Attach 模式）'],
        ['GET', '/v1/agents/status', '查询所有 Agent 状态与健康信息'],
        ['POST', '/v1/agents/scan', '触发 Agent 扫描发现'],
        ['POST', '/v1/orchestration/execute', '执行 DAG 编排计划'],
        ['GET', '/panel/api/tasks', '任务历史列表（含分页、筛选）'],
        ['GET', '/panel/api/agents', 'Agent 管理列表'],
        ['GET', '/panel/api/memory/search', '记忆搜索'],
        ['POST', '/panel/api/feishu/connect', '飞书通道连接'],
        ['GET', '/panel/api/routing/trace/{id}', '路由决策链路追踪'],
        ['GET', '/panel/api/sessions', '活跃讨论会话列表'],
    ],
    col_widths=[2, 5.5, 7.5]
)

# ============================================================
# 9. 测试覆盖
# ============================================================
doc.add_heading('9. 测试覆盖', level=1)

doc.add_paragraph(
    '项目拥有 343 个测试用例，分布在 18 个测试文件中，覆盖单元测试、策略测试、执行器测试、'
    '副作用测试、飞书端到端测试和集成测试。所有测试全部通过。'
)

add_table(doc,
    ['测试文件', '覆盖模块'],
    [
        ['test_router.py', '核心路由逻辑'],
        ['test_rule_engine.py', '规则引擎（关键词/正则匹配）'],
        ['test_pipeline_executors.py', '管道执行器（SingleAgent / SelfReply）'],
        ['test_cli_executor.py', 'CLI 子进程执行器'],
        ['test_api_executor.py', 'API HTTP 执行器'],
        ['test_mcp_executor.py', 'MCP JSON-RPC 执行器'],
        ['test_a2a_executor.py', 'A2A 远程执行器'],
        ['test_core_llm.py', 'Core LLM 提供者'],
        ['test_memory.py', '记忆引擎（写入/检索/冲突检测/淘汰）'],
        ['test_db.py', '数据库操作与崩溃恢复'],
        ['test_feishu_channel.py', '飞书通道适配器'],
        ['test_feishu_path.py', '飞书端到端路径（25 个测试）'],
        ['test_orchestration.py', 'DAG 编排执行'],
        ['test_panel_api.py', '控制面板 API'],
        ['test_stream.py', 'SSE 流式传输'],
        ['test_attach.py', 'Attach 会话接管'],
        ['test_auth_integration.py', '认证中间件'],
        ['test_e2e_scenarios.py', '全链路端到端场景'],
    ],
    col_widths=[5, 10]
)

doc.add_page_break()

# ============================================================
# 10. 快速开始
# ============================================================
doc.add_heading('10. 快速开始', level=1)

doc.add_heading('安装与启动', level=2)
add_code(doc, 'cd agentmind2026\npip install -e .\nagentmind')

doc.add_paragraph(
    '启动后自动扫描已安装的 AI 工具，浏览器打开 http://127.0.0.1:8765/panel/ 进入控制面板。'
)

doc.add_heading('API 调用示例', level=2)
add_code(doc,
    'TOKEN=$(cat ~/.agentmind/config/auth.token)\n'
    'curl -H "Authorization: Bearer $TOKEN" \\\n'
    '  -X POST http://127.0.0.1:8765/v1/route \\\n'
    '  -H "Content-Type: application/json" \\\n'
    '  -d \'{"message":"写一个 hello world","stream":false}\''
)

doc.add_heading('配置文件位置', level=2)
config_items = [
    ('~/.agentmind/config/agents.yaml', 'Agent 注册与命令模板'),
    ('~/.agentmind/config/routes.yaml', '路由规则'),
    ('~/.agentmind/config/settings.yaml', '语义路由 LLM、飞书通道等全局设置'),
]
for path, desc in config_items:
    p = doc.add_paragraph()
    run = p.add_run(path)
    run.font.name = 'Courier New'
    run.font.size = Pt(10)
    p.add_run(f' — {desc}')

doc.add_page_break()

# ============================================================
# 11. 开发进度与路线图
# ============================================================
doc.add_heading('11. 开发进度与路线图', level=1)

doc.add_heading('已完成（15 项核心功能）', level=2)
add_table(doc,
    ['#', '功能', '阶段'],
    [
        ['1', '数据模型升级（AgentCapability + history.db + memory.db + settings.yaml）', 'Phase 1 — 基础'],
        ['2', '安全层实现（敏感词检测 → 本地 Agent 降级）', 'Phase 1 — 基础'],
        ['3', '崩溃恢复（心跳超时可配置）', 'Phase 1 — 基础'],
        ['4', '语义路由（LLM Top-3 候选 + 幻觉过滤）', 'Phase 2 — 路由'],
        ['5', '信号驱动（成本/延迟/安全评分 + is_retry 权重）', 'Phase 2 — 路由'],
        ['6', '路由管道 v2 升级（4 层架构整合）', 'Phase 2 — 路由'],
        ['7', '共享记忆引擎（写入/检索/统计/清理）', 'Phase 3 — 记忆'],
        ['8', '面板升级（执行预览/记忆审计/飞书配置）', 'Phase 3 — 面板'],
        ['9', 'DAG 可视化编排（React Flow 画布 + 拓扑执行）', 'Phase 4 — 编排'],
        ['10', 'Attach 深度接管（上下文重新路由）', 'Phase 4 — 编排'],
        ['11', 'MCP + A2A 协议支持', 'Phase 4 — 编排'],
        ['12', '任务工作区管理', 'Phase 4 — 编排'],
        ['13', '连接器市场', 'Phase 4 — 编排'],
        ['14', '可观测性（P50/P90/P99 + 错误率 + 吞吐量）', 'Phase 4 — 编排'],
        ['15', '自学习 Agent 探测（双重策略 + 面板手动添加）', 'Phase 4 — 编排'],
    ],
    col_widths=[1, 10, 4]
)

doc.add_heading('待完成事项', level=2)
doc.add_paragraph('当前还有约 26 项待完成，主要包括：')
pending = [
    '控制面板 UI 优化（15 项）：路由矩阵字段更新、Agent 表格扩展列、路由追踪入口、活跃讨论卡片等',
    '记忆引擎增强（3 项）：重要性评分、自动蒸馏、全局记忆层级',
    '基础设施完善（3 项）：独立任务状态数据库、数据迁移脚本、一键导出/恢复',
    '编排 & 执行增强（2 项）：线性链式编排、文件隔离',
    '部分完成功能（3 项）：连接器市场交互、AgentMind 作为 MCP Server、前端自动化测试',
]
for p in pending:
    doc.add_paragraph(p, style='List Bullet')

doc.add_page_break()

# ============================================================
# 12. 关键技术指标
# ============================================================
doc.add_heading('12. 关键技术指标', level=1)

add_table(doc,
    ['指标', '数值'],
    [
        ['代码规模', '约 8,000+ 行 Python（src/）+ 约 1,200 行前端 HTML/JS'],
        ['源代码文件', '39 个 .py 文件 + 3 个前端页面'],
        ['测试数量', '343 个测试用例，18 个测试文件'],
        ['API 端点', '3 个公共 API + 39 个面板 API'],
        ['支持 Agent 协议', '4 种（CLI / API / MCP / A2A）'],
        ['内置已知 Agent', '9 个（Claude Code、Hermes、Codex、Aider 等）'],
        ['路由策略', '4 种（显式指定 / 规则匹配 / LLM 语义 / 信号评分）'],
        ['并发上限', '5 个 Agent 同时执行'],
        ['输出上限', '1MB / 任务'],
        ['超时', '120 秒'],
        ['记忆容量', '默认 10,000 条'],
        ['Embedding 维度', '384 维（all-MiniLM-L6-v2）'],
    ],
    col_widths=[5, 10]
)

# -- Save --
desktop = os.path.expanduser('~/Desktop')
path = os.path.join(desktop, 'AgentMind项目介绍.docx')
doc.save(path)
print(f'Document saved to: {path}')
