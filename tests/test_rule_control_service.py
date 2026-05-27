import pytest


class _ConfigService:
    def __init__(self):
        self.data = {
            "rules": [
                {"name": "old", "type": "keyword", "patterns": ["old"]},
            ]
        }
        self.writes = []

    def read_routes(self):
        return self.data

    def write_routes(self, data):
        self.writes.append(data)
        self.data = data
        return data


class _RuleEngine:
    def __init__(self):
        self.reloads = 0

    async def reload(self):
        self.reloads += 1


def test_rule_control_service_lists_rules_from_config_service():
    from agentmind.services.rule_control_service import RuleControlService

    config_service = _ConfigService()

    assert RuleControlService(config_service=config_service).list_rules() == [
        {"name": "old", "type": "keyword", "patterns": ["old"]},
    ]


@pytest.mark.asyncio
async def test_rule_control_service_saves_rule_and_reloads_rule_engine():
    from agentmind.services.rule_control_service import RuleControlService

    config_service = _ConfigService()
    rule_engine = _RuleEngine()
    service = RuleControlService(config_service=config_service, rule_engine=rule_engine)

    result = await service.save_rule({
        "name": "new",
        "type": "regex",
        "patterns": ["hello"],
        "target_tags": ["general"],
        "priority": 20,
        "tags": ["demo"],
    })

    assert result == {"ok": True, "name": "new"}
    assert config_service.writes == [{
        "rules": [
            {"name": "old", "type": "keyword", "patterns": ["old"]},
            {
                "name": "new",
                "type": "regex",
                "patterns": ["hello"],
                "target_tags": ["general"],
                "priority": 20,
                "tags": ["demo"],
            },
        ]
    }]
    assert rule_engine.reloads == 1


@pytest.mark.asyncio
async def test_rule_control_service_deletes_rule_and_reloads_rule_engine():
    from agentmind.services.rule_control_service import RuleControlService

    config_service = _ConfigService()
    rule_engine = _RuleEngine()
    service = RuleControlService(config_service=config_service, rule_engine=rule_engine)

    result = await service.delete_rule("old")

    assert result == {"ok": True}
    assert config_service.writes == [{"rules": []}]
    assert rule_engine.reloads == 1
