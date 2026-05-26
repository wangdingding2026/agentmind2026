from fastapi import APIRouter, HTTPException, Request

from agentmind.agents.discovery import discover_and_generate

router = APIRouter()


@router.get("/agents/status")
async def get_agents_status(request: Request):
    registry = request.app.state.agent_registry
    return registry.get_all_status()


@router.post("/agents/{agent_id}/health-check")
async def trigger_health_check(agent_id: str, request: Request):
    registry = request.app.state.agent_registry
    executor = registry.get_executor(agent_id)
    if executor is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    await executor.health_check()
    return {"agent_id": agent_id, "healthy": executor.is_healthy}


@router.post("/agents/scan")
async def scan_agents(request: Request):
    """手动触发 Agent 扫描，发现新安装的 Agent 并重新加载所有组件"""
    agents_path = request.app.state.agents_config_path
    registry = request.app.state.agent_registry
    rule_engine = request.app.state.rule_engine

    # 扫描并合并到配置
    await discover_and_generate(agents_path)

    # 重新加载 Agent 注册表
    await registry.reload(agents_path)
    await registry.run_health_checks()

    # 重新加载路由规则（根据新 Agent 的 tags 重新解析 target_agent）
    await rule_engine.reload()

    return {
        "ok": True,
        "agents": registry.get_all_status(),
    }
