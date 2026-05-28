# Task Replay Adapter Readiness

## Readiness Decision

This document defines read-only TaskReplay adapter readiness.

panel, API, and channel replay endpoints are not implemented in this package.
endpoint implementation requires a separate small package.

## Existing Service Contract

TaskReplayService service contract already exists as the service-level replay DTO boundary over TaskTimelineService.

TaskReplayService normalizes limits, preserves TaskTimelineService event order, and returns stable missing and available replay DTOs.

panel/API/channel currently have no replay endpoint.

## Future Read-Only Adapter Boundary

Any future read-only adapter must call TaskReplayService.

The adapter DTO must pass through the service DTO, including:

- `trace_id`
- `found`
- `event_count`
- `source`
- `replay_status`
- `limit`
- `timeline`

A future adapter must not assemble timeline data itself.

A future adapter must not query TaskEventService.

A future adapter must not connect to stream queues.

TaskReplayService remains the only replay DTO source for adapter-facing read-only replay.

## Explicit Non-Goals

- no panel replay endpoint in this package;
- no API replay endpoint in this package;
- no channel replay adapter in this package;
- does not implement stream runtime replay;
- does not implement observability UI;
- does not enable CPE or AgentShield enforcement;
- does not inspect customer content;
- no TaskEventService schema change;
- no TaskTimelineService ordering or query change;
- no SessionRuntimeService change;
- no `feishu.route_callback` migration expansion.

## Verification Gate

TaskReplay adapter readiness is guarded by adapter readiness tests, task-event replay readiness tests, TaskReplayService tests, panel architecture tests, router/panel regression, and full pytest.

## Next Direction

If a read-only replay endpoint is needed, create a separate small implementation package that wires a panel or API adapter to TaskReplayService and keeps the adapter as pass-through only.

Stream runtime replay, observability UI, channel replay, governance enforcement, and customer-content inspection remain separate future decisions.
