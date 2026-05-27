from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any

from agentmind.services.config_service import ConfigService


class RuleControlService:
    """Manage route-rule configuration for the control plane."""

    def __init__(
        self,
        *,
        config_service: ConfigService | None = None,
        rule_engine=None,
        config_dir: Path | None = None,
    ):
        self._config_service = config_service or ConfigService(config_dir)
        self._rule_engine = rule_engine

    def list_rules(self) -> list[dict[str, Any]]:
        data = self._config_service.read_routes()
        rules = data.get("rules", []) if isinstance(data, dict) else []
        return rules if isinstance(rules, list) else []

    async def save_rule(self, rule_input: dict[str, Any]) -> dict[str, Any]:
        name = str(rule_input.get("name", "")).strip()
        rule = {
            "name": name,
            "type": rule_input.get("type", "keyword"),
            "patterns": rule_input.get("patterns", []),
            "target_tags": rule_input.get("target_tags", []),
            "priority": rule_input.get("priority", 10),
            "tags": rule_input.get("tags", []),
        }
        data = self._config_service.read_routes()
        rules = data.get("rules", []) if isinstance(data, dict) else []
        if not isinstance(rules, list):
            rules = []
        exist_idx = next(
            (i for i, item in enumerate(rules) if isinstance(item, dict) and item.get("name") == name),
            None,
        )
        if exist_idx is not None:
            rules[exist_idx] = rule
        else:
            rules.append(rule)
        data["rules"] = rules
        self._config_service.write_routes(data)
        await self._reload_rule_engine()
        return {"ok": True, "name": name}

    async def delete_rule(self, name: str) -> dict[str, Any]:
        data = self._config_service.read_routes()
        if isinstance(data, dict):
            data["rules"] = [
                rule
                for rule in data.get("rules", [])
                if isinstance(rule, dict) and rule.get("name") != name
            ]
            self._config_service.write_routes(data)
        await self._reload_rule_engine()
        return {"ok": True}

    async def _reload_rule_engine(self) -> None:
        if self._rule_engine is None:
            return
        result = self._rule_engine.reload()
        if inspect.isawaitable(result):
            await result
