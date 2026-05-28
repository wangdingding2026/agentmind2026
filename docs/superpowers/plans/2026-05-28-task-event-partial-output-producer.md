# Task Event Partial Output Producer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist `partial_output` task timeline events from streaming task output without changing live SSE listener queues, stream snapshots, replay runtime, panel/API/channel behavior, or governance enforcement.

**Architecture:** `TaskService` remains the task lifecycle and task-event producer boundary. A new `TaskService.record_partial_output(...)` method records structured `partial_output` metadata through `TaskEventService`, and streaming executors call this service method when they emit content chunks. `SessionRegistry`, `stream_snapshot`, live SSE queues, replay services, and panel/API/channel adapters are not used for partial-output persistence.

**Tech Stack:** Python async services, pytest, existing routing executor tests, Markdown architecture docs.

---

## File Structure

- Modify: `src/agentmind/services/task_service.py`
  - Add `record_partial_output(trace_id, agent_id=None, content="", chunk_index=0)`.
  - Persist `partial_output` events with `seq=50` and structured payload.
  - Catch task-event recording failures using the existing `_record_task_event` helper.
- Modify: `src/agentmind/routing/executors/single_agent.py`
  - Import `TaskService`.
  - Call `TaskService().record_partial_output(...)` when `run_stream` emits SSE `partial` chunks.
  - Call it when `run_text` emits text chunks without `response_path`.
- Modify: `src/agentmind/routing/executors/self_reply.py`
  - Import `TaskService`.
  - Call `TaskService().record_partial_output(...)` when `run_stream` emits its self-reply partial chunk.
  - Call it when `run_text` emits its self-reply text.
- Modify: `tests/test_task_service.py`
  - Adds RED/GREEN service-level tests for `record_partial_output`.
- Modify: `tests/test_pipeline_executors.py`
  - Adds executor producer tests proving stream/text content chunks call `TaskService.record_partial_output`.
- Modify: `docs/observability/task-event-readiness.md`
  - Updates producer status to note `partial_output` capture is now implemented.
- Modify: `docs/observability/task-event-replay-readiness.md`
  - Notes replay may include persisted `partial_output` events through `TaskTimelineService`, while stream runtime replay stays out of scope.

No `TaskEventService` schema change, `TaskTimelineService` query/order change, replay runtime, observability UI, channel adapter, API replay endpoint, `SessionRuntimeService`, `SessionRegistry`, `stream_snapshot`, live SSE queue persistence/restoration, CPE/AgentShield enforcement, customer-content inspection, or `feishu.route_callback` expansion is in scope.

### Task 1: Add TaskService Partial Output RED Tests

**Files:**
- Modify: `tests/test_task_service.py`

- [ ] **Step 1: Write the failing service tests**

Append near existing task-event producer tests:

```python
@pytest.mark.asyncio
async def test_task_service_produces_partial_output_event(tmp_db):
    event_service = _TaskEventRecorder()
    service = TaskService(task_event_service=event_service)

    await service.record_partial_output(
        "tr-partial",
        agent_id="agent-a",
        content="hello world",
        chunk_index=2,
    )

    assert event_service.events == [
        {
            "trace_id": "tr-partial",
            "event_type": "partial_output",
            "seq": 50,
            "agent_id": "agent-a",
            "message": "partial output",
            "payload": {
                "chunk_index": 2,
                "content_length": 11,
                "preview": "hello world",
            },
        }
    ]


@pytest.mark.asyncio
async def test_task_service_truncates_partial_output_preview(tmp_db):
    event_service = _TaskEventRecorder()
    service = TaskService(task_event_service=event_service)

    await service.record_partial_output("tr-partial", content="x" * 300)

    payload = event_service.events[0]["payload"]
    assert payload["content_length"] == 300
    assert payload["preview"] == "x" * 200


@pytest.mark.asyncio
async def test_task_service_ignores_partial_output_event_failures(tmp_db):
    service = TaskService(task_event_service=_FailingTaskEventRecorder())

    await service.record_partial_output("tr-partial", content="hello")
```

- [ ] **Step 2: Run service RED**

Run:

```bash
pytest tests/test_task_service.py::test_task_service_produces_partial_output_event tests/test_task_service.py::test_task_service_truncates_partial_output_preview tests/test_task_service.py::test_task_service_ignores_partial_output_event_failures -q
```

Expected: FAIL because `TaskService.record_partial_output` does not exist.

### Task 2: Implement TaskService Partial Output Producer

**Files:**
- Modify: `src/agentmind/services/task_service.py`
- Test: `tests/test_task_service.py`

- [ ] **Step 1: Add the service method**

Add this public method before `_record_task_event`:

```python
    async def record_partial_output(
        self,
        trace_id: str,
        agent_id: str | None = None,
        content: str = "",
        chunk_index: int = 0,
    ) -> None:
        text = content or ""
        await self._record_task_event(
            trace_id=trace_id,
            event_type="partial_output",
            seq=50,
            agent_id=agent_id or "",
            message="partial output",
            payload={
                "chunk_index": chunk_index,
                "content_length": len(text),
                "preview": text[:200],
            },
        )
```

- [ ] **Step 2: Run service GREEN**

Run:

```bash
pytest tests/test_task_service.py::test_task_service_produces_partial_output_event tests/test_task_service.py::test_task_service_truncates_partial_output_preview tests/test_task_service.py::test_task_service_ignores_partial_output_event_failures -q
```

Expected: PASS.

### Task 3: Add Executor Producer RED Tests

**Files:**
- Modify: `tests/test_pipeline_executors.py`

- [ ] **Step 1: Write failing executor tests**

Add helper:

```python
class _TaskServiceRecorder:
    def __init__(self):
        self.calls = []

    async def record_partial_output(self, trace_id, agent_id=None, content="", chunk_index=0):
        self.calls.append({
            "trace_id": trace_id,
            "agent_id": agent_id,
            "content": content,
            "chunk_index": chunk_index,
        })
```

Add this test under `TestSingleAgentStreamFallback`:

```python
    @pytest.mark.asyncio
    async def test_run_stream_records_partial_output_events(self, monkeypatch):
        async def _fake_stream(msg):
            yield StreamEvent(StreamEventType.CONTENT, "hello")
            yield StreamEvent(StreamEventType.CONTENT, " world")

        ex = _mock_executor(succeed=True)
        ex.execute_stream = _fake_stream
        reg = _mock_registry({"a1": ex})
        recorder = _TaskServiceRecorder()

        decision = _make_decision(agent_id="a1", fallback_chain=[])
        monkeypatch.setattr("agentmind.routing.executors.single_agent.record_task_end", AsyncMock())
        monkeypatch.setattr("agentmind.routing.executors.single_agent.record_task_update", AsyncMock())
        monkeypatch.setattr("agentmind.routing.executors.single_agent.TaskService", lambda: recorder)
        monkeypatch.setattr("agentmind.routing.executors.base.MemoryWriter.write_task", AsyncMock())

        executor = SingleAgentExecutor(reg)
        async for _chunk in executor.run_stream(decision, "t1", "u1"):
            pass

        assert recorder.calls == [
            {"trace_id": "t1", "agent_id": "a1", "content": "hello", "chunk_index": 1},
            {"trace_id": "t1", "agent_id": "a1", "content": " world", "chunk_index": 2},
        ]
```

Add this test under `TestSingleAgentRunText`:

```python
    @pytest.mark.asyncio
    async def test_run_text_records_partial_output_events(self, monkeypatch):
        from agentmind.routing.context import RequestIdentity, RoutingContext

        async def _stream(msg):
            yield StreamEvent(StreamEventType.CONTENT, "chunk1")
            yield StreamEvent(StreamEventType.CONTENT, "chunk2")

        cap = AgentCapability(
            id="a1", name="Agent", type="cli", tags=["general"],
            description="", enabled=True, timeout=5,
        )
        from agentmind.agents.cli_executor import CLIExecutor
        ex = CLIExecutor(cap)
        ex.is_healthy = True
        ex.execute_stream = _stream

        reg = _mock_registry({"a1": ex})
        ctx = RoutingContext(
            identity=RequestIdentity(trace_id="t1", user_id="u1"),
            raw_message="hello", candidates=["a1"],
        )
        decision = RoutingDecision(
            agent_id="a1", strategy="test", confidence=0.9,
            context=ctx,
        )
        recorder = _TaskServiceRecorder()
        monkeypatch.setattr("agentmind.routing.executors.single_agent.record_task_update", AsyncMock())
        monkeypatch.setattr("agentmind.routing.executors.single_agent.TaskService", lambda: recorder)
        monkeypatch.setattr("agentmind.routing.executors.base.MemoryWriter.write_task", AsyncMock())

        executor = SingleAgentExecutor(reg)
        chunks = []
        async for chunk in executor.run_text(decision, "t1", "u1"):
            chunks.append(chunk)

        assert chunks == ["chunk1", "chunk2"]
        assert recorder.calls == [
            {"trace_id": "t1", "agent_id": "a1", "content": "chunk1", "chunk_index": 1},
            {"trace_id": "t1", "agent_id": "a1", "content": "chunk2", "chunk_index": 2},
        ]
```

- [ ] **Step 2: Run executor RED**

Run:

```bash
pytest tests/test_pipeline_executors.py::TestSingleAgentStreamFallback::test_run_stream_records_partial_output_events tests/test_pipeline_executors.py::TestSingleAgentRunText::test_run_text_records_partial_output_events -q
```

Expected: FAIL because `single_agent.TaskService` is not imported or because calls are not recorded.

### Task 4: Wire SingleAgentExecutor Partial Output

**Files:**
- Modify: `src/agentmind/routing/executors/single_agent.py`
- Test: `tests/test_pipeline_executors.py`

- [ ] **Step 1: Import TaskService**

Add:

```python
from agentmind.services.task_service import TaskService
```

- [ ] **Step 2: Record partial chunks in `run_stream`**

Before the `for agent_id in chain:` loop, add:

```python
        chunk_index = 0
```

Inside the `StreamEventType.CONTENT` branch, before `yield chunk`, add:

```python
                    chunk_index += 1
                    await TaskService().record_partial_output(
                        trace_id,
                        agent_id=agent_id,
                        content=event.text,
                        chunk_index=chunk_index,
                    )
```

- [ ] **Step 3: Record text chunks in `run_text`**

Before the `for agent_id in chain:` loop, add:

```python
        chunk_index = 0
```

Inside the `StreamEventType.CONTENT` branch, before yielding direct text when no `response_path`, add:

```python
                    chunk_index += 1
                    await TaskService().record_partial_output(
                        trace_id,
                        agent_id=agent_id,
                        content=event.text,
                        chunk_index=chunk_index,
                    )
```

Do not record the extracted `response_path` result as `partial_output` in this package because it is produced after full buffered output, not as a live chunk.

- [ ] **Step 4: Run executor GREEN**

Run:

```bash
pytest tests/test_pipeline_executors.py::TestSingleAgentStreamFallback::test_run_stream_records_partial_output_events tests/test_pipeline_executors.py::TestSingleAgentRunText::test_run_text_records_partial_output_events -q
```

Expected: PASS.

### Task 5: Add SelfReply Producer Coverage

**Files:**
- Modify: `tests/test_pipeline_executors.py`
- Modify: `src/agentmind/routing/executors/self_reply.py`

- [ ] **Step 1: Add self-reply RED tests**

Add tests near existing self-reply tests:

```python
@pytest.mark.asyncio
async def test_self_reply_run_stream_records_partial_output_event(monkeypatch):
    recorder = _TaskServiceRecorder()
    decision = _make_decision(agent_id="agentmind", fallback_chain=[], reply_text="self reply")
    monkeypatch.setattr("agentmind.routing.executors.self_reply.record_task_update", AsyncMock())
    monkeypatch.setattr("agentmind.routing.executors.self_reply.TaskService", lambda: recorder)
    monkeypatch.setattr("agentmind.routing.executors.base.MemoryWriter.write_task", AsyncMock())

    executor = SelfReplyExecutor(_mock_registry({}))
    async for _chunk in executor.run_stream(decision, "t1", "u1"):
        pass

    assert recorder.calls == [
        {"trace_id": "t1", "agent_id": "agentmind", "content": "self reply", "chunk_index": 1}
    ]


@pytest.mark.asyncio
async def test_self_reply_run_text_records_partial_output_event(monkeypatch):
    recorder = _TaskServiceRecorder()
    decision = _make_decision(agent_id="agentmind", fallback_chain=[], reply_text="self reply")
    monkeypatch.setattr("agentmind.routing.executors.self_reply.record_task_update", AsyncMock())
    monkeypatch.setattr("agentmind.routing.executors.self_reply.TaskService", lambda: recorder)
    monkeypatch.setattr("agentmind.routing.executors.base.MemoryWriter.write_task", AsyncMock())

    executor = SelfReplyExecutor(_mock_registry({}))
    chunks = []
    async for chunk in executor.run_text(decision, "t1", "u1"):
        chunks.append(chunk)

    assert chunks == ["self reply"]
    assert recorder.calls == [
        {"trace_id": "t1", "agent_id": "agentmind", "content": "self reply", "chunk_index": 1}
    ]
```

Run:

```bash
pytest tests/test_pipeline_executors.py::test_self_reply_run_stream_records_partial_output_event tests/test_pipeline_executors.py::test_self_reply_run_text_records_partial_output_event -q
```

Expected: FAIL because `self_reply.TaskService` is not imported or calls are not recorded.

- [ ] **Step 2: Import and call TaskService in self-reply executor**

In `src/agentmind/routing/executors/self_reply.py`, add:

```python
from agentmind.services.task_service import TaskService
```

In `run_stream`, before yielding the `partial` event, add:

```python
        await TaskService().record_partial_output(
            trace_id,
            agent_id="agentmind",
            content=reply,
            chunk_index=1,
        )
```

In `run_text`, before `yield reply`, add the same call.

- [ ] **Step 3: Run self-reply GREEN**

Run:

```bash
pytest tests/test_pipeline_executors.py::test_self_reply_run_stream_records_partial_output_event tests/test_pipeline_executors.py::test_self_reply_run_text_records_partial_output_event -q
```

Expected: PASS.

### Task 6: Update Observability Docs

**Files:**
- Modify: `docs/observability/task-event-readiness.md`
- Modify: `docs/observability/task-event-replay-readiness.md`

- [ ] **Step 1: Update task-event readiness**

Replace:

```markdown
TaskEventService is not yet wired into partial output capture, persistent task-event replay, observability UI, stream runtime, panel/API/channel adapters, or routing behavior beyond TaskService lifecycle production.
```

with:

```markdown
TaskService now produces `partial_output` task events for streaming executor output through TaskEventService.

`partial_output` payloads contain structured metadata and a bounded preview. They are persisted task timeline events, not raw stream queue objects.

TaskEventService is not wired into persistent task-event replay runtime, observability UI, stream runtime replay, channel adapters, or routing behavior beyond TaskService event production.
```

- [ ] **Step 2: Update replay readiness**

Add to Existing Boundaries:

```markdown
Persisted `partial_output` events may appear in TaskTimelineService and TaskReplayService DTOs through the existing task-event timeline query path.
```

Add to Explicit Non-Goals:

```markdown
- no live SSE listener queue persistence or restoration;
```

- [ ] **Step 3: Run docs focused tests**

Run:

```bash
pytest tests/test_observability_task_event_readiness.py tests/test_task_event_replay_readiness.py -q
```

Expected: PASS.

### Task 7: Run Required Regression Gates

**Files:**
- Read: all modified files

- [ ] **Step 1: Run focused tests**

Run:

```bash
pytest tests/test_task_service.py::test_task_service_produces_partial_output_event tests/test_task_service.py::test_task_service_truncates_partial_output_preview tests/test_task_service.py::test_task_service_ignores_partial_output_event_failures tests/test_pipeline_executors.py::TestSingleAgentStreamFallback::test_run_stream_records_partial_output_events tests/test_pipeline_executors.py::TestSingleAgentRunText::test_run_text_records_partial_output_events tests/test_pipeline_executors.py::test_self_reply_run_stream_records_partial_output_event tests/test_pipeline_executors.py::test_self_reply_run_text_records_partial_output_event -q
```

Expected: PASS.

- [ ] **Step 2: Run observability/service gate**

Run:

```bash
pytest tests/test_task_service.py tests/test_task_event_service.py tests/test_task_timeline_service.py tests/test_task_replay_service.py tests/test_task_event_replay_readiness.py tests/test_observability_task_event_readiness.py tests/test_task_replay_adapter_readiness.py -q
```

Expected: PASS.

- [ ] **Step 3: Run panel/architecture gate**

Run:

```bash
pytest tests/test_panel_api.py tests/test_panel_control_plane_boundary.py tests/test_phase5_closure_audit.py -q
```

Expected: PASS.

- [ ] **Step 4: Run router/panel regression**

Run:

```bash
pytest tests/test_router.py tests/test_panel_api.py tests/test_feishu_path.py tests/test_e2e_scenarios.py tests/test_pipeline_executors.py -q
```

Expected: PASS.

- [ ] **Step 5: Run full verification**

Run:

```bash
pytest -q
git diff --check
git status --short
```

Expected: pytest PASS, diff check clean, status shows only intended changed files before commit.

- [ ] **Step 6: Commit**

Run:

```bash
git add src/agentmind/services/task_service.py src/agentmind/routing/executors/single_agent.py src/agentmind/routing/executors/self_reply.py tests/test_task_service.py tests/test_pipeline_executors.py docs/observability/task-event-readiness.md docs/observability/task-event-replay-readiness.md docs/superpowers/plans/2026-05-28-task-event-partial-output-producer.md
git commit -m "feat: record partial output task events"
```

Expected: commit succeeds.

## Self-Review

- Spec coverage: the plan adds persisted `partial_output` task events through TaskService and streaming executors.
- Placeholder scan: no TBD/TODO/implement-later placeholders remain.
- Scope check: no stream runtime replay, live SSE listener persistence, stream snapshot change, panel/API/channel timeline assembly, replay runtime, UI, governance enforcement, customer-content inspection, TaskEventService schema change, TaskTimelineService ordering/query change, or old fallback expansion is included.
