# Phase 5 Readiness

## Readiness Decision

Phase 5 readiness is the security governance readiness gate after Phase 4 closure.

Phase 4 is closed. The required entry source for this gate is `docs/phase4/phase-4-closure-status.md`.

This package prepares AgentMind for security governance readiness only. It does not start CPE or AgentShield runtime implementation.

## Boundary Baseline

Phase 5 starts from these service/rule/channel boundaries:

- panel/API/channel remain adapters;
- services do the work;
- rule/core layers own rules and decisions;
- infrastructure modules own storage, protocols, runtimes, and external tool details;
- channel adapters normalize inbound/outbound protocol details and do not own business rules;
- runtime primitives remain below services and do not leak back into panel handlers.

Before any security-governance implementation begins, these service/rule/channel boundaries must be confirmed against the current code and tests.

## Security Governance Scope

Phase 5 is about preparing and then implementing security governance in small packages:

- CPE controls information flow: context, memory, sensitive content, and remote-agent exposure.
- AgentShield controls behavior permissions: dangerous commands, external API usage, tool access, loops, and approval triggers.
- AuditService records governance decisions and security-relevant actions.
- Memory private/public access rules stay behind service and governance boundaries.

Phase 5 readiness only defines entry conditions. It does not add runtime policy behavior.

## CPE Start Criteria

CPE start criteria must be satisfied before planning the first CPE package:

- the entry service that calls CPE is identified;
- the rule/core boundary that owns CPE decisions is identified;
- the channel boundary remains below services and does not own CPE rules;
- sensitive context flow into local, cloud, and third-party agents has an explicit decision point;
- private memory access has an explicit decision point before retrieval results are exposed;
- CPE decisions have an AuditService event shape;
- CPE tests cover new architecture targets, not only legacy sensitive-scanner behavior.

The first CPE package should be a readiness-to-skeleton step, not broad routing or memory rewrites.

## AgentShield Start Criteria

AgentShield start criteria must be satisfied after CPE entry criteria are clear:

- execution boundaries are identified before interception is added;
- ProtocolGateway and executor boundaries are checked for the correct interception point;
- approval boundaries are identified before high-risk actions are allowed;
- blocked and approval-required decisions have AuditService event shapes;
- panel/API/channel remain adapters and do not implement AgentShield rules;
- rollback and compatibility impact are documented for every intercepted behavior.

The first AgentShield package should define behavior-permission decisions and audit events before blocking broad classes of actions.

## Compatibility Boundaries

`feishu.route_callback` remains a bounded migration fallback.

Its delete criteria are:

- delete after Feishu inbound handling no longer needs the `route_callback` fallback;
- delete after all supported Feishu inbound paths use `ChannelMessage`.

Phase 5 must not add new architecture behavior to `feishu.route_callback`. Phase 5 readiness does not require deleting it; it requires keeping it bounded and documented.

## Deferred Work

persistent task-event replay remains deferred to a later observability/task-event package.

Do not mix persistent task-event replay into Phase 5 security governance readiness. Stream snapshot behavior remains the Phase 4 in-process backlog boundary until a separate observability/task-event package is planned.

Phase 6 readiness, EvolutionEngine, TemplateMarket, and self-evolution work remain out of scope until Phase 5 is closed.

## Explicit Non-Goals

This gate is intentionally narrow:

- do not implement CPE;
- do not implement AgentShield;
- do not implement persistent task-event replay;
- do not delete `feishu.route_callback`;
- do not change API/Webhook channel behavior;
- do not expand old fallback business logic;
- do not start EvolutionEngine or TemplateMarket;
- do not move security rules into panel/API/channel handlers.

## Verification Gate

Phase 5 readiness is guarded by architecture audit tests plus the existing Phase 3 and Phase 4 closure tests.

Required focused verification:

```bash
pytest tests/test_phase5_readiness_audit.py tests/test_phase4_closure_audit.py tests/test_phase3_closure_audit.py -q
```

Before starting any CPE or AgentShield package, also run:

```bash
pytest tests/test_panel_api.py tests/test_panel_control_plane_boundary.py tests/test_phase3_closure_audit.py tests/test_phase4_closure_audit.py tests/test_phase5_readiness_audit.py -q
pytest tests/test_startup.py tests/test_channel_hub.py tests/test_feishu_channel.py tests/test_feishu_path.py tests/test_session_runtime_service.py tests/test_stream.py -q
pytest tests/test_router.py tests/test_panel_api.py tests/test_feishu_path.py tests/test_e2e_scenarios.py tests/test_pipeline_executors.py -q
pytest -q
git diff --check
git status --short
```

## Next Direction

After Phase 5 readiness is green, plan the first security-governance skeleton package. That package should define CPE decision types and service entry points before changing routing, memory retrieval, or executor behavior.
