from agentmind.memory.dto import MemoryContext


class PromptEnvelope:
    """将 MemoryContext.assembled_context 包装为 Agent 最终 prompt。

    纯函数，无副作用，无 IO。assembled_context 由 ContextAssembler 统一生成，
    PromptEnvelope 仅负责追加当前指令字符串。

    兼容旧调用方传入 list[dict] 的情况——直接返回原始消息，不做格式化。
    """

    @staticmethod
    def build(raw_message: str, memory_context: MemoryContext | list[dict] | None) -> str:
        if memory_context is None:
            return raw_message
        if isinstance(memory_context, list):
            # 兼容旧调用方（已由 MemoryRetriever → ContextAssembler 统一格式化，
            # 不再在此处拼装 prompt）
            return raw_message
        if memory_context.assembled_context:
            return memory_context.assembled_context + "\n\n当前指令：" + raw_message
        return raw_message
