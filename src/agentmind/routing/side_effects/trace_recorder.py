"""决策链路追踪适配器。"""

import logging

from agentmind.services.trace_service import TraceService

logger = logging.getLogger("agentmind")


class TraceRecorder:
    """L4 副作用：将路由决策写入 TraceService。"""

    @staticmethod
    async def record_decision(trace_id: str, decision, user_id: str = ""):
        try:
            await TraceService().record_decision(trace_id, decision, user_id)
        except Exception:
            logger.debug("记录 routing trace 失败", exc_info=True)

    @staticmethod
    async def get_trace(trace_id: str) -> dict | None:
        try:
            return await TraceService().get_trace(trace_id)
        except Exception:
            logger.debug("查询 routing trace 失败", exc_info=True)
            return None
