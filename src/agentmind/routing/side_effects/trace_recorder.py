"""决策链路追踪适配器。"""

import logging

from agentmind.services.audit_service import AuditService
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
        try:
            context = decision.context
            await AuditService().record_routing_decision(
                trace_id=trace_id,
                agent_id=decision.agent_id or "",
                strategy=decision.strategy or "",
                confidence=float(decision.confidence or 0.0),
                actor="system",
                user_id=user_id,
                risk_level="medium" if context and context.security_flagged else "low",
                payload={
                    "fallback_chain": decision.fallback_chain,
                    "reply_text": decision.reply_text[:200] if decision.reply_text else "",
                    "raw_message": context.raw_message[:500] if context else "",
                    "candidates": context.candidates if context else [],
                    "security_flagged": context.security_flagged if context else False,
                },
            )
        except Exception:
            logger.debug("记录 routing audit 失败", exc_info=True)

    @staticmethod
    async def get_trace(trace_id: str) -> dict | None:
        try:
            return await TraceService().get_trace(trace_id)
        except Exception:
            logger.debug("查询 routing trace 失败", exc_info=True)
            return None
