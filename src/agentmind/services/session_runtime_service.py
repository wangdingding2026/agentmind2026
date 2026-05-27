from agentmind.services.task_service import TaskService


class SessionRuntimeService:
    def __init__(
        self,
        session_registry=None,
        task_service=None,
        attach_registry=None,
        runtime_store=None,
    ):
        self.session_registry = session_registry or self._default_session_registry()
        self.task_service = task_service or TaskService()
        self.attach_registry = attach_registry
        self.runtime_store = runtime_store or self._default_runtime_store()

    async def active_sessions(self):
        discussions = [
            {"user_id": user_id, "stop": discussion.get("stop", False)}
            for user_id, discussion in self.session_registry.list_discussions().items()
        ]
        tasks = await self.task_service.query_tasks(limit=5, status="executing")
        return {"discussions": discussions, "executing_tasks": tasks}

    def attach_to_task(self, trace_id: str, session_id: str):
        if not session_id:
            return {"error": "缺少 session_id 参数"}
        if not self.attach_registry:
            return {"error": "Attach 功能未启用"}

        self.attach_registry.bind(session_id, trace_id)
        return {"status": "attached", "trace_id": trace_id}

    async def stream_events(self, trace_id: str):
        queue = self.session_registry.register_stream_listener(trace_id)
        try:
            while True:
                chunk = await queue.get()
                if chunk is None:
                    break
                yield chunk
        finally:
            self.session_registry.unregister_stream_listener(trace_id, queue)

    def restore_runtime_state(self):
        discussions = self.runtime_store.list_discussions()
        self.session_registry.restore_discussions(discussions)
        return {"restored_discussions": len(discussions)}

    @staticmethod
    def _default_session_registry():
        from agentmind.routing.side_effects.session_registry import session_registry

        return session_registry

    @staticmethod
    def _default_runtime_store():
        from agentmind.services.session_runtime_store import SessionRuntimeStore

        return SessionRuntimeStore()
