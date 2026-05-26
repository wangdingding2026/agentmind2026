class PromptEnvelope:
    """将 L0 MemoryRetriever 产出的记忆列表拼接为 Agent 最终 prompt。

    纯函数，无副作用，无 IO。逻辑来自 router.py:_inject_context 的后半段。
    """

    @staticmethod
    def build(raw_message: str, memories: list[dict]) -> str:
        if not memories:
            return raw_message

        # v4 预组装 context：第一条记忆携带 _v4_assembled 标记
        if memories and memories[0].get("_v4_assembled"):
            context = memories[0].get("_assembled_context", "")
            if context:
                return context + "\n\n当前指令：" + raw_message

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
