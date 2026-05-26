"""Attach 会话注册表 — session_id ↔ trace_id 映射"""


class AttachRegistry:
    def __init__(self):
        self._attachments: dict[str, str] = {}  # session_id → trace_id
        self._task_owners: dict[str, str] = {}  # trace_id → session_id

    def bind(self, session_id: str, trace_id: str):
        self._attachments[session_id] = trace_id
        self._task_owners[trace_id] = session_id

    def unbind(self, trace_id: str):
        session_id = self._task_owners.pop(trace_id, None)
        if session_id:
            self._attachments.pop(session_id, None)

    def get_bound_task(self, session_id: str) -> str | None:
        return self._attachments.get(session_id)
