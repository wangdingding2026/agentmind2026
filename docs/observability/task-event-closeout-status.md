# Task Event Closeout Status

## Closeout Decision

The observability/task-event route is closed.

This closeout decision covers persisted task-event production, task timeline query, task explanation timeline inclusion, service-level replay DTOs, the read-only panel replay adapter, and partial-output event capture.

No new runtime behavior is added in this closeout package.

## Completed Boundaries

TaskEventService owns stored task timeline events.

TaskService produces lifecycle task events for task start, routing start, agent selection, execution start, completion, and failure.

TaskService produces `partial_output` task events for streaming executor output.

TaskTimelineService owns read-side timeline DTO assembly over TaskEventService events.

TaskExplanationService includes timeline data through TaskTimelineService.

TaskReplayService owns the service-level replay DTO boundary over TaskTimelineService.

The panel `task_replay` handler calls TaskReplayService and returns the service DTO.

panel/API/channel remain adapters.

Replay uses persisted task timeline events.

Replay does not reconstruct live SSE listener queues.

## Runtime Boundary

stream_snapshot remains in-process backlog only.

live SSE listener queues are not persisted or restored.

Persistent replay is represented by stored task timeline events, not raw stream queue objects.

## Deferred Work

- no API replay endpoint;
- no channel replay adapter;
- no observability UI;
- no stream runtime replay;
- no live SSE listener queue persistence or restoration;
- no CPE or AgentShield enforcement;
- no customer-content inspection;
- no TaskEventService schema change;
- no TaskTimelineService ordering or query change;
- no SessionRuntimeService change;
- no `feishu.route_callback` migration expansion.

## Verification Gate

Task-event closeout is guarded by closeout audit tests, task-event readiness tests, replay readiness tests, adapter readiness tests, TaskEventService tests, TaskTimelineService tests, TaskReplayService tests, task producer tests, panel architecture tests, router/panel regression, and full pytest.

## Next Direction

Overall architecture final closeout is tracked in `docs/architecture/final-closeout-status.md`.

Feishu `route_callback` fallback deletion is complete in `docs/phase4/feishu-route-callback-deletion-readiness.md`.

Channel replay adapter readiness is tracked in `docs/observability/channel-replay-adapter-readiness.md`.

Future API replay endpoint, channel replay adapter, observability UI, stream runtime replay, governance enforcement, and customer-content inspection require separate packages.

Each future package must keep services responsible for work and panel/API/channel as adapters.
