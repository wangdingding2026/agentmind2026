from pathlib import Path


SRC_ROOT = Path(__file__).resolve().parents[1] / "src" / "agentmind"

ALLOWED_LEGACY_MEMORY_FILES = {
    "storage/memory.py",
    "storage/db.py",
    "memory/sqlite_store.py",
    "memory/pipeline/write_pipeline.py",
    "memory/components/importance_scorer.py",
    "services/trace_service.py",
}

ALLOWED_LEGACY_MEMORY_DIRS = {
    "memory/migrations",
    "memory/workers",
}


def _source_files() -> list[Path]:
    return sorted(SRC_ROOT.rglob("*.py"))


def _rel(path: Path) -> str:
    return path.relative_to(SRC_ROOT).as_posix()


def _is_allowed_legacy_zone(path: Path) -> bool:
    rel = _rel(path)
    return rel in ALLOWED_LEGACY_MEMORY_FILES or any(
        rel.startswith(f"{prefix}/") for prefix in ALLOWED_LEGACY_MEMORY_DIRS
    )


def test_business_modules_do_not_import_legacy_storage_memory():
    offenders = []
    forbidden = (
        "from agentmind.storage.memory import",
        "import agentmind.storage.memory",
        "__import__(\"agentmind.storage.memory\"",
        "__import__('agentmind.storage.memory'",
    )

    for path in _source_files():
        if _is_allowed_legacy_zone(path):
            continue
        text = path.read_text(encoding="utf-8")
        if any(pattern in text for pattern in forbidden):
            offenders.append(_rel(path))

    assert offenders == []


def test_business_modules_do_not_touch_memory_entries_directly():
    offenders = []
    forbidden = (
        "_get_memory_conn",
        "FROM memory_entries",
        "DELETE FROM memory_entries",
        "UPDATE memory_entries",
        "INSERT INTO memory_entries",
        "JOIN memory_entries",
    )

    for path in _source_files():
        if _is_allowed_legacy_zone(path):
            continue
        text = path.read_text(encoding="utf-8")
        if any(pattern in text for pattern in forbidden):
            offenders.append(_rel(path))

    assert offenders == []
