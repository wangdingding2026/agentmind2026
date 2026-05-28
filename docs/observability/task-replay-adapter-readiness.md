# Task Replay Adapter Readiness

## Readiness Decision

This document defines read-only TaskReplay adapter readiness.

The read-only panel replay endpoint is implemented as an adapter in this package.

API and channel replay endpoints are not implemented in this package.
Additional endpoint implementation requires a separate small package.

## Existing Service Contract

TaskReplayService service contract already exists as the service-level replay DTO boundary over TaskTimelineService.

TaskReplayService normalizes limits, preserves TaskTimelineService event order, and returns stable missing and available replay DTOs.

The panel has a read-only replay endpoint backed by TaskReplayService.

API and channel currently have no replay endpoint.

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

## Implemented Panel Adapter

The panel `task_replay` handler calls TaskReplayService and returns the service DTO.

The panel adapter does not assemble timeline data, query TaskEventService, connect to stream queues, implement stream runtime replay, implement observability UI, enable CPE or AgentShield enforcement, or inspect customer content.

## Explicit Non-Goals

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

This adapter route is closed in `docs/observability/task-event-closeout-status.md`.

Future API replay endpoint, channel replay adapter, observability UI, stream runtime replay, governance enforcement, and customer-content inspection remain separate future decisions.
