import re
from dataclasses import dataclass


SENSITIVE_RE = re.compile(
    r'(sk-[a-zA-Z0-9]{20,}|api_key\s*=\s*[\"\'][^\"\']+|password\s*=\s*[\"\'][^\"\']+)',
    re.IGNORECASE,
)


@dataclass
class ScanResult:
    flagged: bool
    reason: str = ""


class SensitiveScanner:

    def scan(self, message: str) -> ScanResult:
        if not message:
            return ScanResult(flagged=False)
        if SENSITIVE_RE.search(message):
            return ScanResult(flagged=True, reason="敏感信息（API Key/密码）")
        return ScanResult(flagged=False)
