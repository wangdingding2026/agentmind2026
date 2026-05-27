class ConnectorDiscoveryService:
    def __init__(self, profiles=None):
        self._profiles = profiles

    def list_connectors(self):
        return {
            "connectors": [
                self._profile_to_connector(profile)
                for profile in self._load_profiles()
            ]
        }

    def _load_profiles(self):
        if self._profiles is not None:
            return self._profiles

        from agentmind.agents.discovery import KNOWN_AGENTS

        return KNOWN_AGENTS

    @staticmethod
    def _profile_to_connector(profile):
        return {
            "id": profile.id,
            "name": profile.name,
            "type": profile.type,
            "tags": profile.tags,
            "description": f"自动发现：{', '.join(profile.detect_commands)}",
            "timeout": profile.timeout,
        }
