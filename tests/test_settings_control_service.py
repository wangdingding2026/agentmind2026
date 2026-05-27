class _ConfigService:
    def __init__(self):
        self.calls = []

    def update_settings_sections(self, sections):
        self.calls.append(sections)
        return sections


def test_settings_control_service_saves_allowed_settings_sections():
    from agentmind.services.settings_control_service import SettingsControlService

    config_service = _ConfigService()
    result = SettingsControlService(config_service=config_service).save_settings({
        "memory": {"max_entries": 100},
        "embedding": {"enabled": True},
        "semantic_router": {"enabled": False},
        "history": {"retention_days": 7},
        "meta": {"model": "local"},
        "ignored": {"value": "skip"},
    })

    assert result == {"ok": True}
    assert config_service.calls == [{
        "memory": {"max_entries": 100},
        "embedding": {"enabled": True},
        "semantic_router": {"enabled": False},
        "history": {"retention_days": 7},
        "core_llm": {"model": "local"},
    }]


def test_settings_control_service_saves_feishu_config_section():
    from agentmind.services.settings_control_service import SettingsControlService

    config_service = _ConfigService()
    result = SettingsControlService(config_service=config_service).save_feishu_config({
        "enabled": True,
        "app_id": "cli_a",
        "app_secret": "secret",
        "ignored": "skip",
    })

    assert result == {"ok": True}
    assert config_service.calls == [{
        "feishu": {
            "enabled": True,
            "app_id": "cli_a",
            "app_secret": "secret",
        }
    }]
