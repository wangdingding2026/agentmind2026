from agentmind.storage.db import CONFIG_DIR

ROUTES_YAML_TEMPLATE = """\
rules:
  - name: code
    type: keyword
    patterns: ["写", "代码", "函数", "修复", "重构", "接口", "bug", "class", "def", "补全", "生成"]
    target_tags: ["code"]
    priority: 10
  - name: search
    type: keyword
    patterns: ["搜索", "查", "什么是", "怎么", "推荐", "最新", "新闻"]
    target_tags: ["search"]
    priority: 10
  - name: analysis
    type: keyword
    patterns: ["分析", "审查", "检查", "review", "解释", "为什么"]
    target_tags: ["code"]
    priority: 10
  - name: writing
    type: keyword
    patterns: ["写文章", "文档", "翻译", "总结", "报告", "文案"]
    target_tags: ["general"]
    priority: 10
  - name: memory
    type: keyword
    patterns: ["还记得", "回忆一下", "历史记录", "展开第", "详细说说"]
    target_agent: "agentmind"
    priority: 10
"""


SETTINGS_YAML_TEMPLATE = """\
heartbeat_timeout_seconds: 300
embedding_dim: 384
sensitive_routing_whitelist: []

embedding:
  enabled: false
  endpoint: ""
  api_key: ""
  model: "text-embedding-3-small"
  dimension: 384
  timeout_seconds: 10
  local_fallback: true

memory:
  max_entries: 10000
  atomic_facts: true
  conflict_check_enabled: true
  conflict_similarity_threshold: 0.85
  v4_write_enabled: false
  v4_retrieval_enabled: false

routing:
  use_new_pipeline: true

history:
  max_entries: 10000
  retention_days: 30

core_llm:
  enabled: false
  endpoint: ""
  api_key: ""
  model: ""
  timeout_seconds: 10

feishu:
  enabled: false
  app_id: ""
  app_secret: ""
"""


def generate_default_configs():
    """生成默认配置模板，仅在首次创建，后续不覆盖用户修改。agents.yaml 由自动发现机制生成。"""
    routes_path = CONFIG_DIR / "routes.yaml"
    if not routes_path.exists():
        routes_path.write_text(ROUTES_YAML_TEMPLATE, encoding="utf-8")

    settings_path = CONFIG_DIR / "settings.yaml"
    if not settings_path.exists():
        settings_path.write_text(SETTINGS_YAML_TEMPLATE, encoding="utf-8")
