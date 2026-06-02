class ConnectorDiscoveryService:
    def __init__(self, profiles=None, config_service=None):
        self._profiles = profiles
        self._config_service = config_service

    def list_connectors(self):
        configured_tags = self._configured_tags()
        return {
            "connectors": [
                self._profile_to_connector(profile, configured_tags.get(profile.id))
                for profile in self._load_profiles()
            ]
        }

    def _load_profiles(self):
        if self._profiles is not None:
            return self._profiles

        from agentmind.agents.discovery import KNOWN_AGENTS

        return KNOWN_AGENTS

    def _configured_tags(self):
        if self._config_service is None:
            return {}
        data = self._config_service.read_agents()
        return {
            agent["id"]: agent.get("tags", [])
            for agent in data.get("agents", [])
            if isinstance(agent, dict) and agent.get("id")
        }

    @staticmethod
    def _profile_to_connector(profile, tags_override=None):
        open_way = profile.detect_commands[0].split()[0] if profile.detect_commands else profile.id
        return {
            "id": profile.id,
            "name": profile.name,
            "type": profile.type,
            "tags": tags_override if tags_override is not None else profile.tags,
            "open_way": open_way,
            "description": f"自动发现：{', '.join(profile.detect_commands)}",
            "timeout": profile.timeout,
        }
