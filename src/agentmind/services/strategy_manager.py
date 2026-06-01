from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from agentmind.routing.strategies.base import RoutingStrategy


@dataclass
class StrategyRegistration:
    name: str
    priority: int
    kind: str
    factory: Callable[[dict], RoutingStrategy]
    enabled: bool = True
    required: bool = False

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "priority": self.priority,
            "kind": self.kind,
            "enabled": self.enabled,
            "required": self.required,
        }


class StrategyManager:
    """Runtime registry for routing strategies.

    The four core strategies stay protected. Auxiliary strategies can be
    inserted between them without changing RoutingPipeline or router.py.
    """

    def __init__(self, agent_registry, rule_engine):
        self._agent_registry = agent_registry
        self._rule_engine = rule_engine
        self._registrations: dict[str, StrategyRegistration] = {}
        self._order: list[str] = []
        self._register_defaults()

    def list_strategies(self, kind: str | None = None) -> list[dict]:
        registrations = self._ordered_registrations()
        if kind is not None:
            registrations = [item for item in registrations if item.kind == kind]
        return [item.as_dict() for item in registrations]

    def set_enabled(self, name: str, enabled: bool) -> dict:
        registration = self._get(name)
        if registration.required and not enabled:
            raise ValueError(f"strategy {name} is required and cannot be disabled")
        registration.enabled = bool(enabled)
        return registration.as_dict()

    def set_order(self, names: list[str]) -> list[dict]:
        unknown = [name for name in names if name not in self._registrations]
        if unknown:
            raise ValueError(f"unknown strategies: {', '.join(unknown)}")
        remaining = [name for name in self._order if name not in names]
        self._order = [*names, *remaining]
        return self.list_strategies()

    def get_enabled_strategies(self, settings: dict | None = None) -> list[RoutingStrategy]:
        settings = settings or {}
        strategies = []
        for registration in self._ordered_registrations():
            if registration.enabled:
                strategies.append(registration.factory(settings))
        return strategies

    def _register_defaults(self) -> None:
        from agentmind.routing.strategies.explicit_directive import ExplicitDirective
        from agentmind.routing.strategies.semantic_intent import SemanticIntentStrategy
        from agentmind.routing.strategies.signal_scoring import SignalScoringStrategy

        self._register(
            "explicit",
            priority=0,
            kind="core",
            required=True,
            factory=lambda settings: ExplicitDirective(self._agent_registry),
        )
        self._register(
            "semantic_intent",
            priority=20,
            kind="core",
            required=False,
            factory=lambda settings: SemanticIntentStrategy(self._agent_registry, settings),
        )
        self._register(
            "signal_scoring",
            priority=100,
            kind="core",
            required=True,
            factory=lambda settings: SignalScoringStrategy(self._agent_registry),
        )

    def _register(
        self,
        name: str,
        *,
        priority: int,
        kind: str,
        required: bool,
        factory: Callable[[dict], RoutingStrategy],
    ) -> None:
        self._registrations[name] = StrategyRegistration(
            name=name,
            priority=priority,
            kind=kind,
            required=required,
            factory=factory,
        )
        self._order.append(name)

    def _ordered_registrations(self) -> list[StrategyRegistration]:
        registrations = [self._registrations[name] for name in self._order]
        return sorted(registrations, key=lambda item: item.priority)

    def _get(self, name: str) -> StrategyRegistration:
        try:
            return self._registrations[name]
        except KeyError as exc:
            raise ValueError(f"unknown strategy: {name}") from exc
