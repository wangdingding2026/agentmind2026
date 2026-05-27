# Phase 1-4 Retrospective Continuation

## Purpose

This document is the handoff bridge for the Phase 1-4 retrospective. Its job is to make sure the team can finish the retrospective and then continue architecture refactor and optimization without reopening closed phases, widening old compatibility paths, or mixing Phase 5 and Phase 6 work into the retrospective itself.

The retrospective source of truth starts from:

- `AGENTMIND_OPTIMIZATION_PLAN.md`
- `AGENTMIND_IMPLEMENTATION_PLAN.md`
- `docs/phase3/phase-3-closure-status.md`
- `docs/phase3/panel-control-plane-boundary.md`
- `docs/phase4/phase-4-closure-status.md`

The Phase 4 closure entry point is `docs/phase4/phase-4-closure-status.md`.

## Current Closed Baseline

Phase 1 through Phase 4 should be treated as closed unless the retrospective finds a concrete boundary defect that blocks Phase 5 readiness.

The current baseline is:

- Phase 1 closed the first service-layer foundation.
- Phase 2 closed memory service convergence, retrieval, trace separation, and session/history boundaries.
- Phase 3 closed platform-core and control-plane service boundaries.
- Phase 4 closed control-panel runtime and channel boundary work.

The retrospective may identify follow-up work, but it should classify each item instead of turning the review into broad refactoring:

- must fix before Phase 5 readiness;
- can be carried into Phase 5 readiness as a documented constraint;
- belongs to a later observability/task-event package;
- belongs to compatibility-layer deletion after migration criteria are met;
- out of scope for the current architecture track.

## Architecture Rules To Preserve

The retrospective and follow-up work must keep these service/rule/channel boundaries intact:

- panel/API/channel remain adapters;
- services do the work;
- rule/core layers own rules and decisions;
- infrastructure modules own storage, protocol, runtime primitives, and external tool details;
- service layers may compose rule/core and infrastructure boundaries;
- panel, API, startup, and channel handlers must not regain direct ownership of business rules, persistence decisions, routing strategy construction, or runtime internals.

For Phase 5, this means CPE and AgentShield must be designed as governance/rule boundaries that are called by services. They should not be implemented inside panel handlers, channel adapters, or old fallback paths.

For Phase 6, this means EvolutionEngine and TemplateMarket must propose, approve, apply, and roll back changes through services. They must not directly edit YAML, memory tables, routes, prompts, or orchestration definitions from UI adapters.

## Compatibility Layers

Compatibility layer boundaries are acceptable only when they support migration and final deletion.

The most important current compatibility layer is `feishu.route_callback`.

It remains bounded by these delete criteria:

- delete after Feishu inbound handling no longer needs the `route_callback` fallback;
- delete after all supported Feishu inbound paths use `ChannelMessage`;
- do not add new architecture behavior to `feishu.route_callback`;
- do not make Phase 5 or Phase 6 depend on this fallback.

Other compatibility layers should be judged by the same standard: they need a migration purpose, explicit delete criteria, and tests that protect the new service boundary rather than only preserving old behavior.

## Retrospective Checklist

Use this checklist during the Phase 1-4 retrospective.

1. Confirm panel/API/channel adapters are thin.
2. Confirm service ownership is real for config, tasks, memory, routing, orchestration, audit, panel control, channel lifecycle, and session runtime.
3. Confirm rule/core layers own rules and decisions instead of letting services or adapters hard-code long-term policy.
4. Confirm old storage or runtime paths are only compatibility layers with delete criteria.
5. Confirm tests protect new architecture boundaries, not just legacy response shapes.
6. Confirm runtime recovery boundaries are explicit.
7. Confirm volatile runtime state is documented and not falsely advertised as durable.
8. Confirm persistent task-event replay remains deferred to an observability/task-event package.
9. Confirm no Phase 5 security governance work was accidentally started during Phase 4 closeout.
10. Confirm no Phase 6 self-evolution or marketplace work is coupled to unresolved Phase 1-4 gaps.

## Retrospective Output Format

At the end of the retrospective, create or update a concise closure artifact with these sections:

- reviewed scope;
- confirmed boundaries;
- findings that block Phase 5 readiness;
- non-blocking follow-ups;
- compatibility layers and delete criteria;
- deferred observability/task-event work;
- verification commands and results;
- next implementation package.

The retrospective output should not implement fixes by itself. If a blocking defect is found, create a small TDD package for that defect and close it before starting Phase 5 readiness.

## Resume Route After Retrospective

After the retrospective is complete, resume in this order:

1. Resolve any retrospective finding classified as "must fix before Phase 5 readiness".
2. Start Phase 5 readiness.
3. Only after Phase 5 readiness is green, plan the first CPE/AgentShield package.
4. Close Phase 5 security governance before starting Phase 6 readiness.
5. Start Phase 6 readiness.
6. Only after Phase 6 readiness is green, plan the first EvolutionEngine skeleton package.

Phase 5 readiness must confirm:

- Phase 4 is closed and uses `docs/phase4/phase-4-closure-status.md` as its source;
- service/rule/channel boundaries are ready for security governance;
- CPE and AgentShield entry points are identified before implementation;
- persistent task-event replay is not mixed into the Phase 5 startup package;
- `feishu.route_callback` remains a bounded compatibility layer with delete criteria.

Phase 6 readiness must confirm:

- Phase 5 is closed;
- self-evolution stays semi-automatic at first;
- suggestions require approval before applying;
- applied changes can be rolled back;
- EvolutionEngine, evolvers, TemplateMarket, and observability work through service boundaries.

## Explicit Non-Goals

This continuation document does not authorize implementation work.

Do not implement CPE in the retrospective.
Do not implement AgentShield in the retrospective.
Do not start EvolutionEngine in the retrospective.
Do not start TemplateMarket in the retrospective.
The explicit audit markers are: do not implement CPE, do not implement AgentShield, do not start EvolutionEngine, and do not start TemplateMarket.
Do not implement persistent task-event replay in the retrospective.
Do not delete `feishu.route_callback` unless a later migration package satisfies its delete criteria.
Do not expand panel/API/channel responsibilities to make retrospective findings easier to patch.

## Verification Discipline

Every follow-up package after this retrospective must use TDD:

1. write the RED test first;
2. run it and confirm the expected failure;
3. implement the minimal GREEN change;
4. run focused tests;
5. run related architecture and module regression;
6. run router/panel regression;
7. run full pytest;
8. run `git diff --check`;
9. check `git status --short`.

For the current continuation package, the focused tests are:

```bash
pytest tests/test_phase1_4_retrospective_continuation_audit.py -q
pytest tests/test_phase4_closure_audit.py tests/test_phase3_closure_audit.py -q
```

Before moving from retrospective into Phase 5 readiness, also run:

```bash
pytest tests/test_panel_api.py tests/test_panel_control_plane_boundary.py tests/test_phase3_closure_audit.py tests/test_phase4_closure_audit.py -q
pytest tests/test_router.py tests/test_panel_api.py tests/test_feishu_path.py tests/test_e2e_scenarios.py tests/test_pipeline_executors.py -q
pytest -q
git diff --check
git status --short
```

## Next Step

Use this document as the first reference during the Phase 1-4 retrospective. After the retrospective, continue with a Phase 5 readiness package only if the retrospective does not expose a blocking Phase 1-4 boundary defect.
