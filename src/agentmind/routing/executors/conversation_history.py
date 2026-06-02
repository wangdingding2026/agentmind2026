"""ConversationHistoryExecutor — 历史查询专用执行器。

当 semantic_intent.intent == conversation_history 时使用。
根据 SemanticIntent 的 time_scope / current_session / explicit_date 决定查询范围，
通过 read_conversation_turns 读取结构化问答轮次，再交给 Core LLM 生成总结。
"""
import logging
import re as _re

from agentmind.core.core_llm import core_llm_chat
from agentmind.routing.context import RoutingDecision
from agentmind.routing.executors.base import ExecutorBase
from agentmind.services.time_service import local_date_key, local_day_bounds, to_local_display

logger = logging.getLogger("agentmind")


class ConversationHistoryExecutor(ExecutorBase):
    """历史查询执行器：基于真实历史材料生成自然语言总结。"""

    async def run_json(self, decision: RoutingDecision, trace_id: str, user_id: str):
        from fastapi.responses import JSONResponse

        reply = await self.build_reply(decision, user_id)
        from agentmind.storage.db import record_task_update
        await record_task_update(trace_id, status="executing", routed_agent="agentmind")
        await self._record_success(trace_id, "agentmind", decision.context.raw_message, reply, user_id)

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

        await self._record_success(trace_id, "agentmind", decision.context.raw_message, reply, user_id)

    async def run_text(self, decision: RoutingDecision, trace_id: str, user_id: str):
        from agentmind.services.task_service import TaskService
        from agentmind.storage.db import record_task_update

        reply = await self.build_reply(decision, user_id)
        await record_task_update(trace_id, status="executing", routed_agent="agentmind")

        await TaskService().record_partial_output(trace_id, agent_id="agentmind", content=reply, chunk_index=1)
        yield reply
        await self._record_success(trace_id, "agentmind", decision.context.raw_message, reply, user_id)

    # ── 核心逻辑 ──

    async def build_reply(self, decision: RoutingDecision, user_id: str = "") -> str:
        intent = decision.semantic_intent if decision.semantic_intent else None
        if not intent:
            return self._format_no_records("")

        time_scope = intent.time_scope

        # 当前 session：优先 canonical memory，Working Memory 只做兜底。
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
            except Exception:
                svc = None

            if svc is not None:
                try:
                    conv_id = svc.get_active_conversation_id(uid) or ""
                    if conv_id:
                        turns = await svc.read_conversation_turns(
                            user_id=uid,
                            conversation_id=conv_id,
                        )
                        if turns:
                            return await self._summarize_records(
                                decision,
                                self._records_from_turns(turns),
                                "当前会话的对话记录",
                            )
                except Exception:
                    pass

                try:
                    rounds = svc.get_working_memory(uid, limit=20)
                    if rounds:
                        records = self._records_from_wm(rounds)
                        return await self._summarize_records(
                            decision,
                            records,
                            "当前会话的对话记录",
                        )
                except Exception:
                    pass

        # 最后回退到 memories
        memories = decision.context.memories if decision.context else []
        if memories:
            return await self._summarize_records(
                decision,
                self._records_from_memories(memories),
                "当前会话的对话记录",
            )
        return "当前会话还没有任何对话记录。"

    async def _reply_from_turns(self, decision: RoutingDecision, user_id: str, time_scope: str) -> str:
        uid = user_id or (decision.context.identity.user_id if decision.context else "")
        label = self._scope_label(decision, time_scope)

        if not uid:
            memories = decision.context.memories if decision.context else []
            if memories:
                return await self._summarize_records(
                    decision,
                    self._records_from_memories(memories),
                    label,
                )
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
                return await self._summarize_records(
                    decision,
                    self._records_from_turns(turns),
                    label,
                )
        except Exception:
            pass

        # 回退到 memories
        memories = decision.context.memories if decision.context else []
        if memories:
            return await self._summarize_records(
                decision,
                self._records_from_memories(memories),
                label,
            )
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

    # ── 总结 ──

    async def _summarize_records(
        self,
        decision: RoutingDecision,
        records: list[dict],
        label: str,
    ) -> str:
        if not records:
            return f"没有找到{label}。"

        material = self._build_summary_material(records)
        messages = [
            {
                "role": "system",
                "content": (
                    "你是 AgentMind 的历史记录总结器。只能基于用户提供的历史记录材料总结，"
                    "不要编造材料外的信息。用户想知道聊过什么时，输出主题化总结，"
                    "不要机械罗列每一轮问答。需要保留涉及的 Agent 或说话来源。"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"用户问题：{decision.context.raw_message if decision.context else ''}\n"
                    f"查询范围：{label}\n\n"
                    f"历史记录材料：\n{material}\n\n"
                    "请用中文总结主要话题、关键结论和涉及的 Agent。"
                ),
            },
        ]
        try:
            reply = await core_llm_chat(messages, temperature=0.2)
            if reply and reply.strip():
                return reply.strip()
        except Exception:
            logger.debug("历史记录 LLM 总结失败", exc_info=True)
        return self._fallback_topic_summary(records, label)

    @staticmethod
    def _build_summary_material(records: list[dict]) -> str:
        lines = []
        for i, record in enumerate(records[:80], 1):
            ts = to_local_display(record.get("created_at") or "")
            agent = record.get("source_agent") or "unknown"
            source_kind = record.get("source_kind") or "conversation_turn"
            question = (record.get("question") or "").strip()
            answer = (record.get("answer") or "").strip()
            lines.append(
                f"{i}. 时间：{ts}\n"
                f"   来源：{agent}\n"
                f"   类型：{source_kind}\n"
                f"   用户/主题：{question}\n"
                f"   回复/内容：{answer}"
            )
        return "\n".join(lines)

    @staticmethod
    def _fallback_topic_summary(records: list[dict], label: str) -> str:
        agents = list(dict.fromkeys(
            r.get("source_agent", "") for r in records if r.get("source_agent")
        ))
        topics = []
        for record in records:
            question = (record.get("question") or "").strip()
            if question and question not in topics:
                topics.append(question)
            if len(topics) >= 5:
                break
        lines = [f"{label}摘要："]
        dates = list(dict.fromkeys(
            local_date_key(r.get("created_at") or "")
            for r in records
            if r.get("created_at")
        ))
        if dates:
            lines.append(f"涉及日期：{', '.join(dates[:3])}")
        if agents:
            lines.append(f"涉及 Agent：{', '.join(agents)}")
        if topics:
            lines.append("主要内容：")
            for i, topic in enumerate(topics, 1):
                lines.append(f"{i}. {topic}")
        return "\n".join(lines)

    # ── 结构化记录转换 ──

    def _records_from_wm(self, rounds: list[dict]) -> list[dict]:
        records = []
        for r in rounds:
            records.append({
                "created_at": r.get("ts") or "",
                "source_agent": "working_memory",
                "source_kind": "working_memory",
                "question": (r.get("user") or "").strip(),
                "answer": (r.get("assistant") or "").strip(),
            })
        return records

    def _records_from_turns(self, turns: list[dict]) -> list[dict]:
        return [
            {
                "created_at": t.get("created_at") or "",
                "source_agent": t.get("source_agent") or "",
                "source_kind": t.get("source_kind") or "conversation_turn",
                "question": (t.get("question") or "").strip(),
                "answer": (t.get("answer") or "").strip(),
            }
            for t in turns
        ]

    def _records_from_memories(self, memories: list[dict]) -> list[dict]:
        records = []
        for m in memories:
            summary = (m.get("summary") or "").strip()
            answer = _re.sub(r'^\[[^\]]+\]\s*', '', summary)
            records.append({
                "created_at": m.get("created_at") or "",
                "source_agent": m.get("source_agent") or "",
                "source_kind": m.get("source_kind") or "conversation_turn",
                "question": (m.get("content") or "").strip(),
                "answer": answer,
            })
        return records

    @staticmethod
    def _format_no_records(scope: str) -> str:
        if scope:
            return f"没有找到{scope}的对话记录。"
        return "没有找到对话记录。"
