"""ConversationHistoryExecutor — 历史查询专用执行器。

当 semantic_intent.intent == conversation_history 时使用。
根据 SemanticIntent 的 time_scope / current_session / explicit_date 决定查询范围，
通过 read_conversation_turns 读取结构化问答轮次，输出统一的 问：/答： 格式。
"""
import logging
import re as _re

from agentmind.routing.context import RoutingDecision
from agentmind.routing.executors.base import ExecutorBase
from agentmind.services.time_service import local_date_key, local_day_bounds, to_local_display

logger = logging.getLogger("agentmind")


class ConversationHistoryExecutor(ExecutorBase):
    """历史查询执行器：输出结构化 Q&A，不输出话题索引。"""

    async def run_json(self, decision: RoutingDecision, trace_id: str, user_id: str):
        from fastapi.responses import JSONResponse

        reply = await self.build_reply(decision, user_id)
        from agentmind.storage.db import record_task_update
        await record_task_update(trace_id, status="executing", routed_agent="agentmind")
        await self._record_success(trace_id, "agentmind", decision.context.raw_message, reply, user_id, source_kind="conversation_history_answer")

        return JSONResponse(content={
            "agent_id": "agentmind",
            "result": reply,
            "trace_id": trace_id,
            "status": "completed",
        })

    async def run_stream(self, decision: RoutingDecision, trace_id: str, user_id: str):
        import json as _json
        from agentmind.services.task_service import TaskService
        from agentmind.storage.db import record_task_update

        reply = await self.build_reply(decision, user_id)
        await record_task_update(trace_id, status="executing", routed_agent="agentmind")

        yield {"event": "status", "data": _json.dumps({
            "status": "routed", "agent_id": "agentmind",
            "matched_rule": decision.strategy, "trace_id": trace_id,
        })}
        yield {"event": "status", "data": _json.dumps({
            "status": "executing", "agent_id": "agentmind", "trace_id": trace_id,
        })}

        await TaskService().record_partial_output(trace_id, agent_id="agentmind", content=reply, chunk_index=1)

        yield {"event": "partial", "data": _json.dumps({"content": reply, "trace_id": trace_id})}
        yield {"event": "status", "data": _json.dumps({
            "status": "completed", "trace_id": trace_id, "execution_time_ms": 0,
        })}

        await self._record_success(trace_id, "agentmind", decision.context.raw_message, reply, user_id, source_kind="conversation_history_answer")

    async def run_text(self, decision: RoutingDecision, trace_id: str, user_id: str):
        from agentmind.services.task_service import TaskService
        from agentmind.storage.db import record_task_update

        reply = await self.build_reply(decision, user_id)
        await record_task_update(trace_id, status="executing", routed_agent="agentmind")

        await TaskService().record_partial_output(trace_id, agent_id="agentmind", content=reply, chunk_index=1)
        yield reply
        await self._record_success(trace_id, "agentmind", decision.context.raw_message, reply, user_id, source_kind="conversation_history_answer")

    # ── 核心逻辑 ──

    async def build_reply(self, decision: RoutingDecision, user_id: str = "") -> str:
        intent = decision.semantic_intent if decision.semantic_intent else None
        if not intent:
            return self._format_no_records("")

        time_scope = intent.time_scope

        # 当前 session：优先 Working Memory，再回退 read_conversation_turns
        if intent.current_session or time_scope == "current_session":
            return await self._reply_current_session(decision, user_id)

        # 今天/昨天/指定日期/其他：用 read_conversation_turns
        return await self._reply_from_turns(decision, user_id, time_scope)

    async def _reply_current_session(self, decision: RoutingDecision, user_id: str) -> str:
        uid = user_id or (decision.context.identity.user_id if decision.context else "")
        if uid:
            try:
                from agentmind.memory.service import MemoryService
                svc = MemoryService()
                rounds = svc.get_working_memory(uid, limit=20)
                if rounds:
                    return self._format_qa_from_wm(rounds, "当前会话的对话记录")

                # Working Memory 空，尝试用 conversation_id 查 turns
                conv_id = svc.get_active_conversation_id(uid) or ""
                if conv_id:
                    turns = await svc.read_conversation_turns(
                        user_id=uid,
                        conversation_id=conv_id,
                    )
                    if turns:
                        return self._format_qa_from_turns(turns, "当前会话的对话记录")
            except Exception:
                pass

        # 最后回退到 memories
        memories = decision.context.memories if decision.context else []
        if memories:
            return self._format_qa_from_memories(memories, "当前会话的对话记录")
        return "当前会话还没有任何对话记录。"

    async def _reply_from_turns(self, decision: RoutingDecision, user_id: str, time_scope: str) -> str:
        uid = user_id or (decision.context.identity.user_id if decision.context else "")
        label = self._scope_label(decision, time_scope)

        if not uid:
            memories = decision.context.memories if decision.context else []
            if memories:
                return self._format_qa_from_memories(memories, label)
            return f"没有找到{label}。"

        # 计算时间范围
        time_range_start, time_range_end = self._time_bounds(decision, time_scope)

        try:
            from agentmind.memory.service import MemoryService
            turns = await MemoryService().read_conversation_turns(
                user_id=uid,
                time_range_start=time_range_start,
                time_range_end=time_range_end,
            )
            if turns:
                return self._format_qa_from_turns(turns, label)
        except Exception:
            pass

        # 回退到 memories
        memories = decision.context.memories if decision.context else []
        if memories:
            return self._format_qa_from_memories(memories, label)
        return f"没有找到{label}。"

    # ── 时间范围 ──

    @staticmethod
    def _scope_label(decision: RoutingDecision, time_scope: str) -> str:
        if time_scope == "today":
            return "今天的对话记录"
        if time_scope == "yesterday":
            return "昨天的对话记录"
        if time_scope == "explicit_date":
            date_str = (decision.semantic_intent.explicit_date or "") if decision.semantic_intent else ""
            return f"{date_str} 的对话记录" if date_str else "对话记录"
        return "对话记录"

    @staticmethod
    def _time_bounds(decision: RoutingDecision, time_scope: str) -> tuple[str, str]:
        if time_scope == "today":
            return local_day_bounds("today")
        if time_scope == "yesterday":
            return local_day_bounds("yesterday")
        if time_scope == "explicit_date" and decision.semantic_intent:
            date_str = decision.semantic_intent.explicit_date or ""
            if date_str:
                try:
                    from datetime import datetime, time as dt_time
                    from zoneinfo import ZoneInfo
                    from agentmind.services.time_service import DEFAULT_TIMEZONE
                    tz = ZoneInfo(DEFAULT_TIMEZONE)
                    target = datetime.strptime(date_str[:10], "%Y-%m-%d").date()
                    start = datetime.combine(target, dt_time.min, tzinfo=tz)
                    end = datetime.combine(target, dt_time.max, tzinfo=tz).replace(microsecond=0)
                    return (
                        start.astimezone(tz=None).strftime("%Y-%m-%d %H:%M:%S"),
                        end.astimezone(tz=None).strftime("%Y-%m-%d %H:%M:%S"),
                    )
                except (ValueError, TypeError):
                    pass
        return "", ""

    # ── 格式化 ──

    def _format_qa_from_wm(self, rounds: list[dict], header: str) -> str:
        """从 Working Memory rounds 格式化 Q&A。"""
        lines = [f"{header}："]
        for i, r in enumerate(rounds, 1):
            user_msg = (r.get("user") or "").strip()
            assistant_msg = (r.get("assistant") or "").strip()
            ts = to_local_display(r.get("ts") or "")
            lines.append(f"\n{i}. {ts}")
            lines.append(f"   问：{user_msg}")
            if assistant_msg:
                lines.append(f"   答：{assistant_msg}")
        return "\n".join(lines)

    def _format_qa_from_turns(self, turns: list[dict], header: str) -> str:
        """从 read_conversation_turns 结构化轮次格式化 Q&A。"""
        agents = list(dict.fromkeys(
            t.get("source_agent", "") for t in turns if t.get("source_agent")
        ))

        lines = [f"{header}："]
        if agents:
            lines.append(f"涉及 Agent：{', '.join(agents)}")

        for i, t in enumerate(turns, 1):
            question = (t.get("question") or "").strip()
            answer = (t.get("answer") or "").strip()
            agent = t.get("source_agent", "")
            ts = to_local_display(t.get("created_at") or "")

            lines.append(f"\n{i}. {ts} [{agent}]")
            lines.append(f"   问：{question}")
            if answer:
                lines.append(f"   答：{answer}")

        return "\n".join(lines)

    def _format_qa_from_memories(self, memories: list[dict], header: str) -> str:
        """从 memories 列表格式化 Q&A（回退路径）。"""
        agents = list(dict.fromkeys(
            m.get("source_agent", "") for m in memories if m.get("source_agent")
        ))

        lines = [f"{header}："]
        if agents:
            lines.append(f"涉及 Agent：{', '.join(agents)}")

        for i, m in enumerate(memories, 1):
            content = (m.get("content") or "").strip()
            summary = (m.get("summary") or "").strip()
            agent = m.get("source_agent", "")
            ts = to_local_display(m.get("created_at") or "")

            answer = _re.sub(r'^\[[^\]]+\]\s*', '', summary)

            lines.append(f"\n{i}. {ts} [{agent}]")
            lines.append(f"   问：{content}")
            if answer:
                lines.append(f"   答：{answer}")

        return "\n".join(lines)

    @staticmethod
    def _format_no_records(scope: str) -> str:
        if scope:
            return f"没有找到{scope}的对话记录。"
        return "没有找到对话记录。"
