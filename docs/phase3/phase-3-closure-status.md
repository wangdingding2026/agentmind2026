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

The only documented transition handlers are:

- `feishu_connect`
- `feishu_disconnect`
- `feishu_status`

These handlers still own channel lifecycle state in `app.state`, adapter start/stop, and direct Feishu adapter health checks. They belong in Phase 4 `ChannelHub`, because the target boundary is channel lifecycle management, not another panel helper.

## Compatibility Boundaries

The current compatibility/fallback boundaries are acceptable only as migration support:

- existing executor implementations remain behind `ProtocolGateway` connector wrappers;
- existing in-process session and stream registries remain below `SessionRuntimeService`;
- existing config files remain below `ConfigService` and related control services;
- old panel routes keep response shapes while delegating to services.

These are not new long-term architecture dependencies. Future deletion or consolidation should move toward service/channel boundaries, not back into panel/API handlers.

## Phase 4 Entry Recommendation

Start Phase 4 with `ChannelHub`.

Preferred first package:

1. Add a `ChannelHub` service boundary for channel lifecycle and status.
2. Move Feishu connect/disconnect/status from panel into `ChannelHub`.
3. Keep panel as request adapter only.
4. Add architecture tests that prevent channel lifecycle logic from returning to `panel/server.py`.

After `ChannelHub`, schedule persistence/recovery work for session and stream runtime state. That work should build on `SessionRuntimeService`; it should not move runtime state back into panel.
