-- AgentMind 记忆引擎 v1 → v2 Schema 迁移
-- 幂等设计：每条语句由 runner.py 检查条件后执行

-- 1. memory_entries 新增列（9 列，runner 逐条 try/except）
ALTER TABLE memory_entries ADD COLUMN memory_type TEXT DEFAULT 'episodic';
ALTER TABLE memory_entries ADD COLUMN conversation_id TEXT DEFAULT '';
ALTER TABLE memory_entries ADD COLUMN importance REAL DEFAULT 0.5;
ALTER TABLE memory_entries ADD COLUMN content_hash TEXT DEFAULT '';
ALTER TABLE memory_entries ADD COLUMN embedding_model TEXT DEFAULT 'all-MiniLM-L6-v2';
ALTER TABLE memory_entries ADD COLUMN embedding_version INTEGER DEFAULT 1;
ALTER TABLE memory_entries ADD COLUMN parent_id TEXT DEFAULT '';
ALTER TABLE memory_entries ADD COLUMN distilled INTEGER DEFAULT 0;
ALTER TABLE memory_entries ADD COLUMN expire_at TEXT DEFAULT '';

-- 2. 新表
CREATE TABLE IF NOT EXISTS conversations (
    conversation_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    topic TEXT DEFAULT '',
    summary TEXT DEFAULT '',
    participant_agents TEXT DEFAULT '[]',
    message_count INTEGER DEFAULT 0,
    importance REAL DEFAULT 0.5,
    first_message_at TEXT NOT NULL,
    last_message_at TEXT NOT NULL,
    status TEXT DEFAULT 'active'
);

CREATE TABLE IF NOT EXISTS core_memory (
    user_id TEXT NOT NULL,
    slot_key TEXT NOT NULL,
    slot_value TEXT NOT NULL,
    byte_size INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    updated_by TEXT DEFAULT '',
    PRIMARY KEY (user_id, slot_key)
);

CREATE TABLE IF NOT EXISTS memory_relations (
    relation_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL DEFAULT '',
    head_entity TEXT NOT NULL,
    relation TEXT NOT NULL,
    tail_entity TEXT NOT NULL,
    head_memory_id TEXT DEFAULT '',
    tail_memory_id TEXT DEFAULT '',
    confidence REAL DEFAULT 0.8,
    ts TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS procedural_signals (
    user_id TEXT NOT NULL,
    signal_key TEXT NOT NULL,
    signal_value TEXT NOT NULL DEFAULT '',
    weight REAL DEFAULT 1.0,
    hits INTEGER DEFAULT 0,
    updated_at TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (user_id, signal_key)
);

-- 3. FTS5 迁移到 jieba 分词器（runner 负责检查重建）
-- 删除旧 memory_fts，新建带 jieba tokenizer 的

-- 4. vec_memory 重命名为 vec_memory_v1（runner 负责条件检查）

-- 5. 新增索引
CREATE INDEX IF NOT EXISTS idx_memory_type ON memory_entries(memory_type, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_memory_conversation ON memory_entries(conversation_id);
CREATE INDEX IF NOT EXISTS idx_memory_importance ON memory_entries(importance DESC, last_accessed_at DESC);
CREATE INDEX IF NOT EXISTS idx_memory_expire ON memory_entries(expire_at) WHERE expire_at IS NOT NULL AND expire_at != '';
CREATE INDEX IF NOT EXISTS idx_memory_hash ON memory_entries(content_hash);

CREATE INDEX IF NOT EXISTS idx_conv_user_last ON conversations(user_id, last_message_at DESC);
CREATE INDEX IF NOT EXISTS idx_conv_status ON conversations(status, last_message_at DESC);

CREATE INDEX IF NOT EXISTS idx_rel_head ON memory_relations(user_id, head_entity);
CREATE INDEX IF NOT EXISTS idx_rel_tail ON memory_relations(user_id, tail_entity);
CREATE INDEX IF NOT EXISTS idx_rel_relation ON memory_relations(relation);

-- 6. schema 版本追踪
CREATE TABLE IF NOT EXISTS _schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);
