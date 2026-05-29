"""记忆和检索模块数据类型定义"""

from dataclasses import dataclass, field
from enum import Enum

from agentmind.memory.dto import MemoryAuditReport, MemoryContext, MemoryWriteCommand


def _safe_float(v, default: float = 0.0) -> float:
    try:
        return float(v)
    except (ValueError, TypeError):
        return default


def _safe_int(v, default: int = 0) -> int:
    try:
        return int(v)
    except (ValueError, TypeError):
        return default


class MemoryType(Enum):
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    PROCEDURAL = "procedural"


@dataclass
class MemoryEntry:
    memory_id: str
    content: str
    summary: str = ""
    source_agent: str = ""
    source_task_id: str = ""
    user_id: str = ""
    memory_type: MemoryType = MemoryType.EPISODIC
    conversation_id: str = ""
    importance: float = 0.5
    content_hash: str = ""
    embedding_model: str = ""
    embedding_version: int = 1
    parent_id: str = ""
    distilled: int = 0
    expire_at: str = ""
    tags: list[str] = field(default_factory=list)
    access_level: str = "shared"
    version: int = 1
    created_at: str = ""
    last_accessed_at: str = ""

    def to_dict(self) -> dict:
        d = {
            "memory_id": self.memory_id,
            "content": self.content,
            "summary": self.summary,
            "source_agent": self.source_agent,
            "source_task_id": self.source_task_id,
            "user_id": self.user_id,
            "memory_type": self.memory_type.value,
            "conversation_id": self.conversation_id,
            "importance": self.importance,
            "content_hash": self.content_hash,
            "embedding_model": self.embedding_model,
            "embedding_version": self.embedding_version,
            "parent_id": self.parent_id,
            "distilled": self.distilled,
            "expire_at": self.expire_at,
            "tags": self.tags,
            "access_level": self.access_level,
            "version": self.version,
            "created_at": self.created_at,
            "last_accessed_at": self.last_accessed_at,
        }
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "MemoryEntry":
        memory_type = d.get("memory_type", "episodic")
        if isinstance(memory_type, str):
            try:
                memory_type = MemoryType(memory_type)
            except ValueError:
                memory_type = MemoryType.EPISODIC

        tags = d.get("tags", [])
        if isinstance(tags, str):
            import json
            try:
                tags = json.loads(tags)
            except (json.JSONDecodeError, TypeError):
                tags = []

        return cls(
            memory_id=d.get("memory_id", ""),
            content=d.get("content", ""),
            summary=d.get("summary", ""),
            source_agent=d.get("source_agent", ""),
            source_task_id=d.get("source_task_id", ""),
            user_id=d.get("user_id", ""),
            memory_type=memory_type,
            conversation_id=d.get("conversation_id", ""),
            importance=_safe_float(d.get("importance"), 0.5),
            content_hash=d.get("content_hash", ""),
            embedding_model=d.get("embedding_model", ""),
            embedding_version=_safe_int(d.get("embedding_version"), 1),
            parent_id=d.get("parent_id", ""),
            distilled=_safe_int(d.get("distilled"), 0),
            expire_at=d.get("expire_at", ""),
            tags=tags,
            access_level=d.get("access_level", "shared"),
            version=_safe_int(d.get("version"), 1),
            created_at=d.get("created_at", ""),
            last_accessed_at=d.get("last_accessed_at", ""),
        )


@dataclass
class SearchQuery:
    query_text: str = ""
    user_id: str = ""
    memory_types: list[MemoryType] = field(default_factory=list)
    access_levels: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    conversation_id: str = ""
    limit: int = 10
    offset: int = 0
    time_range_start: str = ""
    time_range_end: str = ""
    exclude_conversation_id: str = ""
    entities: list[str] = field(default_factory=list)


@dataclass
class SearchResult:
    entry: MemoryEntry
    score: float = 0.0
    route: str = ""  # fts5 / vector / graph / core / working

    def to_dict(self) -> dict:
        d = self.entry.to_dict()
        d["_score"] = self.score
        d["_route"] = self.route
        return d


@dataclass
class Conversation:
    conversation_id: str
    user_id: str = ""
    topic: str = ""
    summary: str = ""
    participant_agents: list[str] = field(default_factory=list)
    message_count: int = 0
    importance: float = 0.5
    first_message_at: str = ""
    last_message_at: str = ""
    status: str = "active"  # active / closed / distilled / archived


@dataclass
class RewrittenQuery:
    expanded_query: str = ""
    date_filter: str | None = None
    entity_filters: list[str] = field(default_factory=list)
    query_intent: str = ""  # factual / procedural / episodic
    confidence: float = 0.0
