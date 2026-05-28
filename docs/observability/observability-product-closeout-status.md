# Observability Product Closeout Status

## Product Closeout Decision

The observability productization route is closed.

This closeout covers service-level replay DTOs, the panel replay adapter, Feishu channel replay V1, and Panel Observability UI V1.

No new runtime behavior is added in this closeout package.

## Completed Product Surfaces

TaskReplayService owns the service-level replay DTO boundary.

The panel `task_replay` handler calls TaskReplayService.

Feishu channel replay V1 is implemented through ChannelReplayService and explicit `/replay <trace_id>` commands.

Panel Observability UI V1 is implemented through the existing `/panel/api/tasks/{trace_id}/replay` adapter.

Panel Observability UI V1 can display persisted timeline events and partial_output events may be displayed from the replay DTO.

panel/API/channel remain adapters.

Replay uses persisted task timeline events.

## Runtime Boundary

stream_snapshot remains in-process backlog only.

live SSE listener queues are not persisted or restored.

Replay does not reconstruct live SSE listener queues.

## Deferred Work

- no API replay endpoint;
- no advanced channel replay UX beyond Feishu `/replay <trace_id>` V1;
- no advanced observability UI beyond Panel Observability UI V1;
- no stream runtime replay;
- no live SSE listener queue persistence or restoration;
- no CPE or AgentShield enforcement;
- no customer-content inspection;
- no TaskEventService schema change;
- no TaskTimelineService ordering or query change;
- no SessionRuntimeService change.

## Verification Gate

Observability product closeout is guarded by product closeout audit tests, task-event closeout tests, channel replay readiness tests, observability UI readiness tests, panel UI tests, TaskReplayService tests, ChannelReplayService tests, panel architecture tests, router/panel regression, and full pytest.

## Next Direction

Future API replay endpoint, advanced channel replay UX, advanced observability UI, stream runtime replay, governance enforcement, and customer-content inspection require separate product decisions and implementation plans.
