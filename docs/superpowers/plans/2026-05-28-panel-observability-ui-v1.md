# Panel Observability UI V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a minimal read-only panel task replay/timeline view that consumes the existing `/panel/api/tasks/{trace_id}/replay` endpoint.

**Architecture:** This package changes only the existing static panel page. The UI adds a replay action beside recent tasks, fetches the existing panel replay endpoint, and renders the returned `TaskReplayService` DTO. It does not add APIs, does not query task-event storage, does not call timeline services, and does not implement stream runtime replay.

**Tech Stack:** Static HTML/CSS/vanilla JS in `src/agentmind/panel/static/index.html`, pytest static UI audit tests.

---

## File Structure

- Create: `tests/test_panel_observability_ui.py`
  - Verifies the static panel has a replay/timeline panel, action button, API call, found/missing rendering hooks, and boundary-safe implementation.
- Modify: `src/agentmind/panel/static/index.html`
  - Adds a replay panel below recent tasks.
  - Adds a "回放" action to each recent task row.
  - Adds `loadTaskReplay(traceId)` and `renderTaskReplay(data)` helper functions.
  - Fetches only `/panel/api/tasks/{trace_id}/replay`.
- Modify: `docs/observability/observability-ui-readiness.md`
  - Updates readiness status to say Panel Observability UI V1 is implemented as a separate small package.
- Modify: `docs/observability/task-event-closeout-status.md`
  - Notes Panel Observability UI V1 is implemented via the existing replay endpoint.
- Modify: `docs/architecture/final-closeout-status.md`
  - Updates future work to defer only advanced observability UI beyond V1.

No backend API, service, storage, stream runtime, governance, or channel code should change in this package.

### Task 1: Add Panel Observability UI RED Test

**Files:**
- Create: `tests/test_panel_observability_ui.py`

- [ ] **Step 1: Write failing static UI tests**

Create `tests/test_panel_observability_ui.py`:

```python
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PANEL_HTML = PROJECT_ROOT / "src" / "agentmind" / "panel" / "static" / "index.html"
READINESS_DOC = (
    PROJECT_ROOT / "docs" / "observability" / "observability-ui-readiness.md"
)


REQUIRED_UI_MARKERS = {
    'id="task-replay-panel"',
    'id="task-replay-title"',
    'id="task-replay-content"',
    "loadTaskReplay(",
    "renderTaskReplay(",
    "formatReplayEvent(",
    "btn-task-replay",
    "/tasks/' + encodeURIComponent(traceId) + '/replay?limit=50",
    "任务回放",
    "未找到持久化任务事件",
    "partial_output",
}


FORBIDDEN_UI_MARKERS = {
    "TaskEventService",
    "TaskTimelineService",
    "stream_snapshot",
    "EventSource('/panel/api/tasks/'",
    "/panel/api/task-events",
}


def _panel_html() -> str:
    assert PANEL_HTML.exists(), "panel static index.html is required"
    return PANEL_HTML.read_text(encoding="utf-8")


def test_panel_observability_ui_static_page_contains_replay_view():
    html = _panel_html()
    missing = sorted(marker for marker in REQUIRED_UI_MARKERS if marker not in html)

    assert missing == []


def test_panel_observability_ui_does_not_bypass_replay_adapter_boundary():
    html = _panel_html()
    forbidden = sorted(marker for marker in FORBIDDEN_UI_MARKERS if marker in html)

    assert forbidden == []


def test_observability_ui_readiness_records_panel_v1_implementation():
    text = READINESS_DOC.read_text(encoding="utf-8")

    assert "Panel Observability UI V1 is implemented" in text
    assert "`/panel/api/tasks/{trace_id}/replay`" in text
```

- [ ] **Step 2: Run RED**

Run:

```bash
pytest tests/test_panel_observability_ui.py -q
```

Expected: FAIL because the panel static page does not yet include the replay view and readiness doc does not say V1 is implemented.

### Task 2: Implement Static Panel Replay View

**Files:**
- Modify: `src/agentmind/panel/static/index.html`

- [ ] **Step 1: Add replay panel markup**

After the recent tasks table, add:

```html
      <div id="task-replay-panel" class="config-card" hidden style="margin-top:0.5rem">
        <div style="display:flex;justify-content:space-between;align-items:center;gap:0.75rem">
          <h4 id="task-replay-title" style="margin:0;font-size:0.95rem">任务回放</h4>
          <button class="btn-outline" onclick="closeTaskReplay()" style="font-size:0.75rem;padding:0.1rem 0.5rem">关闭</button>
        </div>
        <div id="task-replay-content" style="margin-top:0.75rem;font-size:0.85rem;color:#334155"></div>
      </div>
```

- [ ] **Step 2: Add task replay action column**

Change recent tasks table header from:

```html
<thead><tr><th>时间</th><th>指令</th><th>Agent</th><th>状态</th><th>耗时</th></tr></thead>
```

to:

```html
<thead><tr><th>时间</th><th>指令</th><th>Agent</th><th>状态</th><th>耗时</th><th>回放</th></tr></thead>
```

In `loadAgents()`, update the task row render so each row ends with:

```javascript
+ '<td><button class="btn-outline btn-task-replay" data-trace-id="' + escapeHtml(t.trace_id || '') + '" style="font-size:0.75rem;padding:0.1rem 0.5rem">回放</button></td>'
```

and update the empty state colspan from 5 to 6.

- [ ] **Step 3: Add replay rendering functions**

Add near other utility functions:

```javascript
    async function loadTaskReplay(traceId) {
      if (!traceId) { showToast('缺少 trace_id', 'error'); return; }
      const panel = document.getElementById('task-replay-panel');
      const title = document.getElementById('task-replay-title');
      const content = document.getElementById('task-replay-content');
      panel.hidden = false;
      title.textContent = '任务回放 ' + traceId;
      content.innerHTML = '<div style="color:#94a3b8">加载中...</div>';
      const data = await fetchAPI('/tasks/' + encodeURIComponent(traceId) + '/replay?limit=50');
      renderTaskReplay(data);
    }

    function closeTaskReplay() {
      const panel = document.getElementById('task-replay-panel');
      if (panel) panel.hidden = true;
    }

    function renderTaskReplay(data) {
      const content = document.getElementById('task-replay-content');
      if (!content) return;
      if (!data) {
        content.innerHTML = '<div style="color:#f44336">回放加载失败</div>';
        return;
      }
      if (!data.found) {
        content.innerHTML = '<div style="color:#94a3b8">未找到持久化任务事件</div>';
        return;
      }
      const events = data.timeline || [];
      const header = '<div style="margin-bottom:0.5rem;color:#475569">状态：' + escapeHtml(data.replay_status || '-') + ' · 事件：' + escapeHtml(data.event_count) + ' · 来源：' + escapeHtml(data.source || '-') + '</div>';
      const rows = events.length ? events.map(formatReplayEvent).join('') : '<div style="color:#94a3b8">暂无事件</div>';
      content.innerHTML = header + '<div style="display:flex;flex-direction:column;gap:0.35rem">' + rows + '</div>';
    }

    function formatReplayEvent(event, index) {
      const eventType = event.event_type || '-';
      const isPartial = eventType === 'partial_output';
      const preview = event.payload && event.payload.preview ? event.payload.preview : '';
      const message = event.message || preview || '';
      const border = isPartial ? '#2196f3' : '#e2e8f0';
      return '<div style="border-left:3px solid ' + border + ';padding:0.4rem 0.6rem;background:#f8fafc;border-radius:4px">' +
        '<div style="font-size:0.78rem;color:#64748b">' + (index + 1) + '. ' + escapeHtml(event.created_at || '-') + ' · ' + escapeHtml(eventType) + (event.agent_id ? ' · ' + escapeHtml(event.agent_id) : '') + '</div>' +
        (message ? '<div style="margin-top:0.2rem;white-space:pre-wrap">' + escapeHtml(message).slice(0, 240) + '</div>' : '') +
      '</div>';
    }
```

- [ ] **Step 4: Add delegated click handler**

After the existing `agents-tbody` delegated handler, add:

```javascript
    document.getElementById('tasks-tbody').addEventListener('click', function(e) {
      const btn = e.target.closest('.btn-task-replay');
      if (btn) loadTaskReplay(btn.dataset.traceId);
    });
```

- [ ] **Step 5: Run GREEN focused**

Run:

```bash
pytest tests/test_panel_observability_ui.py -q
```

Expected: PASS after docs update in Task 3; if only UI is implemented at this point, UI marker tests pass and readiness status still fails until Task 3.

### Task 3: Update Docs and Regression Verification

**Files:**
- Modify: `docs/observability/observability-ui-readiness.md`
- Modify: `docs/observability/task-event-closeout-status.md`
- Modify: `docs/architecture/final-closeout-status.md`

- [ ] **Step 1: Update readiness status**

In `docs/observability/observability-ui-readiness.md`, replace:

```markdown
The UI implementation requires a separate small package.
```

with:

```markdown
Panel Observability UI V1 is implemented as a separate small package.
```

Add under `## UI Boundary`:

```markdown
Panel Observability UI V1 renders the existing replay DTO from `/panel/api/tasks/{trace_id}/replay`.

Panel Observability UI V1 remains read-only and does not add backend APIs.
```

- [ ] **Step 2: Update closeout docs**

In `docs/observability/task-event-closeout-status.md`, add:

```markdown
Panel Observability UI V1 is implemented through the existing `/panel/api/tasks/{trace_id}/replay` adapter.
```

In `docs/architecture/final-closeout-status.md`, change:

```markdown
- observability UI, after `docs/observability/observability-ui-readiness.md`;
```

to:

```markdown
- advanced observability UI beyond Panel Observability UI V1;
```

- [ ] **Step 3: Run focused docs/UI tests**

Run:

```bash
pytest tests/test_panel_observability_ui.py tests/test_observability_ui_readiness.py tests/test_task_event_closeout_audit.py tests/test_architecture_final_closeout_audit.py -q
```

Expected: PASS.

- [ ] **Step 4: Run panel/architecture regression**

Run:

```bash
pytest tests/test_panel_api.py tests/test_panel_control_plane_boundary.py tests/test_phase5_closure_audit.py tests/test_architecture_final_closeout_audit.py tests/test_panel_observability_ui.py -q
```

Expected: PASS.

- [ ] **Step 5: Run observability/service regression**

Run:

```bash
pytest tests/test_task_replay_service.py tests/test_task_timeline_service.py tests/test_task_event_service.py tests/test_channel_replay_service.py tests/test_observability_ui_readiness.py -q
```

Expected: PASS.

- [ ] **Step 6: Run router/panel regression**

Run:

```bash
pytest tests/test_router.py tests/test_panel_api.py tests/test_feishu_path.py tests/test_e2e_scenarios.py tests/test_pipeline_executors.py -q
```

Expected: PASS.

- [ ] **Step 7: Run full validation**

Run:

```bash
pytest -q
git diff --check
git status --short
```

Expected: full pytest PASS, whitespace check clean, and only intended files changed before commit.

- [ ] **Step 8: Commit**

Run:

```bash
git add src/agentmind/panel/static/index.html tests/test_panel_observability_ui.py docs/observability/observability-ui-readiness.md docs/observability/task-event-closeout-status.md docs/architecture/final-closeout-status.md docs/superpowers/plans/2026-05-28-panel-observability-ui-v1.md
git commit -m "feat: add panel observability replay view"
```

Expected: commit succeeds.

## Self-Review

- Spec coverage: this plan implements only the static panel replay/timeline view over the existing panel replay endpoint.
- Placeholder scan: no TBD, TODO, or open implementation placeholders.
- Scope check: no backend API, TaskEventService query, TaskTimelineService direct call, stream runtime replay, EventSource replay, API replay endpoint, channel UX expansion, governance enforcement, customer-content inspection, schema/query/order changes, or SessionRuntimeService changes are included.
