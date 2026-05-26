class _Registry:
    executors = {}

    def get_executor(self, agent_id):
        return None


class _RuleEngine:
    async def match(self, message):
        return None


def test_strategy_manager_lists_core_and_auxiliary_strategies():
    from agentmind.services.strategy_manager import StrategyManager

    manager = StrategyManager(_Registry(), _RuleEngine())

    names = [item["name"] for item in manager.list_strategies()]
    core_names = [item["name"] for item in manager.list_strategies(kind="core")]
    auxiliary_names = [item["name"] for item in manager.list_strategies(kind="auxiliary")]

    assert core_names == ["explicit", "rule_engine", "llm_routing", "signal_scoring"]
    assert "memory_recall" in auxiliary_names
    assert names.index("memory_recall") < names.index("rule_engine")


def test_strategy_manager_can_disable_non_required_strategy():
    from agentmind.services.strategy_manager import StrategyManager

    manager = StrategyManager(_Registry(), _RuleEngine())

    assert manager.set_enabled("llm_routing", False)["enabled"] is False

    enabled_names = [strategy.name for strategy in manager.get_enabled_strategies({})]
    assert "llm_routing" not in enabled_names
    assert enabled_names[-1] == "signal_scoring"
