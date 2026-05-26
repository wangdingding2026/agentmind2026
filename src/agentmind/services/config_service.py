from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import yaml

from agentmind.storage.db import CONFIG_DIR


_SENSITIVE_KEYS = {"api_key", "token", "secret", "authorization", "password"}


class ConfigService:
    """Synchronous YAML configuration service.

    This first Phase 1 version intentionally stays small. It centralizes YAML
    reading, writing, validation, and masking without changing runtime behavior.
    """

    def __init__(self, config_dir: Path | None = None):
        self.config_dir = Path(config_dir) if config_dir is not None else CONFIG_DIR
        self._lock = threading.RLock()

    @property
    def settings_path(self) -> Path:
        return self.config_dir / "settings.yaml"

    @property
    def agents_path(self) -> Path:
        return self.config_dir / "agents.yaml"

    @property
    def routes_path(self) -> Path:
        return self.config_dir / "routes.yaml"

    @property
    def orchestrations_path(self) -> Path:
        return self.config_dir / "orchestrations.yaml"

    def read_settings(self) -> dict[str, Any]:
        return self._read_yaml(self.settings_path, {})

    def read_agents(self) -> dict[str, Any]:
        data = self._read_yaml(self.agents_path, {"agents": []})
        agents = data.get("agents", [])
        if not isinstance(agents, list):
            agents = []
        data["agents"] = agents
        return data

    def read_routes(self) -> dict[str, Any]:
        data = self._read_yaml(self.routes_path, {"rules": []})
        rules = data.get("rules", [])
        if not isinstance(rules, list):
            rules = []
        data["rules"] = rules
        return data

    def read_orchestrations(self) -> dict[str, Any]:
        data = self._read_yaml(self.orchestrations_path, {"plans": []})
        plans = data.get("plans", [])
        if not isinstance(plans, list):
            plans = []
        data["plans"] = plans
        return data

    def write_settings(self, data: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(data, dict):
            raise ValueError("settings must be a dict")
        return self._write_yaml(self.settings_path, data)

    def update_settings_sections(self, sections: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(sections, dict):
            raise ValueError("settings sections must be a dict")
        with self._lock:
            data = self.read_settings()
            data.update(sections)
            return self.write_settings(data)

    def write_agents(self, data: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(data, dict):
            raise ValueError("agents config must be a dict")
        agents = data.get("agents", [])
        if not isinstance(agents, list):
            raise ValueError("agents must be a list")
        return self._write_yaml(self.agents_path, data)

    def write_routes(self, data: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(data, dict):
            raise ValueError("routes config must be a dict")
        rules = data.get("rules", [])
        if not isinstance(rules, list):
            raise ValueError("rules must be a list")
        return self._write_yaml(self.routes_path, data)

    def write_orchestrations(self, data: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(data, dict):
            raise ValueError("orchestrations config must be a dict")
        plans = data.get("plans", [])
        if not isinstance(plans, list):
            raise ValueError("plans must be a list")
        return self._write_yaml(self.orchestrations_path, data)

    def mask_sensitive(self, value: Any) -> Any:
        if isinstance(value, dict):
            masked = {}
            for key, item in value.items():
                key_lower = str(key).lower()
                if key_lower in _SENSITIVE_KEYS or any(part in key_lower for part in _SENSITIVE_KEYS):
                    masked[key] = "****"
                else:
                    masked[key] = self.mask_sensitive(item)
            return masked
        if isinstance(value, list):
            return [self.mask_sensitive(item) for item in value]
        return value

    def _read_yaml(self, path: Path, default: dict[str, Any]) -> dict[str, Any]:
        if not path.exists():
            return dict(default)
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            raise ValueError(f"invalid YAML in {path.name}: {exc}") from exc
        if not isinstance(data, dict):
            return dict(default)
        return data

    def _write_yaml(self, path: Path, data: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                yaml.dump(data, allow_unicode=True, default_flow_style=False, sort_keys=False),
                encoding="utf-8",
            )
            return data
