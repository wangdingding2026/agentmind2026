import json
import logging
import re as _re
from datetime import datetime

from agentmind.routing.context import RoutingDecision
from agentmind.routing.executors.base import ExecutorBase
from agentmind.services.task_service import TaskService
from agentmind.storage.db import record_task_update

logger = logging.getLogger("agentmind")

# 检测"当前会话"语义：现在/当前/这个/本 + session/会话
_CURRENT_SESSION_RE = _re.compile(r'(现在|当前|这个|本)\s*(的)?\s*(session|会话)')


class SelfReplyExecutor(ExecutorBase):
    """L3 执行器：AgentMind 自答。

    当 LLMRouting 策略决定直接回复（action: reply）时使用。
    agent_id 固定为 "agentmind"。

    注意：record_task_start 由调用方（route_request / route_stream）负责，
    本执行器只做 update + end。
    """

    @staticmethod
    def _update_working_memory(user_id: str, user_msg: str, reply: str):
        """记录本轮自答对话到 Working Memory（不写持久化记忆，避免自循环）。"""
        if not user_id:
            return
        try:
            from agentmind.memory.service import MemoryService
            svc = MemoryService()
            svc.add_to_working_memory(user_id, "user", user_msg)
            svc.add_to_working_memory(user_id, "assistant", reply)
        except Exception:
            pass

    async def run_json(self, decision: RoutingDecision, trace_id: str, user_id: str):
        reply = self._build_reply(decision)

        await record_task_update(trace_id, status="executing", routed_agent="agentmind")

        await self._record_success(
            trace_id, "agentmind",
            decision.context.raw_message, reply, user_id,
        )
        self._update_working_memory(user_id, decision.context.raw_message, reply)

        logger.info("AgentMind 自答：%s", reply[:60])
        from fastapi.responses import JSONResponse
        return JSONResponse(content={
            "agent_id": "agentmind",
            "result": reply,
            "trace_id": trace_id,
            "status": "completed",
        })

    async def run_stream(self, decision: RoutingDecision, trace_id: str, user_id: str):
        reply = self._build_reply(decision)

        await record_task_update(trace_id, status="executing", routed_agent="agentmind")

        yield {"event": "status", "data": json.dumps({
            "status": "routed",
            "agent_id": "agentmind",
            "matched_rule": decision.strategy,
            "trace_id": trace_id,
        })}
        yield {"event": "status", "data": json.dumps({
            "status": "executing",
            "agent_id": "agentmind",
            "trace_id": trace_id,
        })}

        await TaskService().record_partial_output(
            trace_id,
            agent_id="agentmind",
            content=reply,
            chunk_index=1,
        )

        yield {"event": "partial", "data": json.dumps({
            "content": reply,
            "trace_id": trace_id,
        })}

        yield {"event": "status", "data": json.dumps({
            "status": "completed",
            "trace_id": trace_id,
            "execution_time_ms": 0,
        })}

        await self._record_success(
            trace_id, "agentmind",
            decision.context.raw_message, reply, user_id,
        )
        self._update_working_memory(user_id, decision.context.raw_message, reply)

        logger.info("AgentMind 自答（流式）：%s", reply[:60])

    async def run_text(self, decision: RoutingDecision, trace_id: str, user_id: str):
        reply = self._build_reply(decision)

        await record_task_update(trace_id, status="executing", routed_agent="agentmind")

        await TaskService().record_partial_output(
            trace_id,
            agent_id="agentmind",
            content=reply,
            chunk_index=1,
        )

        yield reply

        await self._record_success(
            trace_id, "agentmind",
            decision.context.raw_message, reply, user_id,
        )
        self._update_working_memory(user_id, decision.context.raw_message, reply)
        logger.info("AgentMind 自答（文本）：%s", reply[:60])

    def _get_active_conversation_id(self, user_id: str) -> str:
        """查询用户当前活跃的 conversation_id，若无则返回空字符串。"""
        try:
            from agentmind.memory.service import MemoryService
            return MemoryService().get_active_conversation_id(user_id) or ""
        except Exception:
            return ""

    def _build_working_memory_reply(self, user_id: str) -> str | None:
        """从 Working Memory 构建当前会话摘要。无内容时返回 None。"""
        try:
            from agentmind.memory.service import MemoryService
            rounds = MemoryService().get_working_memory(user_id, limit=10)
            if not rounds:
                return None

            lines = ["当前会话的对话记录："]
            for i, r in enumerate(rounds, 1):
                user_msg = (r.get("user") or "")[:80]
                assistant_msg = (r.get("assistant") or "")[:200]
                ts = (r.get("ts") or "")[:16]
                lines.append(f"\n{i}. {ts}")
                lines.append(f"   问：{user_msg}")
                if assistant_msg:
                    lines.append(f"   答：{assistant_msg}")
            return "\n".join(lines)
        except Exception:
            return None

    def _build_reply(self, decision: RoutingDecision) -> str:
        """构建自答内容：两级展示——先话题索引，用户可追问展开"""
        raw_msg = decision.context.raw_message if decision.context else ""
        is_current_session_query = bool(_CURRENT_SESSION_RE.search(raw_msg))

        # reply_text 由 LLM 路由生成，会绕过记忆过滤；
        # 对"当前会话"查询，忽略 reply_text 走结构化路径
        if decision.reply_text and not is_current_session_query:
            return decision.reply_text

        memories = decision.context.memories if decision.context else []

        # 检测"当前会话"语义：过滤仅保留当前 active conversation 的记忆
        if is_current_session_query:
            user_id = decision.context.identity.user_id if decision.context else ""
            if user_id:
                active_conv_id = self._get_active_conversation_id(user_id)
                if active_conv_id:
                    memories = [m for m in memories if m.get("conversation_id") == active_conv_id]
                else:
                    memories = []
                # conversation_id 过滤无结果时，回退到 Working Memory
                # Conversation records are maintained by the canonical memory repository.
                if not memories:
                    wm_reply = self._build_working_memory_reply(user_id)
                    if wm_reply:
                        return wm_reply
                    return "当前会话还没有任何对话记录。"

        if not memories:
            return "抱歉，我暂时没有找到相关的记忆记录。"

        # 从消息中提取用户关心的日期
        from collections import defaultdict
        requested_date = None
        dm = _re.search(r'(\d{1,2})\s*月\s*(\d{1,2})\s*日?', raw_msg)
        if dm:
            month, day = int(dm.group(1)), int(dm.group(2))
            requested_date = f"{datetime.now().year}-{month:02d}-{day:02d}"

        # 用户是否在追问某个话题（含"展开""详细""深入"等词）
        deep_dive = bool(_re.search(r'展开|详细|深入|具体|说说|第\s*\d+\s*个', raw_msg))
        # 提取话题编号
        topic_num = None
        tn = _re.search(r'第\s*(\d+)\s*个', raw_msg)
        if tn:
            topic_num = int(tn.group(1)) - 1  # 0-indexed

        # 按日期分组，去重（去掉讨论轮次号）
        by_date: dict[str, list[dict]] = defaultdict(list)
        seen_content = set()
        for mem in memories:
            date = (mem.get("created_at") or "")[:10] or "未知日期"
            content = (mem.get("content") or "").strip()
            dedup_key = _re.sub(r'（第\d+轮）', '', content)[:60]
            if dedup_key in seen_content:
                continue
            seen_content.add(dedup_key)
            by_date[date].append(mem)

        sorted_dates = sorted(by_date.keys(), reverse=True)

        # ── 二级：展开特定话题 ──
        if deep_dive and requested_date and requested_date in by_date and topic_num is not None:
            entries = by_date[requested_date]
            if 0 <= topic_num < len(entries):
                m = entries[topic_num]
                content = (m.get("content") or "").strip()
                summary = (m.get("summary") or "").strip()
                agent = m.get("source_agent", "")
                summary_clean = _re.sub(r'^\[[^\]]+\]\s*', '', summary)
                lines = [f"{requested_date} 话题「{content[:80]}」的详细内容："]
                lines.append(f"\n回答者：{agent}")
                if summary_clean and len(summary_clean) > 5:
                    lines.append(f"内容：\n{summary_clean}")
                return "\n".join(lines)

        # ── 一级：话题索引 ──
        lines = []
        if requested_date:
            if requested_date in by_date:
                entries = by_date[requested_date]
                agents = list(dict.fromkeys(
                    e.get("source_agent", "") for e in entries if e.get("source_agent")
                ))
                lines.append(f"{requested_date} 有 {len(entries)} 个话题，涉及 {', '.join(agents)}：")
                for i, m in enumerate(entries):
                    content = (m.get("content") or "").strip()
                    agent = m.get("source_agent", "")
                    # 去 @agent 前缀生成简短话题名
                    topic_name = _re.sub(r'^@\S+\s*', '', content)[:60]
                    lines.append(f"  {i+1}. [{agent}] {topic_name}")
                if len(entries) > 1:
                    lines.append(f"\n回复「展开第N个」查看话题详情。")
                del by_date[requested_date]
            else:
                lines.append(f"没有找到 {requested_date} 的对话记录。")
                if sorted_dates:
                    lines.append(f"最近的记录来自：{', '.join(sorted_dates[:5])}")

        # 其他日期摘要
        if by_date and not requested_date:
            lines.append("记忆库中的对话记录：")
        for date in sorted_dates:
            if date == requested_date:
                continue
            entries = by_date[date]
            if not entries:
                continue
            agents = list(dict.fromkeys(
                e.get("source_agent", "") for e in entries if e.get("source_agent")
            ))
            # 提取话题关键词
            topics = []
            for m in entries[:5]:
                c = _re.sub(r'^@\S+\s*', '', (m.get("content") or "").strip())[:50]
                topics.append(c)
            topic_preview = "、".join(topics[:3])
            if len(entries) > 3:
                topic_preview += f" 等 {len(entries)} 个话题"
            lines.append(f"\n{date}（{', '.join(agents[:3])}）：{topic_preview}")

        return "\n".join(lines) if lines else "抱歉，我暂时没有找到相关的记忆记录。"
