# Phase 3 Closure Status

## Closure Decision

Phase 3 is closed for platform-core and control-plane service boundaries. The remaining panel runtime transition is Feishu lifecycle, and it should move with Phase 4 `ChannelHub` instead of being patched into another Phase 3 panel service.

This keeps the architecture rule intact:

- panel/API handlers adapt requests and return service results;
- services do the work and compose runtime dependencies;
- rule/core layers own rules and decisions;
- infrastructure modules keep protocol, storage, and runtime primitives.

## Completed Platform-Core Services

- `StrategyManager`: owns enabled routing strategy registration, order, and listing.
- `ProtocolGateway`: owns unified connector invocation surface for CLI, HTTP, MCP, and A2A paths.
- `AgentCapabilityRegistry`: owns agent capability profiles and scoring inputs.
- `OrchestrationEngine`: owns DAG validation, ordering, context instruction building, and orchestration execution path support through the service/orchestration boundary.
- `AuditService`: owns audit event recording/querying and supports control-plane visibility.

## Completed Control-Plane Services

- `ControlPlaneOverviewService`: owns system overview and service status aggregation.
- `AgentControlService`: owns panel agent list/actions/add operations.
- `RuleControlService`: owns panel rule list/save/delete operations.
- `SettingsControlService`: owns settings and Feishu config save payload mapping.
- `SettingsStatusService`: owns settings, Feishu config, and embedding status read-side views.
- `ConnectorDiscoveryService`: owns connector marketplace DTO assembly.
- `SessionRuntimeService`: owns panel-facing active sessions, attach binding, and task stream listener lifecycle.

## Current Panel Boundary

Service-backed panel handlers are guarded by `tests/test_panel_control_plane_boundary.py`.

No panel handlers are currently documented as transition handlers.

`feishu_connect`, `feishu_disconnect`, `feishu_status`, and startup Feishu auto-start now delegate to Phase 4 `ChannelHub`. Feishu inbound messages now convert to standard `ChannelMessage` before business dispatch, and `ChannelHub` owns the standard Feishu routing glue. The old Feishu `route_callback` remains only as a migration fallback.

## Compatibility Boundaries

The current compatibility/fallback boundaries are acceptable only as migration support:

- existing executor implementations remain behind `ProtocolGateway` connector wrappers;
- existing in-process session and stream registries remain below `SessionRuntimeService`;
- existing config files remain below `ConfigService` and related control services;
- old panel routes keep response shapes while delegating to services.

These are not new long-term architecture dependencies. Future deletion or consolidation should move toward service/channel boundaries, not back into panel/API handlers.

## Phase 4 Entry Recommendation

Phase 4 started with `ChannelHub`.

Completed first packages:

1. Added a `ChannelHub` service boundary for channel lifecycle and status.
2. Moved Feishu connect/disconnect/status from panel into `ChannelHub`.
3. Kept panel as request adapter only.
4. Added architecture tests that prevent channel lifecycle logic from returning to `panel/server.py`.
5. Moved startup Feishu auto-start from `startup.py` direct adapter construction into `ChannelHub`.
6. Moved Feishu inbound message dispatch toward standard `ChannelMessage` with `ChannelHub` routing glue and legacy callback fallback.
7. Moved Feishu discussion stop-word handling out of `FeishuAdapter` and behind the `ChannelHub` standard message boundary.
8. Added startup recovery for persisted active discussion runtime state behind `SessionRuntimeService`; stream listener queues remain volatile.

Next, continue reducing runtime-only state behind service/channel boundaries. The preferred next package is attach binding persistence/recovery through `SessionRuntimeService`, followed by a separate stream resumability design that does not try to persist live queue objects.
