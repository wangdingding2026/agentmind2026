class SettingsStatusService:
    def __init__(self, config_service, local_embedding_probe=None):
        self.config_service = config_service
        self.local_embedding_probe = local_embedding_probe or self._default_local_embedding_probe

    def get_settings_view(self):
        data = self._read_settings()
        return {
            "memory": data.get("memory", {}),
            "embedding": data.get("embedding", {}),
            "semantic_router": data.get("semantic_router", {}),
            "history": data.get("history", {}),
            "meta": data.get("core_llm", {}),
        }

    def get_feishu_config_view(self):
        data = self._read_settings()
        feishu = data.get("feishu", {})
        if not isinstance(feishu, dict):
            feishu = {}
        return {
            "app_id": feishu.get("app_id", ""),
            "app_secret": feishu.get("app_secret", ""),
            "enabled": feishu.get("enabled", False),
        }

    def get_embedding_status(self):
        data = self._read_settings()
        embedding = data.get("embedding", {})
        if not isinstance(embedding, dict):
            embedding = {}

        has_external = bool(embedding.get("endpoint"))
        has_local = self._has_local_embedding()

        parts = []
        if has_external:
            parts.append("外部 API 已配置")
        if has_local:
            parts.append("本地模型已安装")
        if not parts:
            parts.append("未配置")

        return {
            "enabled": embedding.get("enabled", False),
            "has_external_api": has_external,
            "has_local_model": has_local,
            "dimension": embedding.get("dimension", 384),
            "summary": " + ".join(parts),
        }

    def _read_settings(self):
        data = self.config_service.read_settings()
        return data if isinstance(data, dict) else {}

    def _has_local_embedding(self):
        try:
            return bool(self.local_embedding_probe())
        except Exception:
            return False

    @staticmethod
    def _default_local_embedding_probe():
        from agentmind.storage.embedding import has_local_embedding

        return has_local_embedding()
