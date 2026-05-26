from pydantic import BaseModel, Field
from typing import Optional


class RouteRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=10000, description="用户指令")
    caller: Optional[str] = Field(None, description="调用方标识，如 'feishu', 'terminal'")
    user_id: Optional[str] = Field(None, description="用户ID，为多用户预留")
    session_id: Optional[str] = Field(None, description="会话ID，为上下文连续性预留")
    priority: Optional[int] = Field(0, ge=0, le=10, description="优先级，0最低")
    tags: Optional[list[str]] = Field(None, description="自定义标签")
    is_retry: bool = Field(False, description="是否为崩溃恢复重试，v2.0")
    stream: bool = Field(True, description="是否流式返回，默认true")


class RouteResponse(BaseModel):
    """非流式模式下的成功响应模型"""
    trace_id: str
    agent_id: str
    matched_rule: str
    confidence: float
    result: str
    execution_time_ms: int


class RouteErrorResponse(BaseModel):
    """非流式模式下的错误响应模型"""
    trace_id: str
    agent_id: str
    matched_rule: str
    error: str
    execution_time_ms: int


# v3.0 DAG 编排模型

class OrchestrationStep(BaseModel):
    plan_id: str = ""
    step_id: int
    agent_id: str
    instruction: str
    depends_on: list[int] = []


class OrchestrationPlan(BaseModel):
    plan_id: str
    steps: list[OrchestrationStep]
    stream: bool = True



