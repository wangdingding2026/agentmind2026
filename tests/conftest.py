import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
import yaml

from agentmind.agents.base import AgentCapability
from agentmind.agents.cli_executor import CLIExecutor
from agentmind.agents.registry import AgentRegistry
from agentmind.core.rule_engine import RuleEngine
from agentmind.storage.db import initialize_data_directory


@pytest.fixture
def tmp_dir():
    """临时目录，测试后自动清理"""
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture(autouse=True)
def isolated_agentmind_home(tmp_path, monkeypatch):
    """默认隔离 AgentMind 数据目录，防止测试写入真实 ~/.agentmind。"""
    home = tmp_path / ".agentmind"
    data_dir = home / "data"
    config_dir = home / "config"
    logs_dir = home / "logs"
    (data_dir / "results").mkdir(parents=True, exist_ok=True)
    config_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr("agentmind.storage.db.DATA_HOME", home)
    monkeypatch.setattr("agentmind.storage.db.DATA_DIR", data_dir)
    monkeypatch.setattr("agentmind.storage.db.CONFIG_DIR", config_dir)
    monkeypatch.setattr("agentmind.storage.db.LOGS_DIR", logs_dir)
    monkeypatch.setattr("agentmind.core.core_llm.CONFIG_DIR", config_dir)
    monkeypatch.setattr("agentmind.config.defaults.CONFIG_DIR", config_dir)
    monkeypatch.setattr("agentmind.api.orchestration.CONFIG_DIR", config_dir)
    monkeypatch.setattr("agentmind.panel.server.CONFIG_DIR", config_dir)

    initialize_data_directory()


@pytest.fixture
def tmp_db(tmp_dir, monkeypatch):
    """临时数据库，monkeypatch DATA_DIR 使 DB 操作在临时目录"""
    monkeypatch.setattr("agentmind.storage.db.DATA_DIR", tmp_dir / "data")
    monkeypatch.setattr("agentmind.storage.db.DATA_HOME", tmp_dir)
    monkeypatch.setattr("agentmind.storage.db.CONFIG_DIR", tmp_dir / "config")
    monkeypatch.setattr("agentmind.storage.db.LOGS_DIR", tmp_dir / "logs")
    (tmp_dir / "data" / "results").mkdir(parents=True, exist_ok=True)
    initialize_data_directory()
    return tmp_dir


@pytest.fixture
def routes_yaml(tmp_dir):
    """测试用路由规则文件"""
    config = {
        "rules": [
            {"name": "code_kw", "type": "keyword", "patterns": ["写一个", "代码"], "target_tags": ["code"], "priority": 10, "tags": ["code"]},
            {"name": "search_kw", "type": "keyword", "patterns": ["搜索", "查一下"], "target_tags": ["general"], "priority": 10, "tags": ["general"]},
            {"name": "bad_regex", "type": "regex", "patterns": ["[invalid"], "target_tags": ["code"], "priority": 5, "tags": ["code"]},
        ]
    }
    path = tmp_dir / "routes.yaml"
    path.write_text(yaml.dump(config, allow_unicode=True), encoding="utf-8")
    return path


@pytest.fixture
def agents_yaml(tmp_dir):
    """测试用 Agent 配置文件"""
    config = {
        "agents": [
            {"id": "test_cli", "name": "Test CLI", "type": "cli", "tags": ["code", "test"], "enabled": True, "timeout": 5,
             "config": {"command": "echo '{instruction}'", "health_check": "echo ok"}},
            {"id": "test_general", "name": "Test General", "type": "cli", "tags": ["general", "test"], "enabled": True, "timeout": 5,
             "config": {"command": "echo '{instruction}'", "health_check": "echo ok"}},
            {"id": "test_api", "name": "Test API", "type": "api", "tags": ["general"], "enabled": True, "timeout": 5,
             "config": {"endpoint": "https://agent.example.test/api", "method": "POST"}},
        ]
    }
    path = tmp_dir / "agents.yaml"
    path.write_text(yaml.dump(config, allow_unicode=True), encoding="utf-8")
    return path


@pytest.fixture
def registry(agents_yaml):
    """AgentRegistry 实例"""
    return AgentRegistry(agents_yaml)


@pytest.fixture
def rule_engine(routes_yaml, registry):
    """RuleEngine 实例"""
    return RuleEngine(routes_yaml, agent_registry=registry)


@pytest.fixture
def app_client(tmp_db, agents_yaml, routes_yaml):
    """FastAPI TestClient"""
    from fastapi.testclient import TestClient
    from agentmind.main import create_app
    from agentmind.storage.db import DATA_HOME

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr("agentmind.storage.db.DATA_DIR", tmp_db / "data")
    monkeypatch.setattr("agentmind.storage.db.DATA_HOME", tmp_db)
    monkeypatch.setattr("agentmind.main.DATA_HOME", tmp_db)
    monkeypatch.setattr("agentmind.storage.db.CONFIG_DIR", tmp_db / "config")
    monkeypatch.setattr("agentmind.storage.db.LOGS_DIR", tmp_db / "logs")

    app = create_app(0)
    client = TestClient(app)
    yield client
    monkeypatch.undo()
