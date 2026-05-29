from pathlib import Path
import ast


SRC_ROOT = Path(__file__).resolve().parents[1] / "src" / "agentmind"


def _read(rel_path: str) -> str:
    return (SRC_ROOT / rel_path).read_text(encoding="utf-8")


def test_memory_service_production_path_does_not_call_legacy_store_runtime_methods():
    text = _read("memory/service.py")

    forbidden = (
        "self._store.search_memory_cards",
        "self._store.search(",
        "self._store.insert(",
        "self._store._get_conn(",
        "self._store._get_memory_card_sync",
        "self._store._get_raw_memory_sync",
        "self._store.get_stats(",
        "self._store.cleanup_memory(",
        "self._store.delete(",
        "SessionService(self._store)",
    )

    offenders = [pattern for pattern in forbidden if pattern in text]

    assert offenders == []


def test_retrieve_context_uses_formal_strategy_not_empty_result_fallback():
    text = _read("memory/service.py")
    tree = ast.parse(text)
    retrieve_context = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "retrieve_context"
    )
    retrieve_context_text = ast.get_source_segment(text, retrieve_context)

    forbidden = (
        "fallback to memory_entries",
        "self._store.search(",
        "if not rows:\n            rows =",
        "if not keyword_rows:\n            recent_rows =",
    )

    offenders = [pattern for pattern in forbidden if pattern in retrieve_context_text]

    assert offenders == []


def test_write_pipeline_storage_actions_go_through_repository_boundary():
    text = _read("memory/pipeline/write_pipeline.py")

    forbidden = (
        "self._store._get_conn(",
        "INSERT OR REPLACE INTO vec_memory",
        "INSERT OR IGNORE INTO memory_relations",
        "CoreMemoryManager.upsert(self._store",
        "ConversationMerger().find_or_create",
        "merger.find_or_create(",
    )

    offenders = [pattern for pattern in forbidden if pattern in text]

    assert offenders == []


def test_conflict_detector_storage_actions_go_through_repository_boundary():
    text = _read("memory/conflict_detector.py")

    forbidden = (
        "self._store._get_memory_card_sync",
        "self._store._get_conn(",
        "self._store._row_to_memory_card",
    )

    offenders = [pattern for pattern in forbidden if pattern in text]

    assert offenders == []


def test_legacy_recall_pipeline_has_no_store_runtime_fallback():
    text = _read("memory/pipeline/recall.py")

    forbidden = (
        "return await self._store.search(",
        "self._store._get_conn(",
    )

    offenders = [pattern for pattern in forbidden if pattern in text]

    assert offenders == []


def test_memory_retriever_has_no_v4_sentinel_or_switch_path():
    text = _read("routing/middleware/memory_retriever.py")

    forbidden = (
        "_v4_assembled",
        "_assembled_context",
        "_use_v4_retrieval",
        "v4_retrieval_enabled",
    )

    offenders = [pattern for pattern in forbidden if pattern in text]

    assert offenders == []
