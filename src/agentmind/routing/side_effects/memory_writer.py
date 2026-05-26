import logging

from agentmind.memory.service import MemoryService

logger = logging.getLogger("agentmind")


class MemoryWriter:
    """L4 副作用：任务记忆写入 + 原子事实提取。

    静态方法，异常静默处理（记忆写入失败不影响主流程）。
    逻辑来自 router.py 的 _write_task_memory + _maybe_extract_atomic_facts。
    """

    @staticmethod
    async def write_task(
        trace_id: str, agent_id: str, user_message: str,
        result: str, user_id: str = "",
    ):
        try:
            summary = (result or "")[:1000]
            tags = ["task"]
            if user_id:
                tags.append(f"user:{user_id}")

            await MemoryService().write_memory({
                "memory_id": f"task-{trace_id}",
                "content": user_message,
                "summary": f"[{agent_id}] {summary}",
                "source_agent": agent_id,
                "source_task_id": trace_id,
                "tags": tags,
                "user_id": user_id,
            }, user_id=user_id)
        except Exception:
            pass

        # 记录到 Working Memory
        if user_id:
            try:
                svc = MemoryService()
                svc.add_to_working_memory(user_id, "user", user_message)
                svc.add_to_working_memory(user_id, "assistant", result or "")
            except Exception:
                pass

        await MemoryWriter._extract_facts(trace_id, agent_id, user_message, result, user_id)

    @staticmethod
    async def _extract_facts(
        trace_id: str, agent_id: str, user_msg: str,
        result: str, user_id: str = "",
    ):
        try:
            import yaml
            from agentmind.core.core_llm import extract_atomic_facts
            from agentmind.storage.db import CONFIG_DIR

            path = CONFIG_DIR / "settings.yaml"
            if not path.exists():
                return
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            if not data.get("memory", {}).get("atomic_facts", False):
                return
            if len(user_msg) < 10 and len(result or "") < 100:
                return

            facts = await extract_atomic_facts(user_msg, result or "")
            if not facts:
                return
            for i, f in enumerate(facts):
                fact_type = f.get("type", "knowledge")
                fact_text = f.get("fact", "")
                try:
                    fact_entry = {
                        "memory_id": f"fact-{trace_id}-{i}",
                        "content": fact_text,
                        "summary": f"[{agent_id}] {fact_type}: {fact_text[:200]}",
                        "source_agent": agent_id,
                        "source_task_id": trace_id,
                        "tags": ["fact", f"type:{fact_type}", f"user:{user_id}"] if user_id else ["fact", f"type:{fact_type}"],
                        "user_id": user_id,
                    }
                    await MemoryService().write_memory(fact_entry, user_id=user_id)
                except Exception:
                    pass
        except Exception:
            pass
