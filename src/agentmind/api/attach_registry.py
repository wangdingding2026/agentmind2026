"""Attach 会话注册表 — session_id ↔ trace_id 映射"""


class AttachRegistry:
    def __init__(self, runtime_store=None):
        self._attachments: dict[str, str] = {}  # session_id → trace_id
        self._task_owners: dict[str, str] = {}  # trace_id → session_id
        self._runtime_store = runtime_store

    def bind(self, session_id: str, trace_id: str):
        old_trace_id = self._attachments.get(session_id)
        if old_trace_id:
            self._task_owners.pop(old_trace_id, None)
        self._attachments[session_id] = trace_id
        self._task_owners[trace_id] = session_id
        if self._runtime_store is not None:
            self._runtime_store.upsert_attach_binding(session_id, trace_id)

    def unbind(self, trace_id: str):
        session_id = self._task_owners.pop(trace_id, None)
        if session_id:
            self._attachments.pop(session_id, None)
            if self._runtime_store is not None:
                self._runtime_store.delete_attach_binding(trace_id)

    def get_bound_task(self, session_id: str) -> str | None:
        return self._attachments.get(session_id)

    def restore_bindings(self, bindings: dict[str, str]):
        self._attachments = {
            str(session_id): str(trace_id)
            for session_id, trace_id in bindings.items()
        }
        self._task_owners = {
            trace_id: session_id
            for session_id, trace_id in self._attachments.items()
        }
