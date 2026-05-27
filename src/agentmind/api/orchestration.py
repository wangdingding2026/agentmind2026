"""DAG 可视化编排 — 专用执行端点"""

import json
import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse

from agentmind.orchestration.engine import OrchestrationEngine
from agentmind.services.orchestration_service import OrchestrationService
from agentmind.storage.db import CONFIG_DIR
from agentmind.memory.service import MemoryService

logger = logging.getLogger("agentmind")
router = APIRouter()

# ========== 模型 ==========

from agentmind.api.models import OrchestrationStep, OrchestrationPlan  # noqa: E402 — 实际定义在 models.py


# ========== 拓扑验证与排序 ==========

_DEFAULT_ENGINE = OrchestrationEngine()


def validate_dag(steps: list[OrchestrationStep]):
    return _DEFAULT_ENGINE.validate_dag(steps)


def topological_sort(steps: list[OrchestrationStep]) -> list[OrchestrationStep]:
    return _DEFAULT_ENGINE.topological_sort(steps)


# ========== 上下文注入 ==========

def build_contextual_instruction(step: OrchestrationStep, previous_results: dict[int, str]) -> str:
    return _DEFAULT_ENGINE.build_contextual_instruction(step, previous_results)


# ========== 步骤记忆写入 ==========

async def _write_step_memory(step: OrchestrationStep, plan_id: str, result: str):
    try:
        await MemoryService().write_memory({
            "memory_id": f"dag-{plan_id}-step{step.step_id}",
            "content": result,
            "summary": f"[DAG:{plan_id}/step{step.step_id}] {result[:200]}",
            "source_agent": step.agent_id,
            "source_task_id": plan_id,
            "tags": [f"dag:{plan_id}", f"agent:{step.agent_id}"],
        })
    except Exception:
        pass


# ========== 编排计划管理 ==========

ORCHESTRATIONS_PATH = CONFIG_DIR / "orchestrations.yaml"


def _orchestration_service() -> OrchestrationService:
    return OrchestrationService(CONFIG_DIR)


def _load_orchestrations() -> list[dict]:
    return _orchestration_service().list_plans()


def _save_orchestrations(plans: list[dict]):
    _orchestration_service().replace_plans(plans)


@router.post("/orchestrations/save")
async def save_orchestration(request: Request):
    body = await request.json()
    plan_id = body.get("plan_id", "")
    name = body.get("name", "未命名")
    trigger_words = body.get("trigger_words", [])
    steps = body.get("steps", [])

    _orchestration_service().save_plan(plan_id, name, trigger_words, steps)
    return {"ok": True, "plan_id": plan_id}


@router.get("/orchestrations/list")
async def list_orchestrations():
    return {"plans": _load_orchestrations()}


@router.delete("/orchestrations/{plan_id}")
async def delete_orchestration(plan_id: str):
    return _orchestration_service().delete_plan(plan_id)


def _increment_orchestration_usage(plan_id: str):
    _orchestration_service().increment_usage(plan_id)


# ========== 执行端点 ==========

@router.post("/orchestration/execute")
async def execute_dag_plan(plan: OrchestrationPlan, request: Request):
    agent_registry = request.app.state.agent_registry

    try:
        validate_dag(plan.steps)
    except ValueError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})

    async def event_generator():
        async for event in _DEFAULT_ENGINE.execute_events(plan, agent_registry, _write_step_memory):
            yield {"event": event["event"], "data": json.dumps(event["data"])}

    return EventSourceResponse(event_generator())
