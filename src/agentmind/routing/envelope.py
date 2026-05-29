from agentmind.memory.dto import MemoryContext


class PromptEnvelope:
    """将 L0 MemoryRetriever 产出的记忆列表拼接为 Agent 最终 prompt。

    纯函数，无副作用，无 IO。逻辑来自 router.py:_inject_context 的后半段。
    """

    @staticmethod
    def build(raw_message: str, memory_context: MemoryContext | list[dict] | None) -> str:
        if not memory_context:
            return raw_message

        if isinstance(memory_context, MemoryContext):
            if memory_context.assembled_context:
                return memory_context.assembled_context + "\n\n当前指令：" + raw_message
            memories = memory_context.recall_items
        else:
            memories = memory_context

        parts = []
        for m in memories:
            content = (m.get("content") or "")[:300]
            summary = (m.get("summary") or "")[:1000]
            parts.append(f"用户问「{content}」→ {summary}")

        return (
            "[系统注入：历史对话上下文，请据此理解当前指令]\n"
            + "\n".join(parts)
            + "\n\n当前指令：" + raw_message
        )
