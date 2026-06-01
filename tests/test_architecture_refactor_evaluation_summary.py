from pathlib import Path


SUMMARY = Path("docs/architecture/refactor-evaluation-summary.md")


def _summary_text() -> str:
    assert SUMMARY.exists(), "architecture refactor evaluation summary is missing"
    return SUMMARY.read_text(encoding="utf-8")


def test_refactor_evaluation_summary_covers_required_closeout_scope():
    text = _summary_text()

    required_phrases = [
        "# AgentMind 架构重构优化评估总结",
        "Phase 1 服务层地基已完成",
        "Phase 2 记忆与 trace 收口已完成",
        "Phase 3 平台核心与控制平面服务边界已关闭",
        "Phase 4 控制台运行时与通道边界已关闭",
        "Phase 5 宽松治理架构基线已关闭",
        "可观测性产品化路线已关闭",
        "服务层负责真正做事",
        "rule/core 层负责规则和决策",
        "panel/API/channel 只做 adapter",
        "Feishu route_callback fallback 已删除",
        "兼容层只服务迁移和最终删除",
        "业务价值",
        "未来产品包",
        "当前不建议继续做",
        "验证证据",
        "下一步方向",
    ]

    for phrase in required_phrases:
        assert phrase in text


def test_refactor_evaluation_summary_preserves_deferred_boundaries():
    text = _summary_text()

    required_phrases = [
        "不做客户内容检查",
        "CPE 保持宽松",
        "AgentShield 保持宽松",
        "不做自进化",
        "不做 TemplateMarket",
        "不做 stream runtime replay",
        "不做 live SSE listener queue 持久化或恢复",
        "真实使用反馈",
    ]

    for phrase in required_phrases:
        assert phrase in text


def test_refactor_evaluation_summary_details_current_architecture_status():
    text = _summary_text()

    required_phrases = [
        "## AgentMind 详细架构现状",
        "1. 入口层与 adapter",
        "`src/agentmind/main.py`",
        "`src/agentmind/startup.py`",
        "`src/agentmind/api/router.py`",
        "`src/agentmind/panel/server.py`",
        "`src/agentmind/channels/hub.py`",
        "`src/agentmind/channels/feishu.py`",
        "2. 服务层现状",
        "`ConfigService`",
        "`TaskService`",
        "`RoutingService`",
        "`MemoryService`",
        "`SessionRuntimeService`",
        "`ChannelReplayService`",
        "`TaskReplayService`",
        "`AuditService`",
        "`ProtocolGateway`",
        "`StrategyManager`",
        "`AgentCapabilityRegistry`",
        "`OrchestrationEngine`",
        "3. rule/core 与治理层",
        "`src/agentmind/core/rule_engine.py`",
        "`src/agentmind/governance/cpe.py`",
        "`src/agentmind/governance/agent_shield.py`",
        "4. 基础设施与存储层",
        "`src/agentmind/storage/db.py`",
        "`src/agentmind/memory/sqlite_store.py`",
        "`src/agentmind/connectors/`",
        "`src/agentmind/agents/`",
        "5. 可观测性与 replay 现状",
        "`TaskEventService`",
        "`TaskTimelineService`",
        "6. 运行时状态边界",
        "`stream_snapshot`",
        "live SSE listener queues",
        "7. 当前架构约束",
    ]

    for phrase in required_phrases:
        assert phrase in text


def test_refactor_evaluation_summary_contains_readable_architecture_diagram():
    text = _summary_text()

    required_phrases = [
        "## AgentMind 当前架构图",
        "```mermaid",
        "flowchart TB",
        "用户与外部入口",
        "入口层 / Adapter",
        "应用服务层",
        "Rule/Core 与治理层",
        "基础设施与存储层",
        "可观测性 / Replay",
        "运行时状态边界",
        "Panel/API/Channel 只做 adapter",
        "服务层负责真正做事",
        "规则层负责规则和决策",
        "TaskEventService",
        "TaskTimelineService",
        "TaskReplayService",
        "ChannelReplayService",
        "SessionRuntimeService",
        "ConfigService",
        "RoutingService",
        "TaskService",
        "MemoryService",
        "ProtocolGateway",
        "CPE",
        "AgentShield",
        "SQLite / YAML / Connectors / Agents",
        "live SSE listener queues 不持久化",
    ]

    for phrase in required_phrases:
        assert phrase in text
