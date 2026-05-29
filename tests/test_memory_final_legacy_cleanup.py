from pathlib import Path


SRC_ROOT = Path(__file__).resolve().parents[1] / "src" / "agentmind"

LEGACY_PATTERNS = (
    "agentmind.storage.memory",
    "memory_entries",
    "memory_fts",
    "vec_memory",
    "v4_write_enabled",
    "v4_retrieval_enabled",
    "_v4_assembled",
)

# Phase 0 freezes the current legacy surface. Later phases must shrink this
# allowlist until Phase 9 leaves only migration/cleanup tests.
TRANSITIONAL_LEGACY_FILES = {
    "config/defaults.py",
    "memory/components/importance_scorer.py",
    "memory/conflict_detector.py",
    "memory/pipeline/write_pipeline.py",
    "memory/service.py",
    "memory/sqlite_store.py",
    "memory/tokenizer/jieba_fts.py",
    "routing/envelope.py",
    "routing/executors/self_reply.py",
    "routing/middleware/memory_retriever.py",
    "routing/strategies/llm_routing.py",
    "services/trace_service.py",
    "storage/db.py",
    "storage/memory.py",
}

TRANSITIONAL_LEGACY_DIRS = {
    "memory/migrations",
    "memory/workers",
}


def _source_files() -> list[Path]:
    suffixes = {".py", ".sql"}
    return sorted(
        path
        for path in SRC_ROOT.rglob("*")
        if path.is_file() and path.suffix in suffixes
    )


def _rel(path: Path) -> str:
    return path.relative_to(SRC_ROOT).as_posix()


def _is_transitional_legacy_zone(path: Path) -> bool:
    rel = _rel(path)
    return rel in TRANSITIONAL_LEGACY_FILES or any(
        rel.startswith(f"{prefix}/") for prefix in TRANSITIONAL_LEGACY_DIRS
    )


def test_no_new_legacy_memory_or_retrieval_paths_outside_phase0_allowlist():
    offenders: dict[str, list[str]] = {}

    for path in _source_files():
        text = path.read_text(encoding="utf-8")
        matched_patterns = [pattern for pattern in LEGACY_PATTERNS if pattern in text]
        if matched_patterns and not _is_transitional_legacy_zone(path):
            offenders[_rel(path)] = matched_patterns

    assert offenders == {}


def test_phase0_transitional_allowlist_only_references_existing_files_or_dirs():
    missing_files = sorted(
        rel for rel in TRANSITIONAL_LEGACY_FILES if not (SRC_ROOT / rel).is_file()
    )
    missing_dirs = sorted(
        rel for rel in TRANSITIONAL_LEGACY_DIRS if not (SRC_ROOT / rel).is_dir()
    )

    assert missing_files == []
    assert missing_dirs == []
