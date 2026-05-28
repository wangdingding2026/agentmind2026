from __future__ import annotations

from typing import Any

from agentmind.services.task_replay_service import TaskReplayService


class ChannelReplayService:
    """Read-only channel command boundary over TaskReplayService."""

    COMMAND = "/replay"

    def __init__(
        self,
        *,
        task_replay_service=None,
        limit: int = 10,
        summary_event_limit: int = 10,
    ):
        self._task_replay_service = task_replay_service or TaskReplayService()
        self._limit = limit
        self._summary_event_limit = summary_event_limit

    async def handle_text(self, text: str) -> str | None:
        parsed = self._parse_command(text)
        if parsed is None:
            return None
        if not parsed:
            return "用法：/replay <trace_id>"

        replay = await self._task_replay_service.replay(parsed, limit=self._limit)
        return self._format_replay(replay)

    def _parse_command(self, text: str) -> str | None:
        stripped = str(text or "").strip()
        if not stripped.startswith(self.COMMAND):
            return None

        parts = stripped.split(maxsplit=1)
        if parts[0] != self.COMMAND:
            return None
        if len(parts) == 1:
            return ""
        return parts[1].strip()

    def _format_replay(self, replay: dict[str, Any]) -> str:
        trace_id = str(replay.get("trace_id") or "")
        status = str(replay.get("replay_status") or "missing")
        event_count = int(replay.get("event_count") or 0)

        if not replay.get("found"):
            return f"任务回放 {trace_id}：{status}，未找到持久化任务事件。"

        lines = [f"任务回放 {trace_id}：{status}，{event_count} 个事件"]
        timeline = list(replay.get("timeline") or [])
        shown = timeline[: self._summary_event_limit]
        for index, event in enumerate(shown, start=1):
            lines.append(f"{index}. {self._format_event(event)}")

        remaining = max(0, len(timeline) - len(shown))
        if remaining:
            lines.append(f"还有 {remaining} 个事件未展示")
        return "\n".join(lines)

    def _format_event(self, event: dict[str, Any]) -> str:
        created_at = str(event.get("created_at") or "")
        event_type = str(event.get("event_type") or "")
        agent_id = str(event.get("agent_id") or "")
        message = str(event.get("message") or "")

        parts = [created_at, event_type]
        if agent_id:
            parts.append(f"[{agent_id}]")
        line = " ".join(part for part in parts if part)
        if message:
            line = f"{line} - {message}"
        return line
