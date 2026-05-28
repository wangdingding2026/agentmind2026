# Feishu Channel Replay V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement a constrained Feishu `/replay <trace_id>` V1 command that returns a concise persisted task-event replay summary through the existing channel path.

**Architecture:** Add `ChannelReplayService` as the service boundary for explicit channel replay commands. The service parses `/replay <trace_id>`, calls `TaskReplayService`, and formats a bounded text summary from the service DTO. `ChannelHub` only checks this service before normal Feishu routing and returns the text response. `FeishuAdapter` remains a protocol adapter and does not know replay semantics.

**Tech Stack:** Python async services, pytest, existing `ChannelHub`, existing `TaskReplayService`.

---

## File Structure

- Create: `src/agentmind/services/channel_replay_service.py`
  - Owns explicit channel replay command parsing and concise text formatting.
  - Calls `TaskReplayService`; does not query `TaskEventService`, `TaskTimelineService`, or stream queues.
- Modify: `src/agentmind/services/__init__.py`
  - Exports `ChannelReplayService`.
- Modify: `src/agentmind/channels/hub.py`
  - Injects optional `channel_replay_service`.
  - Calls it inside Feishu message handling before discussion stop and normal routing.
  - Returns replay response chunks without calling `route_stream`.
- Create: `tests/test_channel_replay_service.py`
  - Covers explicit `/replay <trace_id>` parsing, non-command pass-through, missing replay, bounded event summary, and export.
- Modify: `tests/test_channel_hub.py`
  - Covers Feishu `/replay <trace_id>` command using injected service and confirms normal routing is skipped.
  - Covers non-replay messages still route normally.
- Modify: `docs/observability/channel-replay-adapter-readiness.md`
  - Updates status from readiness-only to Feishu V1 implemented.
- Modify: `docs/observability/task-event-closeout-status.md`
  - Notes Feishu channel replay V1 is implemented as a separate small package.
- Modify: `docs/architecture/final-closeout-status.md`
  - Notes channel replay V1 is no longer a deferred item, while API replay, UI, and advanced channel UX remain future packages.

No API replay endpoint, observability UI, stream runtime replay, live SSE queue recovery, natural-language task lookup, Feishu card UI, pagination, governance enforcement, or customer-content inspection is in scope.

### Task 1: Add ChannelReplayService RED Tests

**Files:**
- Create: `tests/test_channel_replay_service.py`

- [ ] **Step 1: Write failing service tests**

Create `tests/test_channel_replay_service.py`:

```python
import pytest


class _TaskReplayService:
    def __init__(self, replay):
        self.replay_response = replay
        self.calls = []

    async def replay(self, trace_id, limit=100):
        self.calls.append({"trace_id": trace_id, "limit": limit})
        return self.replay_response


def _available_replay(event_count=3):
    return {
        "trace_id": "t1",
        "found": True,
        "event_count": event_count,
        "source": "task_events",
        "replay_status": "available",
        "limit": 10,
        "timeline": [
            {
                "created_at": "2026-05-28 10:00:00",
                "event_type": "task_started",
                "agent_id": "",
                "message": "task started",
            },
            {
                "created_at": "2026-05-28 10:00:01",
                "event_type": "agent_selected",
                "agent_id": "agent-a",
                "message": "",
            },
            {
                "created_at": "2026-05-28 10:00:02",
                "event_type": "completed",
                "agent_id": "agent-a",
                "message": "done",
            },
        ],
    }


@pytest.mark.asyncio
async def test_channel_replay_service_ignores_non_replay_messages():
    from agentmind.services.channel_replay_service import ChannelReplayService

    task_replay_service = _TaskReplayService(_available_replay())
    service = ChannelReplayService(task_replay_service=task_replay_service)

    result = await service.handle_text("hello")

    assert result is None
    assert task_replay_service.calls == []


@pytest.mark.asyncio
async def test_channel_replay_service_requires_explicit_trace_id():
    from agentmind.services.channel_replay_service import ChannelReplayService

    task_replay_service = _TaskReplayService(_available_replay())
    service = ChannelReplayService(task_replay_service=task_replay_service)

    result = await service.handle_text("/replay")

    assert result == "用法：/replay <trace_id>"
    assert task_replay_service.calls == []


@pytest.mark.asyncio
async def test_channel_replay_service_formats_available_replay_summary():
    from agentmind.services.channel_replay_service import ChannelReplayService

    task_replay_service = _TaskReplayService(_available_replay())
    service = ChannelReplayService(task_replay_service=task_replay_service, limit=10)

    result = await service.handle_text("/replay t1")

    assert result == (
        "任务回放 t1：available，3 个事件\\n"
        "1. 2026-05-28 10:00:00 task_started - task started\\n"
        "2. 2026-05-28 10:00:01 agent_selected [agent-a]\\n"
        "3. 2026-05-28 10:00:02 completed [agent-a] - done"
    )
    assert task_replay_service.calls == [{"trace_id": "t1", "limit": 10}]


@pytest.mark.asyncio
async def test_channel_replay_service_formats_missing_replay_summary():
    from agentmind.services.channel_replay_service import ChannelReplayService

    task_replay_service = _TaskReplayService({
        "trace_id": "missing",
        "found": False,
        "event_count": 0,
        "source": "task_events",
        "replay_status": "missing",
        "limit": 10,
        "timeline": [],
    })
    service = ChannelReplayService(task_replay_service=task_replay_service, limit=10)

    result = await service.handle_text("/replay missing")

    assert result == "任务回放 missing：missing，未找到持久化任务事件。"
    assert task_replay_service.calls == [{"trace_id": "missing", "limit": 10}]


@pytest.mark.asyncio
async def test_channel_replay_service_bounds_summary_events():
    from agentmind.services.channel_replay_service import ChannelReplayService

    replay = _available_replay(event_count=3)
    task_replay_service = _TaskReplayService(replay)
    service = ChannelReplayService(
        task_replay_service=task_replay_service,
        limit=10,
        summary_event_limit=2,
    )

    result = await service.handle_text("/replay t1")

    assert "1. 2026-05-28 10:00:00 task_started - task started" in result
    assert "2. 2026-05-28 10:00:01 agent_selected [agent-a]" in result
    assert "还有 1 个事件未展示" in result
    assert "3. 2026-05-28 10:00:02 completed" not in result


def test_channel_replay_service_is_exported_from_services_package():
    from agentmind.services import ChannelReplayService

    assert ChannelReplayService.__name__ == "ChannelReplayService"
```

- [ ] **Step 2: Run service RED**

Run:

```bash
pytest tests/test_channel_replay_service.py -q
```

Expected: FAIL because `agentmind.services.channel_replay_service` does not exist.

### Task 2: Add ChannelHub RED Tests

**Files:**
- Modify: `tests/test_channel_hub.py`

- [ ] **Step 1: Add failing ChannelHub tests**

Append to `tests/test_channel_hub.py`:

```python
class _ChannelReplayService:
    def __init__(self, response=None):
        self.response = response
        self.calls = []

    async def handle_text(self, text):
        self.calls.append(text)
        return self.response


@pytest.mark.asyncio
async def test_channel_hub_feishu_replay_command_returns_replay_without_routing():
    from agentmind.channels.hub import ChannelHub, ChannelMessage

    app = _App()
    captured = {}
    route_calls = []
    replay_service = _ChannelReplayService(response="任务回放 t1：available，1 个事件")

    def adapter_factory(**kwargs):
        captured.update(kwargs)
        return _Adapter()

    async def route_stream_func(*args, **kwargs):
        route_calls.append((args, kwargs))
        yield "should not route"

    hub = ChannelHub(
        config_service=_ConfigService(),
        feishu_adapter_factory=adapter_factory,
        route_stream_func=route_stream_func,
        channel_replay_service=replay_service,
    )
    await hub.connect_feishu(app, "app", "secret")

    result = await captured["message_callback"](
        ChannelMessage(channel_id="feishu", sender_id="u1", text="/replay t1")
    )

    assert result == ["任务回放 t1：available，1 个事件"]
    assert replay_service.calls == ["/replay t1"]
    assert route_calls == []


@pytest.mark.asyncio
async def test_channel_hub_feishu_non_replay_message_still_routes_normally():
    from agentmind.channels.hub import ChannelHub, ChannelMessage

    app = _App()
    captured = {}
    route_calls = []
    replay_service = _ChannelReplayService(response=None)

    def adapter_factory(**kwargs):
        captured.update(kwargs)
        return _Adapter()

    async def route_stream_func(*args, **kwargs):
        route_calls.append((args, kwargs))
        yield "normal reply"

    hub = ChannelHub(
        config_service=_ConfigService(),
        feishu_adapter_factory=adapter_factory,
        route_stream_func=route_stream_func,
        channel_replay_service=replay_service,
    )
    await hub.connect_feishu(app, "app", "secret")

    result = await captured["message_callback"](
        ChannelMessage(channel_id="feishu", sender_id="u1", text="hello")
    )

    assert result == ["normal reply"]
    assert replay_service.calls == ["hello"]
    assert len(route_calls) == 1
```

- [ ] **Step 2: Run ChannelHub RED**

Run:

```bash
pytest tests/test_channel_hub.py::test_channel_hub_feishu_replay_command_returns_replay_without_routing tests/test_channel_hub.py::test_channel_hub_feishu_non_replay_message_still_routes_normally -q
```

Expected: FAIL because `ChannelHub.__init__` does not accept `channel_replay_service`.

### Task 3: Implement ChannelReplayService and ChannelHub Wiring

**Files:**
- Create: `src/agentmind/services/channel_replay_service.py`
- Modify: `src/agentmind/services/__init__.py`
- Modify: `src/agentmind/channels/hub.py`

- [ ] **Step 1: Implement service**

Create `src/agentmind/services/channel_replay_service.py`:

```python
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
```

- [ ] **Step 2: Export service**

In `src/agentmind/services/__init__.py`, add:

```python
from agentmind.services.channel_replay_service import ChannelReplayService
```

and add `"ChannelReplayService"` to `__all__`.

- [ ] **Step 3: Wire ChannelHub**

In `src/agentmind/channels/hub.py`, update `ChannelHub.__init__` to accept `channel_replay_service=None` and store it.

At the start of `_handle_feishu_message`, before discussion stop and normal routing:

```python
        replay_result = await self._handle_channel_replay(message)
        if replay_result is not None:
            return [replay_result]
```

Add:

```python
    async def _handle_channel_replay(self, message: ChannelMessage) -> str | None:
        service = self._channel_replay_service
        if service is None:
            from agentmind.services.channel_replay_service import ChannelReplayService

            service = ChannelReplayService()
            self._channel_replay_service = service
        return await service.handle_text(message.text)
```

- [ ] **Step 4: Run GREEN focused**

Run:

```bash
pytest tests/test_channel_replay_service.py tests/test_channel_hub.py::test_channel_hub_feishu_replay_command_returns_replay_without_routing tests/test_channel_hub.py::test_channel_hub_feishu_non_replay_message_still_routes_normally -q
```

Expected: PASS.

### Task 4: Update Docs and Regression Verification

**Files:**
- Modify: `docs/observability/channel-replay-adapter-readiness.md`
- Modify: `docs/observability/task-event-closeout-status.md`
- Modify: `docs/architecture/final-closeout-status.md`

- [ ] **Step 1: Update channel replay readiness status**

In `docs/observability/channel-replay-adapter-readiness.md`, change the implementation deferral sentence to:

```markdown
Feishu `/replay <trace_id>` V1 is implemented as a separate small package.
```

Add under `## Adapter Boundary`:

```markdown
ChannelReplayService owns explicit channel replay command parsing and concise text formatting.

ChannelHub calls ChannelReplayService before normal Feishu routing.

FeishuAdapter remains a protocol adapter and does not know replay semantics.
```

- [ ] **Step 2: Update closeout docs**

In `docs/observability/task-event-closeout-status.md`, add:

```markdown
Feishu channel replay V1 is implemented through ChannelReplayService and explicit `/replay <trace_id>` commands.
```

In `docs/architecture/final-closeout-status.md`, change the channel replay future-work bullet to:

```markdown
- advanced channel replay UX beyond Feishu `/replay <trace_id>` V1;
```

- [ ] **Step 3: Run focused documentation/readiness tests**

Run:

```bash
pytest tests/test_channel_replay_adapter_readiness.py tests/test_architecture_final_closeout_audit.py tests/test_task_event_closeout_audit.py -q
```

Expected: PASS.

- [ ] **Step 4: Run observability/service regression**

Run:

```bash
pytest tests/test_channel_replay_service.py tests/test_channel_replay_adapter_readiness.py tests/test_task_replay_service.py tests/test_task_timeline_service.py tests/test_task_event_service.py -q
```

Expected: PASS.

- [ ] **Step 5: Run channel/Feishu regression**

Run:

```bash
pytest tests/test_channel_hub.py tests/test_feishu_channel.py tests/test_feishu_path.py tests/test_feishu_route_callback_deletion_readiness.py -q
```

Expected: PASS.

- [ ] **Step 6: Run panel/architecture regression**

Run:

```bash
pytest tests/test_panel_api.py tests/test_panel_control_plane_boundary.py tests/test_phase5_closure_audit.py tests/test_architecture_final_closeout_audit.py -q
```

Expected: PASS.

- [ ] **Step 7: Run router/panel regression**

Run:

```bash
pytest tests/test_router.py tests/test_panel_api.py tests/test_feishu_path.py tests/test_e2e_scenarios.py tests/test_pipeline_executors.py -q
```

Expected: PASS.

- [ ] **Step 8: Run full validation**

Run:

```bash
pytest -q
git diff --check
git status --short
```

Expected: full pytest PASS, whitespace check clean, and only intended files changed before commit.

- [ ] **Step 9: Commit**

Run:

```bash
git add src/agentmind/services/channel_replay_service.py src/agentmind/services/__init__.py src/agentmind/channels/hub.py tests/test_channel_replay_service.py tests/test_channel_hub.py docs/observability/channel-replay-adapter-readiness.md docs/observability/task-event-closeout-status.md docs/architecture/final-closeout-status.md docs/superpowers/plans/2026-05-28-feishu-channel-replay-v1.md
git commit -m "feat: add feishu channel replay command"
```

Expected: commit succeeds.

## Self-Review

- Spec coverage: this plan implements only Feishu `/replay <trace_id>` V1, through a service boundary over `TaskReplayService`, and keeps FeishuAdapter protocol-only.
- Placeholder scan: no TBD, TODO, or open implementation placeholders.
- Scope check: no API replay endpoint, observability UI, stream runtime replay, live SSE queue persistence, natural-language task lookup, Feishu card UI, pagination, governance enforcement, customer-content inspection, TaskEventService schema change, TaskTimelineService ordering/query change, or SessionRuntimeService change is included.
