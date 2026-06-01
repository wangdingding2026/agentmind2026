import yaml

from agentmind.services.config_service import ConfigService


def test_read_missing_config_returns_empty_dict(tmp_path):
    service = ConfigService(tmp_path / "config")

    assert service.read_settings() == {}
    assert service.read_agents() == {"agents": []}
    assert service.read_routes() == {"rules": []}
    assert service.read_orchestrations() == {"plans": []}


def test_update_settings_section_preserves_other_sections(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    settings_path = config_dir / "settings.yaml"
    settings_path.write_text(
        yaml.dump({
            "memory": {"max_entries": 100},
            "embedding": {"enabled": False},
        }),
        encoding="utf-8",
    )
    service = ConfigService(config_dir)

    saved = service.update_settings_sections({
        "memory": {"max_entries": 500},
    })

    assert saved["memory"]["max_entries"] == 500
    assert saved["embedding"]["enabled"] is False
    assert yaml.safe_load(settings_path.read_text(encoding="utf-8")) == saved


def test_write_routes_rejects_non_list_rules(tmp_path):
    service = ConfigService(tmp_path / "config")

    try:
        service.write_routes({"rules": "not-a-list"})
    except ValueError as exc:
        assert "rules must be a list" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_mask_sensitive_config_values(tmp_path):
    service = ConfigService(tmp_path / "config")

    masked = service.mask_sensitive({
        "api_key": "sk-test",
        "nested": {"app_secret": "secret", "safe": "value"},
        "items": [{"token": "abc"}],
    })

    assert masked["api_key"] == "****"
    assert masked["nested"]["app_secret"] == "****"
    assert masked["nested"]["safe"] == "value"
    assert masked["items"][0]["token"] == "****"


def test_config_service_audits_settings_updates_with_masked_payload(tmp_path):
    calls = []

    class FakeAuditService:
        def _record_event_sync(self, **kwargs):
            calls.append(kwargs)
            return "audit-1"

    service = ConfigService(tmp_path / "config", audit_service=FakeAuditService())

    service.update_settings_sections({
        "feishu": {"app_id": "app", "app_secret": "secret"},
    })

    assert calls == [{
        "module": "config",
        "action": "update",
        "actor": "system",
        "risk_level": "medium",
        "status": "success",
        "message": "config update: settings",
        "payload": {
            "area": "settings",
            "changed_keys": ["feishu"],
            "data": {"feishu": {"app_id": "app", "app_secret": "****"}},
        },
    }]


def test_config_service_audits_only_changed_settings_sections(tmp_path):
    calls = []

    class FakeAuditService:
        def _record_event_sync(self, **kwargs):
            calls.append(kwargs)
            return "audit-1"

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "settings.yaml").write_text(
        yaml.dump({
            "feishu": {"enabled": True, "app_id": "cli", "app_secret": "secret"},
            "embedding": {"enabled": False},
        }),
        encoding="utf-8",
    )
    service = ConfigService(config_dir, audit_service=FakeAuditService())

    service.update_settings_sections({"embedding": {"enabled": True}})

    assert calls[0]["payload"] == {
        "area": "settings",
        "changed_keys": ["embedding"],
        "data": {"embedding": {"enabled": True}},
    }


def test_config_service_audits_route_writes(tmp_path):
    calls = []

    class FakeAuditService:
        def _record_event_sync(self, **kwargs):
            calls.append(kwargs)
            return "audit-1"

    service = ConfigService(tmp_path / "config", audit_service=FakeAuditService())

    service.write_routes({"rules": [{"name": "r1"}]})

    assert calls[0]["module"] == "config"
    assert calls[0]["action"] == "update"
    assert calls[0]["message"] == "config update: routes"
    assert calls[0]["payload"] == {
        "area": "routes",
        "changed_keys": ["rules"],
        "data": {"rules": [{"name": "r1"}]},
    }


def test_config_service_audit_failure_does_not_prevent_write(tmp_path):
    class FailingAuditService:
        def _record_event_sync(self, **kwargs):
            raise RuntimeError("audit unavailable")

    config_dir = tmp_path / "config"
    service = ConfigService(config_dir, audit_service=FailingAuditService())

    saved = service.write_agents({"agents": [{"id": "a1"}]})

    assert saved == {"agents": [{"id": "a1"}]}
    assert yaml.safe_load((config_dir / "agents.yaml").read_text(encoding="utf-8")) == saved
