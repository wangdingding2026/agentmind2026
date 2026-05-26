import asyncio
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

logger = logging.getLogger("agentmind")


@dataclass
class RouteRule:
    name: str
    type: str  # "keyword", "regex"
    target_agent: str = ""
    priority: int = 0
    patterns: list = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    target_tags: list[str] = field(default_factory=list)
    _compiled_patterns: list = field(default_factory=list, repr=False)


@dataclass
class RouteResult:
    agent_id: str
    matched_rule: str
    confidence: float
    tags: list[str] = field(default_factory=list)


class RuleEngine:
    def __init__(self, config_path: Path, agent_registry=None):
        self.rules: list[RouteRule] = []
        self._agent_registry = agent_registry
        self._config_path = config_path
        self._lock = asyncio.Lock()
        self.load_rules(config_path)
        self._resolve_target_agents()
        self.rules.sort(key=lambda r: r.priority, reverse=True)

    def load_rules(self, config_path: Path):
        if not config_path.exists():
            return
        try:
            with open(config_path) as f:
                data = yaml.safe_load(f) or {}
        except yaml.YAMLError as e:
            logger.warning("routes.yaml 解析失败: %s，将使用空规则", e)
            return
        if not isinstance(data, dict):
            logger.warning("routes.yaml 顶层结构异常（非 dict），将使用空规则")
            return
        rules_list = data.get("rules", [])
        if not isinstance(rules_list, list):
            logger.warning("routes.yaml 的 rules 字段不是列表，跳过加载")
            return
        for rule_data in rules_list:
            if not isinstance(rule_data, dict):
                logger.warning("跳过无效规则条目: %s", rule_data)
                continue
            # 跳过 prefix/fallback 类型（已被新管道策略替代）
            if rule_data.get("type") in ("prefix", "fallback"):
                continue
            try:
                normalized = {"target_agent": "__dynamic_fallback__", **rule_data}
                # 规范化 patterns：只保留字符串，过滤数字/None 等
                if "patterns" in normalized:
                    raw = normalized["patterns"]
                    if isinstance(raw, list):
                        normalized["patterns"] = [p for p in raw if isinstance(p, str)]
                        bad = [p for p in raw if not isinstance(p, str)]
                        if bad:
                            logger.warning("路由规则 '%s' 的非字符串 patterns 已忽略: %s",
                                         rule_data.get("name", "?"), bad)
                # 过滤不存在的字段
                allowed = {f.name for f in dataclasses_fields(RouteRule)}
                rule = RouteRule(**{k: v for k, v in normalized.items() if k in allowed})
                if rule.type == "regex":
                    for p in rule.patterns:
                        try:
                            rule._compiled_patterns.append(re.compile(p, re.IGNORECASE))
                        except re.error as e:
                            logger.warning("路由规则 '%s' 的正则 '%s' 非法，已跳过: %s", rule.name, p, e)
                self.rules.append(rule)
            except Exception as e:
                logger.warning("跳过无效路由规则: %s，错误: %s", rule_data.get("name", "?"), e)

    def _resolve_target_agents(self):
        """根据 target_tags 动态解析 target_agent"""
        if not self._agent_registry:
            return

        agent_tags = {
            aid: set(ex.capability.tags)
            for aid, ex in self._agent_registry.executors.items()
        }

        for rule in self.rules:
            if rule.target_agent and rule.target_agent != "__dynamic_fallback__":
                if rule.target_agent == "agentmind" or self._agent_registry.get_executor(rule.target_agent):
                    continue

            if rule.target_tags:
                tag_set = set(rule.target_tags)
                matched = None
                for aid, ex in self._agent_registry.executors.items():
                    if tag_set & agent_tags.get(aid, set()):
                        if matched is None or "general" in agent_tags.get(aid, set()):
                            matched = aid
                            if "general" in agent_tags[aid]:
                                break
                rule.target_agent = matched or "__dynamic_fallback__"
            else:
                rule.target_agent = "__dynamic_fallback__"

    async def reload(self, config_path: Path = None):
        """重新加载路由规则并重新解析 target_agent"""
        async with self._lock:
            self.rules.clear()
            self.load_rules(config_path or self._config_path)
            self._resolve_target_agents()
            self.rules.sort(key=lambda r: r.priority, reverse=True)

    async def match(self, user_message: str) -> RouteResult:
        async with self._lock:
            return self._match_impl(user_message)

    def _match_impl(self, user_message: str) -> RouteResult:
        if not user_message or not user_message.strip():
            return None

        for rule in self.rules:
            if rule.type == "keyword":
                if any(p.lower() in user_message.lower() for p in rule.patterns):
                    return RouteResult(
                        agent_id=rule.target_agent,
                        matched_rule=rule.name,
                        confidence=0.9,
                        tags=rule.tags,
                    )
            elif rule.type == "regex":
                for compiled in rule._compiled_patterns:
                    try:
                        if compiled.search(user_message):
                            return RouteResult(
                                agent_id=rule.target_agent,
                                matched_rule=rule.name,
                                confidence=0.85,
                                tags=rule.tags,
                            )
                    except re.error:
                        continue

        return None


def dataclasses_fields(cls):
    """兼容 Python 3.12 的 dataclass fields 获取"""
    from dataclasses import fields
    return fields(cls)
