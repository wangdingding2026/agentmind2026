import pytest
import yaml
from pathlib import Path

from agentmind.core.rule_engine import RuleEngine, RouteRule


class TestRuleEngineMatch:
    @pytest.mark.asyncio
    async def test_keyword_match(self, rule_engine):
        result = await rule_engine.match("写一个函数")
        assert result.matched_rule == "code_kw"
        assert result.confidence == 0.9

    @pytest.mark.asyncio
    async def test_keyword_no_match(self, rule_engine):
        result = await rule_engine.match("今天天气不错")
        assert result is None

    @pytest.mark.asyncio
    async def test_empty_message_returns_none(self, rule_engine):
        result = await rule_engine.match("")
        assert result is None

    @pytest.mark.asyncio
    async def test_whitespace_message_returns_none(self, rule_engine):
        result = await rule_engine.match("   ")
        assert result is None


class TestRuleEngineBadRegex:
    @pytest.mark.asyncio
    async def test_invalid_regex_skipped(self, rule_engine):
        result = await rule_engine.match("anything")
        assert result is None


class TestRuleEngineNoMutation:
    def test_load_does_not_mutate_original_dict(self, tmp_dir):
        raw = {"rules": [{"name": "test", "type": "keyword", "patterns": ["hello"], "priority": 1, "tags": []}]}
        path = tmp_dir / "routes.yaml"
        path.write_text(yaml.dump(raw, allow_unicode=True), encoding="utf-8")

        engine = RuleEngine(path, agent_registry=None)
        with open(path) as f:
            data = yaml.safe_load(f)
        assert "target_agent" not in data["rules"][0]


class TestRuleEngineReload:
    @pytest.mark.asyncio
    async def test_reload_refreshes_rules(self, tmp_dir):
        path = tmp_dir / "routes.yaml"
        path.write_text(yaml.dump({"rules": [
            {"name": "old", "type": "keyword", "patterns": ["hello"], "priority": 1, "tags": []}
        ]}, allow_unicode=True), encoding="utf-8")

        engine = RuleEngine(path, agent_registry=None)
        assert len(engine.rules) == 1

        path.write_text(yaml.dump({"rules": [
            {"name": "new1", "type": "keyword", "patterns": ["a"], "priority": 1, "tags": []},
            {"name": "new2", "type": "keyword", "patterns": ["b"], "priority": 2, "tags": []},
        ]}, allow_unicode=True), encoding="utf-8")

        await engine.reload()
        assert len(engine.rules) == 2
        assert engine.rules[0].name == "new2"


class TestRuleEngineBadConfig:
    def test_yaml_syntax_error_does_not_crash(self, tmp_dir):
        path = tmp_dir / "bad.yaml"
        path.write_text("rules: [{{{ bad yaml", encoding="utf-8")
        engine = RuleEngine(path, agent_registry=None)
        assert engine.rules == []

    def test_top_level_not_dict_does_not_crash(self, tmp_dir):
        path = tmp_dir / "bad.yaml"
        path.write_text("- just a list\n- of items", encoding="utf-8")
        engine = RuleEngine(path, agent_registry=None)
        assert engine.rules == []

    def test_non_string_patterns_filtered(self, tmp_dir):
        config = {
            "rules": [{
                "name": "mixed", "type": "keyword",
                "patterns": [123, "ok", None, "also_ok"],
                "priority": 1, "tags": [],
            }]
        }
        path = tmp_dir / "routes.yaml"
        path.write_text(yaml.dump(config, allow_unicode=True), encoding="utf-8")
        engine = RuleEngine(path, agent_registry=None)
        assert len(engine.rules) == 1
        assert engine.rules[0].patterns == ["ok", "also_ok"]

    def test_prefix_fallback_types_skipped(self, tmp_dir):
        """prefix/fallback 类型规则在加载时被跳过"""
        config = {
            "rules": [
                {"name": "pfx", "type": "prefix", "patterns": ["/code"], "priority": 20, "tags": []},
                {"name": "kw", "type": "keyword", "patterns": ["hello"], "priority": 10, "tags": []},
                {"name": "fb", "type": "fallback", "patterns": [], "priority": 0, "tags": []},
            ]
        }
        path = tmp_dir / "routes.yaml"
        path.write_text(yaml.dump(config, allow_unicode=True), encoding="utf-8")
        engine = RuleEngine(path, agent_registry=None)
        assert len(engine.rules) == 1
        assert engine.rules[0].name == "kw"
