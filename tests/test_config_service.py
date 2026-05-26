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
