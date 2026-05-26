# AgentMind Phase 1 Service Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first Phase 1 service-layer package by adding `ConfigService` and `TaskService`, then migrating the lowest-risk callers while preserving existing behavior.

**Architecture:** Add thin services that wrap existing YAML and SQLite behavior before moving higher-level routing logic. Keep old public functions compatible so existing callers and tests keep working. Limit this package to configuration writes/reads and task lifecycle access; `main.py` slimming and `RoutingService` extraction remain later Phase 1 subpackages.

**Tech Stack:** Python 3.12, FastAPI, SQLite, PyYAML, pytest, pytest-asyncio.

---

## Current Baseline

- Phase 0 baseline commit: `5c101d7 test: stabilize phase 0 baseline`
- Full test suite is green before this package:

```bash
pytest -q
```

Expected baseline:

```text
333 passed, 4 warnings
```

## Files

Create:

- `src/agentmind/services/__init__.py`
- `src/agentmind/services/config_service.py`
- `src/agentmind/services/task_service.py`
- `tests/test_config_service.py`
- `tests/test_task_service.py`

Modify:

- `src/agentmind/storage/db.py`
- `src/agentmind/panel/server.py`
- `tests/test_panel_api.py`
- `docs/phase0/architecture-dependency-inventory.md`

Do not modify in this package:

- `src/agentmind/api/router.py`
- `src/agentmind/main.py`
- `src/agentmind/storage/memory.py`
- `src/agentmind/memory/service.py`

## Strict Testing Rules

Every production change follows RED-GREEN:

1. Add or update a focused failing test.
2. Run that exact test and confirm it fails for the expected reason.
3. Implement the smallest production change.
4. Run the exact test and confirm it passes.
5. Run the package verification command.
6. Commit the task.

Package verification commands:

```bash
pytest tests/test_config_service.py tests/test_task_service.py -q
pytest tests/test_db.py tests/test_panel_api.py tests/test_router.py -q
pytest -q
```

---

### Task 1: Add ConfigService

**Files:**

- Create: `tests/test_config_service.py`
- Create: `src/agentmind/services/__init__.py`
- Create: `src/agentmind/services/config_service.py`

- [ ] **Step 1: Write failing ConfigService tests**

Create `tests/test_config_service.py` with:

```python
from pathlib import Path

import yaml

from agentmind.services.config_service import ConfigService


def test_read_missing_config_returns_empty_dict(tmp_path):
    service = ConfigService(tmp_path / "config")

    assert service.read_settings() == {}
    assert service.read_agents() == {"agents": []}
    assert service.read_routes() == {"rules": []}
    assert service.read_orchestrations() == {"plans": []}


def test_update_settings_section_preserves_other_sections(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    settings_path = config_dir / "settings.yaml"
    settings_path.write_text(
        yaml.dump({
            "memory": {"max_entries": 100},
            "embedding": {"enabled": False},
        }),
        encoding="utf-8",
    )
    service = ConfigService(config_dir)

    saved = service.update_settings_sections({
        "memory": {"max_entries": 500},
    })

    assert saved["memory"]["max_entries"] == 500
    assert saved["embedding"]["enabled"] is False
    assert yaml.safe_load(settings_path.read_text(encoding="utf-8")) == saved


def test_write_routes_rejects_non_list_rules(tmp_path):
    service = ConfigService(tmp_path / "config")

    try:
        service.write_routes({"rules": "not-a-list"})
    except ValueError as exc:
        assert "rules must be a list" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_mask_sensitive_config_values(tmp_path):
    service = ConfigService(tmp_path / "config")

    masked = service.mask_sensitive({
        "api_key": "sk-test",
        "nested": {"app_secret": "secret", "safe": "value"},
        "items": [{"token": "abc"}],
    })

    assert masked["api_key"] == "****"
    assert masked["nested"]["app_secret"] == "****"
    assert masked["nested"]["safe"] == "value"
    assert masked["items"][0]["token"] == "****"
```

- [ ] **Step 2: Verify RED**

Run:

```bash
pytest tests/test_config_service.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'agentmind.services'`.

- [ ] **Step 3: Implement ConfigService**

Create `src/agentmind/services/__init__.py`:

```python
"""Application services for AgentMind."""
```

Create `src/agentmind/services/config_service.py`:

```python
from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import yaml

from agentmind.storage.db import CONFIG_DIR


_SENSITIVE_KEYS = {"api_key", "token", "secret", "authorization", "password"}


class ConfigService:
    """Synchronous YAML configuration service.

    This first Phase 1 version intentionally stays small. It centralizes YAML
    reading, writing, validation, and masking without changing runtime behavior.
    """

    def __init__(self, config_dir: Path | None = None):
        self.config_dir = Path(config_dir) if config_dir is not None else CONFIG_DIR
        self._lock = threading.RLock()

    @property
    def settings_path(self) -> Path:
        return self.config_dir / "settings.yaml"

    @property
    def agents_path(self) -> Path:
        return self.config_dir / "agents.yaml"

    @property
    def routes_path(self) -> Path:
        return self.config_dir / "routes.yaml"

    @property
    def orchestrations_path(self) -> Path:
        return self.config_dir / "orchestrations.yaml"

    def read_settings(self) -> dict[str, Any]:
        return self._read_yaml(self.settings_path, {})

    def read_agents(self) -> dict[str, Any]:
        data = self._read_yaml(self.agents_path, {"agents": []})
        agents = data.get("agents", [])
        if not isinstance(agents, list):
            agents = []
        data["agents"] = agents
        return data

    def read_routes(self) -> dict[str, Any]:
        data = self._read_yaml(self.routes_path, {"rules": []})
        rules = data.get("rules", [])
        if not isinstance(rules, list):
            rules = []
        data["rules"] = rules
        return data

    def read_orchestrations(self) -> dict[str, Any]:
        data = self._read_yaml(self.orchestrations_path, {"plans": []})
        plans = data.get("plans", [])
        if not isinstance(plans, list):
            plans = []
        data["plans"] = plans
        return data

    def write_settings(self, data: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(data, dict):
            raise ValueError("settings must be a dict")
        return self._write_yaml(self.settings_path, data)

    def update_settings_sections(self, sections: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(sections, dict):
            raise ValueError("settings sections must be a dict")
        with self._lock:
            data = self.read_settings()
            data.update(sections)
            return self.write_settings(data)

    def write_agents(self, data: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(data, dict):
            raise ValueError("agents config must be a dict")
        agents = data.get("agents", [])
        if not isinstance(agents, list):
            raise ValueError("agents must be a list")
        return self._write_yaml(self.agents_path, data)

    def write_routes(self, data: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(data, dict):
            raise ValueError("routes config must be a dict")
        rules = data.get("rules", [])
        if not isinstance(rules, list):
            raise ValueError("rules must be a list")
        return self._write_yaml(self.routes_path, data)

    def write_orchestrations(self, data: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(data, dict):
            raise ValueError("orchestrations config must be a dict")
        plans = data.get("plans", [])
        if not isinstance(plans, list):
            raise ValueError("plans must be a list")
        return self._write_yaml(self.orchestrations_path, data)

    def mask_sensitive(self, value: Any) -> Any:
        if isinstance(value, dict):
            masked = {}
            for key, item in value.items():
                key_lower = str(key).lower()
                if key_lower in _SENSITIVE_KEYS or any(part in key_lower for part in _SENSITIVE_KEYS):
                    masked[key] = "****"
                else:
                    masked[key] = self.mask_sensitive(item)
            return masked
        if isinstance(value, list):
            return [self.mask_sensitive(item) for item in value]
        return value

    def _read_yaml(self, path: Path, default: dict[str, Any]) -> dict[str, Any]:
        if not path.exists():
            return dict(default)
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            raise ValueError(f"invalid YAML in {path.name}: {exc}") from exc
        if not isinstance(data, dict):
            return dict(default)
        return data

    def _write_yaml(self, path: Path, data: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                yaml.dump(data, allow_unicode=True, default_flow_style=False, sort_keys=False),
                encoding="utf-8",
            )
            return data
```

- [ ] **Step 4: Verify GREEN**

Run:

```bash
pytest tests/test_config_service.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add src/agentmind/services/__init__.py src/agentmind/services/config_service.py tests/test_config_service.py
git commit -m "feat: add config service"
```

---

### Task 2: Add TaskService and keep storage compatibility

**Files:**

- Create: `tests/test_task_service.py`
- Create: `src/agentmind/services/task_service.py`
- Modify: `src/agentmind/storage/db.py`

- [ ] **Step 1: Write failing TaskService tests**

Create `tests/test_task_service.py` with:

```python
import pytest

from agentmind.services.task_service import TaskService


@pytest.mark.asyncio
async def test_task_service_records_lifecycle(tmp_db):
    service = TaskService()

    await service.start_task("tr-service-1", "hello")
    await service.mark_routing("tr-service-1", matched_rule="rule", routed_agent="agent-a")
    await service.mark_executing("tr-service-1")
    await service.complete_task("tr-service-1", "agent-a", result="done", execution_time_ms=12)

    detail = await service.get_task_detail("tr-service-1")
    assert detail["trace_id"] == "tr-service-1"
    assert detail["status"] == "completed"
    assert detail["matched_rule"] == "rule"
    assert detail["routed_agent"] == "agent-a"
    assert detail["result_summary"] == "done"


@pytest.mark.asyncio
async def test_task_service_records_failure(tmp_db):
    service = TaskService()

    await service.start_task("tr-service-2", "hello")
    await service.fail_task("tr-service-2", "agent-a", error_message="boom", execution_time_ms=4)

    detail = await service.get_task_detail("tr-service-2")
    assert detail["status"] == "failed"
    assert detail["routed_agent"] == "agent-a"
    assert detail["error_message"] == "boom"


@pytest.mark.asyncio
async def test_storage_functions_delegate_to_task_service(tmp_db, monkeypatch):
    calls = []

    class FakeTaskService:
        async def start_task(self, trace_id, user_message):
            calls.append(("start", trace_id, user_message))

        async def update_task(self, trace_id, status, matched_rule=None, routed_agent=None):
            calls.append(("update", trace_id, status, matched_rule, routed_agent))

        async def end_task(
            self,
            trace_id,
            status,
            agent_id=None,
            execution_time_ms=None,
            result=None,
            error_message=None,
        ):
            calls.append(("end", trace_id, status, agent_id, execution_time_ms, result, error_message))

    monkeypatch.setattr("agentmind.storage.db.TaskService", FakeTaskService)

    from agentmind.storage.db import record_task_start, record_task_update, record_task_end

    await record_task_start("tr-compat", "msg")
    await record_task_update("tr-compat", "routing", matched_rule="rule", routed_agent="agent")
    await record_task_end("tr-compat", "completed", "agent", 5, result="ok")

    assert calls == [
        ("start", "tr-compat", "msg"),
        ("update", "tr-compat", "routing", "rule", "agent"),
        ("end", "tr-compat", "completed", "agent", 5, "ok", None),
    ]
```

- [ ] **Step 2: Verify RED**

Run:

```bash
pytest tests/test_task_service.py -q
```

Expected: FAIL with `ModuleNotFoundError` or import error for `agentmind.services.task_service`.

- [ ] **Step 3: Implement TaskService**

Create `src/agentmind/services/task_service.py`:

```python
from __future__ import annotations

import asyncio

from agentmind.storage import db as storage_db


class TaskService:
    """Task lifecycle service.

    This first version wraps the existing storage implementation. It creates a
    stable service seam without changing the SQLite schema or public behavior.
    """

    async def start_task(self, trace_id: str, user_message: str):
        await asyncio.to_thread(storage_db._record_task_start_sync, trace_id, user_message)

    async def update_task(
        self,
        trace_id: str,
        status: str,
        matched_rule: str | None = None,
        routed_agent: str | None = None,
    ):
        await asyncio.to_thread(
            storage_db._record_task_update_sync,
            trace_id,
            status,
            matched_rule,
            routed_agent,
        )

    async def mark_routing(
        self,
        trace_id: str,
        matched_rule: str | None = None,
        routed_agent: str | None = None,
    ):
        await self.update_task(trace_id, "routing", matched_rule, routed_agent)

    async def mark_executing(self, trace_id: str, routed_agent: str | None = None):
        await self.update_task(trace_id, "executing", routed_agent=routed_agent)

    async def end_task(
        self,
        trace_id: str,
        status: str,
        agent_id: str | None = None,
        execution_time_ms: int | None = None,
        result: str | None = None,
        error_message: str | None = None,
    ):
        await asyncio.to_thread(
            storage_db._save_result_sync,
            trace_id,
            status,
            agent_id,
            execution_time_ms,
            result,
            error_message,
        )

    async def complete_task(
        self,
        trace_id: str,
        agent_id: str | None = None,
        result: str | None = None,
        execution_time_ms: int | None = None,
    ):
        await self.end_task(
            trace_id,
            "completed",
            agent_id,
            execution_time_ms=execution_time_ms,
            result=result,
        )

    async def fail_task(
        self,
        trace_id: str,
        agent_id: str | None = None,
        error_message: str | None = None,
        execution_time_ms: int | None = None,
    ):
        await self.end_task(
            trace_id,
            "failed",
            agent_id,
            execution_time_ms=execution_time_ms,
            error_message=error_message,
        )

    async def record_attached_turn(self, trace_id: str, user_message: str, agent_response: str):
        await asyncio.to_thread(
            storage_db._record_attached_turn_sync,
            trace_id,
            user_message,
            agent_response,
        )

    async def query_tasks(self, limit: int = 20, offset: int = 0, status: str | None = None) -> list[dict]:
        return await asyncio.to_thread(storage_db._query_tasks_sync, limit, offset, status)

    async def get_task_stats(self) -> dict:
        return await asyncio.to_thread(storage_db._get_task_stats_sync)

    async def get_task_detail(self, trace_id: str) -> dict | None:
        return await asyncio.to_thread(storage_db._get_task_detail_sync, trace_id)

    async def get_recent_errors(self, limit: int = 5) -> list[dict]:
        return await asyncio.to_thread(storage_db._get_recent_errors_sync, limit)

    async def get_metrics(self) -> dict:
        return await asyncio.to_thread(storage_db._get_metrics_sync)
```

Modify `src/agentmind/storage/db.py`:

Add near imports:

```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agentmind.services.task_service import TaskService as TaskService
```

Add helper near task functions:

```python
def _task_service():
    from agentmind.services.task_service import TaskService
    return TaskService()
```

Then update async compatibility functions:

```python
async def record_task_start(trace_id: str, user_message: str):
    await _task_service().start_task(trace_id, user_message)
```

```python
async def record_task_update(trace_id: str, status: str, matched_rule: str = None, routed_agent: str = None):
    await _task_service().update_task(trace_id, status, matched_rule, routed_agent)
```

```python
async def record_task_end(
    trace_id: str,
    status: str,
    agent_id: str = None,
    execution_time_ms: int = None,
    result: str = None,
    error_message: str = None,
):
    await _task_service().end_task(
        trace_id,
        status,
        agent_id,
        execution_time_ms,
        result,
        error_message,
    )
```

```python
async def record_attached_turn(trace_id: str, user_message: str, agent_response: str):
    await _task_service().record_attached_turn(trace_id, user_message, agent_response)
```

Keep all synchronous functions unchanged. Do not change schema.

- [ ] **Step 4: Verify GREEN**

Run:

```bash
pytest tests/test_task_service.py tests/test_db.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add src/agentmind/services/task_service.py src/agentmind/storage/db.py tests/test_task_service.py
git commit -m "feat: add task service compatibility layer"
```

---

### Task 3: Migrate panel configuration writes to ConfigService

**Files:**

- Modify: `src/agentmind/panel/server.py`
- Modify: `tests/test_panel_api.py`

- [ ] **Step 1: Add failing panel tests proving ConfigService is used**

Append to `tests/test_panel_api.py`:

```python
class TestPanelConfigServiceUsage:
    def test_settings_save_uses_config_service(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            app, mp = make_panel_app(tmp_dir)
            client = TestClient(app)
            calls = []

            class FakeConfigService:
                def __init__(self, config_dir=None):
                    self.config_dir = config_dir

                def read_settings(self):
                    return {"memory": {"max_entries": 10000}}

                def update_settings_sections(self, sections):
                    calls.append(sections)
                    return {"memory": {"max_entries": 321}}

            try:
                mp.setattr("agentmind.panel.server.ConfigService", FakeConfigService)
                resp = client.post("/panel/api/settings", json={
                    "memory": {"max_entries": 321},
                })
                assert resp.status_code == 200
                assert resp.json()["ok"] is True
                assert calls == [{"memory": {"max_entries": 321}}]
            finally:
                mp.undo()

    def test_rules_save_uses_config_service(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            app, mp = make_panel_app(tmp_dir)
            client = TestClient(app)
            writes = []

            class FakeConfigService:
                def __init__(self, config_dir=None):
                    self.config_dir = config_dir

                def read_routes(self):
                    return {"rules": []}

                def write_routes(self, data):
                    writes.append(data)
                    return data

            try:
                mp.setattr("agentmind.panel.server.ConfigService", FakeConfigService)
                resp = client.post("/panel/api/rules", json={
                    "name": "route-a",
                    "type": "keyword",
                    "patterns": ["hello"],
                    "target_tags": ["general"],
                    "priority": 10,
                    "tags": ["demo"],
                })
                assert resp.status_code == 200
                assert resp.json()["ok"] is True
                assert writes == [{
                    "rules": [{
                        "name": "route-a",
                        "type": "keyword",
                        "patterns": ["hello"],
                        "target_tags": ["general"],
                        "priority": 10,
                        "tags": ["demo"],
                    }]
                }]
            finally:
                mp.undo()
```

- [ ] **Step 2: Verify RED**

Run:

```bash
pytest tests/test_panel_api.py::TestPanelConfigServiceUsage -q
```

Expected: FAIL because `agentmind.panel.server.ConfigService` is not imported/used.

- [ ] **Step 3: Migrate selected panel config operations**

Modify `src/agentmind/panel/server.py`:

Add import near existing imports:

```python
from agentmind.services.config_service import ConfigService
```

Keep `_mask_config` for compatibility or replace its internals with:

```python
def _mask_config(config: dict) -> dict:
    """脱敏敏感配置字段，只返回 masked 值"""
    return ConfigService(CONFIG_DIR).mask_sensitive(config)
```

Update these endpoints to use `ConfigService(CONFIG_DIR)`:

- `feishu_get_config`: `data = ConfigService(CONFIG_DIR).read_settings()`
- `feishu_save_config`: `ConfigService(CONFIG_DIR).update_settings_sections({"feishu": {...}})`
- `feishu_connect`: persist Feishu config via `update_settings_sections`, then update `request.app.state.settings["feishu"]`
- `feishu_disconnect`: read settings, set `feishu.enabled = False`, write full settings via `write_settings`
- `list_rules`: `data = ConfigService(CONFIG_DIR).read_routes()`
- `save_rule`: read routes, update list, `write_routes`
- `delete_rule`: read routes, filter list, `write_routes`
- `get_settings`: `data = ConfigService(CONFIG_DIR).read_settings()`
- `save_settings`: build `sections` from body keys and call `update_settings_sections`
- `embedding_status`: `data = ConfigService(CONFIG_DIR).read_settings()`

Do not migrate agent add/toggle/tag endpoints in this task. They require runtime
registry coordination and should be handled by a later `AgentService` task.

- [ ] **Step 4: Verify GREEN**

Run:

```bash
pytest tests/test_panel_api.py::TestPanelConfigServiceUsage tests/test_panel_api.py::TestSettings tests/test_panel_api.py::TestFeishu tests/test_panel_api.py::TestEmbeddingStatus -q
```

Expected: PASS.

- [ ] **Step 5: Run broader panel regression**

Run:

```bash
pytest tests/test_panel_api.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

```bash
git add src/agentmind/panel/server.py tests/test_panel_api.py
git commit -m "refactor: route panel config writes through config service"
```

---

### Task 4: Document Phase 1 status and run package verification

**Files:**

- Modify: `docs/phase0/architecture-dependency-inventory.md`

- [ ] **Step 1: Update inventory with completed Phase 1 package**

Append this section to `docs/phase0/architecture-dependency-inventory.md`:

```markdown

## Phase 1 Service Layer Package 1 Status

Completed in the first Phase 1 package:

- Added `ConfigService` as a central YAML read/write/masking service.
- Added `TaskService` as a task lifecycle service wrapping the existing SQLite storage implementation.
- Kept old `record_task_*` and `record_attached_turn` APIs compatible through `TaskService`.
- Migrated panel settings, Feishu config, route rules, and embedding status config reads/writes to `ConfigService`.

Deferred intentionally:

- Agent config writes in panel remain direct until `AgentService` exists.
- `main.py` startup decomposition remains a later Phase 1 subpackage.
- `/v1/route` main request flow remains a later Phase 1 `RoutingService` subpackage.
- Memory service unification remains Phase 2.
```

- [ ] **Step 2: Run package verification**

Run:

```bash
pytest tests/test_config_service.py tests/test_task_service.py -q
pytest tests/test_db.py tests/test_panel_api.py tests/test_router.py -q
pytest -q
```

Expected:

```text
All commands pass.
Full suite: 333+ tests passed, 0 failed, warnings allowed if unchanged.
```

- [ ] **Step 3: Commit**

Run:

```bash
git add docs/phase0/architecture-dependency-inventory.md
git commit -m "docs: record phase 1 service layer checkpoint"
```

## Self-Review

- Spec coverage: Covers Phase 1 package 1 only: `ConfigService`, `TaskService`, compatibility delegation, and panel config write migration.
- Intentional gaps: `main.py` slimming, `RoutingService`, `AgentService`, memory unification, trace split, and startup modules are deferred to later packages.
- Placeholder scan: No placeholder tasks; every production change has a RED/GREEN verification step.
- Type consistency: `ConfigService` and `TaskService` method names are consistent across tests, implementation, and migration steps.
