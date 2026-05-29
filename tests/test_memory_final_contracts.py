from pathlib import Path


def test_memory_write_command_defaults_are_stable():
    from agentmind.memory.dto import MemoryWriteCommand

    cmd = MemoryWriteCommand(content="hello")

    assert cmd.content == "hello"
    assert cmd.summary == ""
    assert cmd.memory_type == "episodic"
    assert cmd.access_level == "shared"
    assert cmd.source_kind == "task"
    assert cmd.tags == []


def test_memory_context_defaults_are_stable():
    from agentmind.memory.dto import MemoryContext

    ctx = MemoryContext(assembled_context="context")

    assert ctx.assembled_context == "context"
    assert ctx.working_memory == []
    assert ctx.recall_items == []
    assert ctx.result_set_id == ""
    assert ctx.steps == []
    assert ctx.truncated is False


def test_memory_audit_report_defaults_are_stable():
    from agentmind.memory.dto import MemoryAuditReport

    report = MemoryAuditReport()

    assert report.memory_entries_count == 0
    assert report.raw_count == 0
    assert report.card_count == 0
    assert report.missing_raw_for_entries == 0
    assert report.missing_card_for_entries == 0


def test_memory_provider_reads_settings_through_config_service(monkeypatch):
    from agentmind.memory import provider

    class FakeConfigService:
        def read_settings(self):
            return {"memory": {"max_entries": 123}}

    monkeypatch.setattr(provider, "ConfigService", FakeConfigService)

    assert provider.read_memory_settings() == {"memory": {"max_entries": 123}}


def test_memory_modules_do_not_import_storage_memory_helpers():
    src_root = Path(__file__).resolve().parents[1] / "src" / "agentmind" / "memory"
    forbidden = (
        "from agentmind.storage.memory import _load_settings",
        "from agentmind.storage.memory import _generate_embedding",
        "from agentmind.storage.memory import _embedding_to_blob",
        "from agentmind.storage.memory import await_or_sync_embedding",
        "from agentmind.storage.memory import _get_agent_credibility",
    )
    offenders = []

    for path in sorted(src_root.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        if any(pattern in text for pattern in forbidden):
            offenders.append(path.relative_to(src_root).as_posix())

    assert offenders == []
