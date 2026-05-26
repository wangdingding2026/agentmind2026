"""决策链路追踪：记录和查询路由决策的结构化信息。"""

import json
import logging

from agentmind.routing.context import RoutingDecision
from agentmind.storage.memory import write_memory

logger = logging.getLogger("agentmind")


class TraceRecorder:
    """L4 副作用：将路由决策写入 memory.db，供面板查询。"""

    @staticmethod
    async def record_decision(trace_id: str, decision: RoutingDecision, user_id: str = ""):
        try:
            payload = {
                "agent_id": decision.agent_id,
                "strategy": decision.strategy,
                "confidence": decision.confidence,
                "fallback_chain": decision.fallback_chain,
                "reply_text": decision.reply_text[:200] if decision.reply_text else "",
                "raw_message": decision.context.raw_message[:500] if decision.context else "",
                "candidates": decision.context.candidates if decision.context else [],
                "security_flagged": decision.context.security_flagged if decision.context else False,
            }
            tags = ["routing_trace"]
            if user_id:
                tags.append(f"user:{user_id}")
            await write_memory({
                "memory_id": f"trace-{trace_id}",
                "content": json.dumps(payload, ensure_ascii=False),
                "summary": f"[{decision.strategy}] → {decision.agent_id} (conf={decision.confidence})",
                "source_agent": "agentmind",
                "source_task_id": trace_id,
                "tags": tags,
                "user_id": user_id,
                "access_level": "private",
            })
        except Exception:
            pass

    @staticmethod
    async def get_trace(trace_id: str) -> dict | None:
        try:
            from agentmind.storage.memory import _get_memory_conn
            import asyncio
            conn = await asyncio.to_thread(_get_memory_conn)
            try:
                row = conn.execute(
                    "SELECT * FROM memory_entries WHERE memory_id=? LIMIT 1",
                    (f"trace-{trace_id}",),
                ).fetchone()
                if row:
                    return dict(row)
            finally:
                conn.close()
        except Exception:
            pass
        return None
