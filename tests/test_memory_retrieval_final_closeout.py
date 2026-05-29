from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src" / "agentmind"
CLOSEOUT_DOC = (
    PROJECT_ROOT / "docs" / "architecture" / "final-memory-retrieval-closeout-status.md"
)


REQUIRED_CLOSEOUT_MARKERS = {
    "MemoryService is the only production memory entry point",
    "raw_memory is the only raw fact layer",
    "memory_cards is the only historical recall read model",
    "working_memory preserves current-session context",
    "core_memory and memory_relations are inside the unified repository boundary",
    "conversations are accessed through MemoryService or SqliteMemoryRepository",
    "archive and vector compatibility remain available through the repository",
    "result_sets supports expand_result and more_results",
    "agentmind.storage.memory is removed from production runtime",
    "memory_entries, memory_fts, and old vec_memory are not created or used at runtime",
    "v4 write and retrieval keys are removed",
    "focused memory retrieval eval passed",
    "tracked full pytest passed",
    "There is one memory and retrieval architecture",
}


def _source_files() -> list[Path]:
    return sorted(
        path
        for path in SRC_ROOT.rglob("*")
        if path.is_file() and path.suffix in {".py", ".sql"}
    )


def test_memory_retrieval_closeout_document_exists_and_names_final_state():
    assert CLOSEOUT_DOC.exists()
    text = CLOSEOUT_DOC.read_text(encoding="utf-8")
    missing = sorted(marker for marker in REQUIRED_CLOSEOUT_MARKERS if marker not in text)

    assert missing == []


def test_memory_retrieval_closeout_has_no_old_runtime_source_paths():
    forbidden = (
        "agentmind.storage.memory",
        "memory_entries",
        "memory_fts",
        "vec_memory",
        "SqliteMemoryStore",
        "v4_write_enabled",
        "v4_retrieval_enabled",
        "_v4_assembled",
    )
    offenders = {}

    for path in _source_files():
        text = path.read_text(encoding="utf-8")
        matches = [pattern for pattern in forbidden if pattern in text]
        if matches:
            offenders[path.relative_to(SRC_ROOT).as_posix()] = matches

    assert offenders == {}


def test_memory_retrieval_closeout_removed_old_runtime_files():
    removed = (
        SRC_ROOT / "storage" / "memory.py",
        SRC_ROOT / "memory" / "sqlite_store.py",
        SRC_ROOT / "memory" / "maintenance.py",
        SRC_ROOT / "memory" / "pipeline" / "recall.py",
        SRC_ROOT / "memory" / "migrations" / "runner.py",
    )

    assert [path for path in removed if path.exists()] == []
