class _ConfigService:
    def __init__(self, settings):
        self.settings = settings
        self.calls = 0

    def read_settings(self):
        self.calls += 1
        return self.settings


def test_settings_status_service_builds_settings_view():
    from agentmind.services.settings_status_service import SettingsStatusService

    config_service = _ConfigService({
        "memory": {"enabled": True},
        "embedding": {"enabled": False},
        "semantic_router": {"enabled": True},
        "history": {"max_turns": 8},
        "core_llm": {"model": "local"},
        "ignored": {"value": "skip"},
    })

    result = SettingsStatusService(config_service=config_service).get_settings_view()

    assert result == {
        "memory": {"enabled": True},
        "embedding": {"enabled": False},
        "semantic_router": {"enabled": True},
        "history": {"max_turns": 8},
        "meta": {"model": "local"},
    }
    assert config_service.calls == 1


def test_settings_status_service_builds_feishu_config_defaults():
    from agentmind.services.settings_status_service import SettingsStatusService

    result = SettingsStatusService(
        config_service=_ConfigService({})
    ).get_feishu_config_view()

    assert result == {"app_id": "", "app_secret": "", "enabled": False}


def test_settings_status_service_builds_embedding_status_with_external_and_local_sources():
    from agentmind.services.settings_status_service import SettingsStatusService

    config_service = _ConfigService({
        "embedding": {
            "enabled": True,
            "endpoint": "https://api.example.com/embeddings",
            "dimension": 768,
        }
    })

    result = SettingsStatusService(
        config_service=config_service,
        local_embedding_probe=lambda: True,
    ).get_embedding_status()

    assert result == {
        "enabled": True,
        "has_external_api": True,
        "has_local_model": True,
        "dimension": 768,
        "summary": "外部 API 已配置 + 本地模型已安装",
    }


def test_settings_status_service_treats_local_probe_failure_as_no_local_model():
    from agentmind.services.settings_status_service import SettingsStatusService

    def failing_probe():
        raise RuntimeError("probe failed")

    result = SettingsStatusService(
        config_service=_ConfigService({"embedding": {"enabled": True, "endpoint": ""}}),
        local_embedding_probe=failing_probe,
    ).get_embedding_status()

    assert result == {
        "enabled": True,
        "has_external_api": False,
        "has_local_model": False,
        "dimension": 384,
        "summary": "未配置",
    }
