from __future__ import annotations

from pathlib import Path
from typing import Any

from agentmind.services.config_service import ConfigService


class SettingsControlService:
    """Manage control-plane settings update payloads."""

    def __init__(
        self,
        *,
        config_service: ConfigService | None = None,
        config_dir: Path | None = None,
    ):
        self._config_service = config_service or ConfigService(config_dir)

    def save_settings(self, body: dict[str, Any]) -> dict[str, bool]:
        sections = {}
        for key in ["memory", "embedding", "semantic_router", "history"]:
            if key in body:
                sections[key] = body[key]
        if "meta" in body:
            sections["core_llm"] = body["meta"]
        self._config_service.update_settings_sections(sections)
        return {"ok": True}

    def save_feishu_config(self, body: dict[str, Any]) -> dict[str, bool]:
        self._config_service.update_settings_sections({
            "feishu": {
                "enabled": body.get("enabled", False),
                "app_id": body.get("app_id", ""),
                "app_secret": body.get("app_secret", ""),
            }
        })
        return {"ok": True}
