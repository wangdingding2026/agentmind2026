# Task Event Replay Readiness

## Readiness Decision

This document defines task-event replay readiness.

future persistent task-event replay is not implemented in this package.

## Existing Boundaries

TaskEventService owns stored task timeline events.

TaskTimelineService remains the read-side DTO boundary over TaskEventService events.

TaskReplayService owns the service-level replay DTO boundary over TaskTimelineService.

TaskReplayService normalizes replay limits at the service boundary, returns stable missing and found DTOs, and preserves TaskTimelineService event order.

TaskExplanationService may include timeline DTOs through TaskTimelineService.

panel/API/channel remain adapters and must not assemble replay timelines.

## Future Replay Boundary

Replay must use persisted task timeline events.

Replay must not reconstruct live SSE listener queues.

stream_snapshot remains an in-process backlog boundary.

future TaskReplayService should own replay orchestration as a service-level boundary before panel/API/channel adapters consume it.

## Entry Conditions

- TaskEventService event vocabulary remains stable.
- TaskEventService event ordering remains trace-id and creation-time based.
- TaskTimelineService DTO shape remains stable for missing and found timelines.
- Any future replay service starts service-level before panel/API/channel adapters are changed.

## Explicit Non-Goals

- no observability UI in this package;
- no stream runtime behavior changes;
- no panel/API/channel replay assembly;
- no panel/API/channel TaskReplayService adapters in this package;
- no CPE or AgentShield enforcement;
- no customer-content inspection;
- no replay persistence migration.

## Verification Gate

Replay readiness is guarded by task-event replay readiness tests, task-event observability readiness tests, Phase 5 closure tests, panel architecture tests, router/panel regression, and full pytest.

## Next Direction

After this service contract remains green, the next package is `docs/observability/task-replay-adapter-readiness.md`.

That package should decide read-only adapter entry conditions before any panel/API endpoint is implemented. Stream runtime replay, observability UI, channel replay, CPE/AgentShield enforcement, and customer-content inspection remain out of scope until separate packages are approved.
