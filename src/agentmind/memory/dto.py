"""Final memory/retrieval boundary DTOs."""

from dataclasses import dataclass, field


@dataclass
class MemoryWriteCommand:
    content: str
    memory_id: str = ""
    summary: str = ""
    user_id: str = ""
    source_agent: str = ""
    source_task_id: str = ""
    session_id: str = ""
    conversation_id: str = ""
    tags: list[str] = field(default_factory=list)
    memory_type: str = "episodic"
    importance: float = 0.5
    access_level: str = "shared"
    content_hash: str = ""
    parent_id: str = ""
    embedding_model: str = ""
    embedding_version: int = 1
    source_kind: str = "task"
    created_at: str = ""


@dataclass
class MemoryContext:
    assembled_context: str
    working_memory: list[dict] = field(default_factory=list)
    recall_items: list[dict] = field(default_factory=list)
    result_set_id: str = ""
    steps: list[str] = field(default_factory=list)
    truncated: bool = False


@dataclass
class MemoryAuditReport:
    source_entry_count: int = 0
    raw_count: int = 0
    card_count: int = 0
    missing_raw_for_entries: int = 0
    missing_card_for_entries: int = 0
    orphan_raw: int = 0
    orphan_card: int = 0
    index_gaps: int = 0
