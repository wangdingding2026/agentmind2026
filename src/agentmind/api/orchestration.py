"""DAG 可视化编排 — 专用执行端点"""

import json
import logging
from collections import defaultdict, deque

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse

from agentmind.storage.db import CONFIG_DIR
from agentmind.memory.service import MemoryService

logger = logging.getLogger("agentmind")
router = APIRouter()

# ========== 模型 ==========

from agentmind.api.models import OrchestrationStep, OrchestrationPlan  # noqa: E402 — 实际定义在 models.py


# ========== 拓扑验证与排序 ==========

def validate_dag(steps: list[OrchestrationStep]):
    """DFS 检测循环依赖，存在则抛出 ValueError"""
    visited: set[int] = set()
    rec_stack: set[int] = set()
    step_map = {s.step_id: s for s in steps}

    def dfs(step_id: int):
        if step_id in rec_stack:
            raise ValueError(f"检测到循环依赖，涉及步骤 {step_id}")
        if step_id in visited:
            return
        visited.add(step_id)
        rec_stack.add(step_id)
        step = step_map.get(step_id)
        if step:
            for dep in step.depends_on:
                dfs(dep)
        rec_stack.discard(step_id)

    for s in steps:
        dfs(s.step_id)


def topological_sort(steps: list[OrchestrationStep]) -> list[OrchestrationStep]:
    """Kahn 算法拓扑排序，返回可顺序执行的步骤列表"""
    in_degree: dict[int, int] = defaultdict(int)
    children: dict[int, list[int]] = defaultdict(list)
    step_map = {s.step_id: s for s in steps}

    for s in steps:
        for dep in s.depends_on:
            in_degree[s.step_id] += 1
            children[dep].append(s.step_id)

    queue = deque([s.step_id for s in steps if in_degree[s.step_id] == 0])
    sorted_steps: list[OrchestrationStep] = []

    while queue:
        sid = queue.popleft()
        step = step_map[sid]
        sorted_steps.append(step)
        for child in children[sid]:
            in_degree[child] -= 1
            if in_degree[child] == 0:
                queue.append(child)

    if len(sorted_steps) != len(steps):
        raise ValueError("拓扑排序失败，可能存在循环依赖")
    return sorted_steps


# ========== 上下文注入 ==========

def build_contextual_instruction(step: OrchestrationStep, previous_results: dict[int, str]) -> str:
    """将前置步骤结果注入当前步骤的 Prompt"""
    if not step.depends_on:
        return step.instruction

    parts = []
    for dep_id in step.depends_on:
        if dep_id in previous_results:
            parts.append(f"前置步骤 {dep_id} 的输出：\n{previous_results[dep_id]}")

    if not parts:
        return step.instruction

    injected = "\n\n".join(parts)
    return (
        f"[系统注入：前置依赖的执行结果摘要]\n"
        f"{injected}\n\n"
        f"（注意：以上内容可能被截断，如需完整细节请通过记忆检索获取）\n\n"
        f"请基于以上前置结果，执行当前任务：\n"
        f"{step.instruction}"
    )


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


def _load_orchestrations() -> list[dict]:
    import yaml as _yaml
    if not ORCHESTRATIONS_PATH.exists():
        return []
    try:
        data = _yaml.safe_load(ORCHESTRATIONS_PATH.read_text(encoding="utf-8")) or {}
        return data.get("plans", []) if isinstance(data, dict) else []
    except Exception:
        return []


def _save_orchestrations(plans: list[dict]):
    import yaml as _yaml
    ORCHESTRATIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    ORCHESTRATIONS_PATH.write_text(
        _yaml.dump({"plans": plans}, allow_unicode=True, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )


@router.post("/orchestrations/save")
async def save_orchestration(request: Request):
    body = await request.json()
    plan_id = body.get("plan_id", "")
    name = body.get("name", "未命名")
    trigger_words = body.get("trigger_words", [])
    steps = body.get("steps", [])

    plans = _load_orchestrations()
    exist_idx = next((i for i, p in enumerate(plans) if p.get("plan_id") == plan_id), None)
    old_count = plans[exist_idx].get("usage_count", 0) if exist_idx is not None else 0
    entry = {"plan_id": plan_id, "name": name, "trigger_words": trigger_words, "steps": steps, "usage_count": old_count}
    if exist_idx is not None:
        plans[exist_idx] = entry
    else:
        plans.append(entry)
    _save_orchestrations(plans)
    return {"ok": True, "plan_id": plan_id}


@router.get("/orchestrations/list")
async def list_orchestrations():
    return {"plans": _load_orchestrations()}


@router.delete("/orchestrations/{plan_id}")
async def delete_orchestration(plan_id: str):
    plans = [p for p in _load_orchestrations() if p.get("plan_id") != plan_id]
    _save_orchestrations(plans)
    return {"ok": True}


def _increment_orchestration_usage(plan_id: str):
    plans = _load_orchestrations()
    for p in plans:
        if p.get("plan_id") == plan_id:
            p["usage_count"] = p.get("usage_count", 0) + 1
            break
    _save_orchestrations(plans)


# ========== 执行端点 ==========

@router.post("/orchestration/execute")
async def execute_dag_plan(plan: OrchestrationPlan, request: Request):
    agent_registry = request.app.state.agent_registry

    # 1. 拓扑验证
    try:
        validate_dag(plan.steps)
    except ValueError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})

    # 2. 拓扑排序
    try:
        sorted_steps = topological_sort(plan.steps)
    except ValueError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})

    async def event_generator():
        step_results: dict[int, str] = {}
        step_outputs: dict[int, str] = {}

        for step in sorted_steps:
            yield {"event": "node_status", "data": json.dumps({
                "step_id": step.step_id, "status": "executing",
            })}

            executor = agent_registry.get_executor(step.agent_id)
            if executor is None:
                yield {"event": "node_status", "data": json.dumps({
                    "step_id": step.step_id, "status": "failed",
                    "error": f"Agent {step.agent_id} 不可用",
                })}
                continue

            enriched = build_contextual_instruction(step, step_results)

            full_output = []
            try:
                async for event in executor.execute_stream(enriched):
                    if event.type.value == "content":
                        yield {"event": "partial", "data": json.dumps({
                            "step_id": step.step_id, "content": event.text,
                        })}
                        full_output.append(event.text)
                    elif event.type.value == "error":
                        yield {"event": "node_status", "data": json.dumps({
                            "step_id": step.step_id, "status": "failed",
                            "error": event.text,
                        })}
                        full_output = []
                        break
            except Exception as e:
                yield {"event": "node_status", "data": json.dumps({
                    "step_id": step.step_id, "status": "failed",
                    "error": str(e),
                })}
                continue

            if not full_output and step.step_id not in step_outputs:
                continue

            result = "".join(full_output)
            step_results[step.step_id] = result[:4000]
            step_outputs[step.step_id] = result

            await _write_step_memory(step, plan.plan_id, result)

            yield {"event": "node_status", "data": json.dumps({
                "step_id": step.step_id, "status": "completed",
            })}

        yield {"event": "status", "data": json.dumps({
            "status": "orchestration_complete", "plan_id": plan.plan_id,
        })}

    return EventSourceResponse(event_generator())
