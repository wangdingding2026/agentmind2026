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

FINAL_ALLOWED_LEGACY_FILES = set()
FINAL_ALLOWED_LEGACY_DIRS = set()


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
    return rel in FINAL_ALLOWED_LEGACY_FILES or any(
        rel.startswith(f"{prefix}/") for prefix in FINAL_ALLOWED_LEGACY_DIRS
    )


def test_no_new_legacy_memory_or_retrieval_paths_outside_phase0_allowlist():
    offenders: dict[str, list[str]] = {}

    for path in _source_files():
        text = path.read_text(encoding="utf-8")
        matched_patterns = [pattern for pattern in LEGACY_PATTERNS if pattern in text]
        if matched_patterns and not _is_transitional_legacy_zone(path):
            offenders[_rel(path)] = matched_patterns

    assert offenders == {}


def test_final_legacy_allowlist_only_references_existing_files_or_dirs():
    missing_files = sorted(
        rel for rel in FINAL_ALLOWED_LEGACY_FILES if not (SRC_ROOT / rel).is_file()
    )
    missing_dirs = sorted(
        rel for rel in FINAL_ALLOWED_LEGACY_DIRS if not (SRC_ROOT / rel).is_dir()
    )

    assert missing_files == []
    assert missing_dirs == []
