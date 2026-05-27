from __future__ import annotations

from pathlib import Path
from typing import Any

from agentmind.services.config_service import ConfigService


class OrchestrationService:
    """Plan management and trigger matching for DAG orchestrations."""

    def __init__(self, config_dir: Path | None = None, config_service: ConfigService | None = None):
        self.config_service = config_service or ConfigService(config_dir)

    def list_plans(self) -> list[dict[str, Any]]:
        return list(self.config_service.read_orchestrations().get("plans", []))

    def replace_plans(self, plans: list[dict[str, Any]]) -> None:
        self.config_service.write_orchestrations({"plans": plans})

    def save_plan(
        self,
        plan_id: str,
        name: str,
        trigger_words: list[str],
        steps: list[dict[str, Any]],
    ) -> dict[str, Any]:
        plans = self.list_plans()
        existing_index = next((idx for idx, plan in enumerate(plans) if plan.get("plan_id") == plan_id), None)
        usage_count = plans[existing_index].get("usage_count", 0) if existing_index is not None else 0
        entry = {
            "plan_id": plan_id,
            "name": name,
            "trigger_words": trigger_words,
            "steps": steps,
            "usage_count": usage_count,
        }
        if existing_index is None:
            plans.append(entry)
        else:
            plans[existing_index] = entry
        self.config_service.write_orchestrations({"plans": plans})
        return entry

    def delete_plan(self, plan_id: str) -> dict[str, bool]:
        plans = [plan for plan in self.list_plans() if plan.get("plan_id") != plan_id]
        self.config_service.write_orchestrations({"plans": plans})
        return {"ok": True}

    def increment_usage(self, plan_id: str) -> None:
        plans = self.list_plans()
        for plan in plans:
            if plan.get("plan_id") == plan_id:
                plan["usage_count"] = plan.get("usage_count", 0) + 1
                break
        self.config_service.write_orchestrations({"plans": plans})

    def match_plan(self, message: str) -> dict[str, Any] | None:
        message_lower = message.lower()
        for plan in self.list_plans():
            for trigger_word in plan.get("trigger_words", []):
                if str(trigger_word).lower() in message_lower:
                    self.increment_usage(plan["plan_id"])
                    return plan
        return None
