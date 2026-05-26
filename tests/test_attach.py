"""Attach 深度接管测试"""
import tempfile
from pathlib import Path

import pytest
import yaml


class TestAttachRegistry:
    def test_bind_and_get(self):
        from agentmind.api.attach_registry import AttachRegistry
        reg = AttachRegistry()
        reg.bind("session-1", "tr-abc")
        assert reg.get_bound_task("session-1") == "tr-abc"

    def test_get_not_bound(self):
        from agentmind.api.attach_registry import AttachRegistry
        reg = AttachRegistry()
        assert reg.get_bound_task("nonexistent") is None

    def test_unbind(self):
        from agentmind.api.attach_registry import AttachRegistry
        reg = AttachRegistry()
        reg.bind("s1", "t1")
        reg.unbind("t1")
        assert reg.get_bound_task("s1") is None

    def test_rebind_overwrites(self):
        from agentmind.api.attach_registry import AttachRegistry
        reg = AttachRegistry()
        reg.bind("s1", "t1")
        reg.bind("s1", "t2")
        assert reg.get_bound_task("s1") == "t2"


class TestAttachAPI:
    def test_attach_bind_endpoint(self):
        """绑定端点正常工作"""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            mp = pytest.MonkeyPatch()
            mp.setattr("agentmind.storage.db.DATA_HOME", tmp_dir)
            mp.setattr("agentmind.storage.db.DATA_DIR", tmp_dir / "data")
            mp.setattr("agentmind.storage.db.CONFIG_DIR", tmp_dir / "config")
            mp.setattr("agentmind.storage.db.LOGS_DIR", tmp_dir / "logs")
            (tmp_dir / "data" / "results").mkdir(parents=True, exist_ok=True)
            (tmp_dir / "config").mkdir(parents=True, exist_ok=True)

            from agentmind.storage.db import initialize_data_directory
            initialize_data_directory()

            agents_config = {"agents": [{"id": "test", "name": "Test", "type": "cli", "tags": [], "enabled": True, "timeout": 5, "config": {"command": "echo done", "health_check": "echo ok"}}]}
            (tmp_dir / "config" / "agents.yaml").write_text(yaml.dump(agents_config), encoding="utf-8")
            (tmp_dir / "config" / "routes.yaml").write_text(yaml.dump({"rules": []}), encoding="utf-8")

            from agentmind.main import create_app
            app = create_app(0)
            token = app.state.auth_token
            app.state.attach_registry.bind("s-test", "tr-test")

            from fastapi.testclient import TestClient
            client = TestClient(app)
            # 无 session_id
            resp = client.post("/panel/api/tasks/tr-abc/attach", headers={"Authorization": f"Bearer {token}"})
            data = resp.json()
            assert "error" in data

            # 有 session_id
            resp = client.post(f"/panel/api/tasks/tr-xyz/attach?session_id=s-new", headers={"Authorization": f"Bearer {token}"})
            data = resp.json()
            assert data["status"] == "attached"
            assert app.state.attach_registry.get_bound_task("s-new") == "tr-xyz"

            mp.undo()


class TestAttachDB:
    def test_record_attached_turn(self):
        import asyncio
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            mp = pytest.MonkeyPatch()
            mp.setattr("agentmind.storage.db.DATA_HOME", tmp_dir)
            mp.setattr("agentmind.storage.db.DATA_DIR", tmp_dir / "data")
            mp.setattr("agentmind.storage.db.CONFIG_DIR", tmp_dir / "config")
            mp.setattr("agentmind.storage.db.LOGS_DIR", tmp_dir / "logs")
            (tmp_dir / "data" / "results").mkdir(parents=True, exist_ok=True)
            (tmp_dir / "config").mkdir(parents=True, exist_ok=True)

            from agentmind.storage.db import initialize_data_directory, record_attached_turn
            initialize_data_directory()

            asyncio.run(record_attached_turn("tr-001", "hello", "world"))
            # 不抛异常即通过
            mp.undo()
