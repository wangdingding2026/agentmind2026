from agentmind.routing.middleware.sensitive_scanner import ScanResult


class CandidatePool:

    def __init__(self, agent_registry):
        self._registry = agent_registry

    def filter(self, scan_result: ScanResult) -> list[str]:
        candidates = []
        for aid, ex in self._registry.executors.items():
            if not ex.is_healthy:
                continue
            if scan_result.flagged and ex.capability.security_level != "local":
                continue
            candidates.append(aid)
        return candidates
