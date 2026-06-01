from agentmind.storage.db import CONFIG_DIR

ROUTES_YAML_TEMPLATE = """\
# AgentMind 路由规则
# 路由策略已统一为：@agent 显式指定 → 语义意图 → 信号评分。
# 如需启用关键词规则，在策略管理器中注册 rule_engine 策略即可。
rules: []
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
