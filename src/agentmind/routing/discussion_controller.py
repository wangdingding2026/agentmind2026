from __future__ import annotations

from dataclasses import dataclass, field
import re


def extract_word_limit(topic: str, default: int = 300) -> int:
    match = re.search(r'(\d+)\s*(?:个\s*)?字', topic or "")
    if not match:
        return default
    return max(1, int(match.group(1)))


@dataclass
class DiscussionController:
    """Keep multi-agent discussion prompts anchored to the user's topic."""

    original_topic: str
    max_chars: int = 300
    history: list[tuple[str, str]] = field(default_factory=list)

    @classmethod
    def from_topic(cls, topic: str) -> "DiscussionController":
        return cls(original_topic=topic, max_chars=extract_word_limit(topic))

    @property
    def word_limit(self) -> str:
        return f"限{self.max_chars}字"

    def response_contract(self) -> str:
        if self.max_chars <= 20:
            shape = "只输出一句结论，不要理由。"
        elif self.max_chars <= 60:
            shape = "只输出一句完整短答，包含立场和一个短理由。"
        elif self.max_chars <= 120:
            shape = "输出两句以内，包含立场、理由和建议。"
        else:
            shape = "可以简短展开，但不要列表。"
        return (
            f"必须一次性输出{self.max_chars}字以内的完整中文短句。"
            f"{shape}"
            "不要解释规则，不要列表，不要省略号，不要半句话。"
        )

    def build_turn_prompt(self) -> str:
        anchor = (
            "[讨论控制]\n"
            f'原始议题："{self.original_topic}"\n'
            f"输出要求：{self.word_limit}。\n"
            f"{self.response_contract()}\n"
            "只围绕原始议题回答。不得把例子、局部概念或上一轮的偏题内容扩展为新议题。"
        )
        if not self.history:
            return f"{anchor}\n请发表你的核心观点，并用一句话直接回答原始议题。"

        previous_name, previous_response = self.history[-1]
        return (
            f"{anchor}\n"
            "上一轮待审查观点（仅供参考，不得视为新的讨论主题）：\n"
            f'{previous_name}：\n"""{previous_response[:800]}"""\n'
            "请只回应其中与原始议题直接相关的部分。"
            "若上一轮偏离原始议题，请忽略偏题内容并主动拉回原始议题。\n"
            "请说明同意、反驳或补充的理由，并用一句话直接回答原始议题。"
        )

    def record_response(self, agent_name: str, response: str) -> None:
        self.history.append((agent_name, response))

    def is_valid_response(self, text: str) -> bool:
        normalized = (text or "").strip()
        if not normalized or len(normalized) > self.max_chars:
            return False
        return normalized[-1] not in "，、：；,;:"

    def build_rewrite_prompt(self, text: str, *, kind: str = "观点") -> str:
        return (
            "[讨论控制]\n"
            f'原始议题："{self.original_topic}"\n'
            f"你的上一版{kind}不符合输出要求。\n"
            f"请重写为{self.max_chars}字以内的完整中文短句。\n"
            f"{self.response_contract()}\n"
            "只能输出重写后的最终内容，不要解释。\n"
            f"上一版{kind}：\n{text[:1000]}"
        )

    def build_summary_prompt(self) -> str:
        lines = [
            "[讨论控制]",
            f'原始议题："{self.original_topic}"',
            f"输出要求：{self.word_limit}。",
            self.response_contract(),
            "请仅总结与原始议题直接相关的内容，忽略与原始议题无关的内容。",
            "讨论记录：",
        ]
        for name, response in self.history:
            lines.append(f"{name}：{response[:800]}")
        lines.extend([
            "",
            "请输出结构化结论，按以下格式：",
            "1. 核心结论（一句话概括讨论结果）",
            "2. 共识点（列出双方都同意的）",
            "3. 分歧点（列出双方立场不同的）",
            "4. 行动建议（基于讨论结果，下一步该做什么）",
        ])
        return "\n".join(lines)
