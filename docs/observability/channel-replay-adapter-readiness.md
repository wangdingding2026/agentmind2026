# Channel Replay Adapter Readiness

## Readiness Decision

This document defines channel replay adapter readiness.

The read-only channel replay adapter is useful for Feishu users who need task replay diagnostics without opening the panel.

Feishu `/replay <trace_id>` V1 is implemented as a separate small package.

## Feishu V1 UX Boundary

Feishu V1 should support `/replay <trace_id>`.

The command is explicit command only.

The adapter should return a concise text summary.

The summary should use a bounded event count.

Feishu V1 has no natural-language 'last task' resolution.

Feishu V1 has no pagination in V1.

Feishu V1 has no Feishu card UI in V1.

## Adapter Boundary

The read-only channel replay adapter must call TaskReplayService.

ChannelReplayService owns explicit channel replay command parsing and concise text formatting.

ChannelHub calls ChannelReplayService before normal Feishu routing.

FeishuAdapter remains a protocol adapter and does not know replay semantics.

The adapter DTO must be derived from the TaskReplayService DTO.

The adapter must not assemble timeline data.

The adapter must not query TaskEventService.

The adapter must not connect to stream queues.

The adapter must not reconstruct live SSE listener queues.

The adapter must not implement stream runtime replay.

The adapter must not implement observability UI.

The adapter must not enable CPE or AgentShield enforcement.

The adapter must not inspect customer content.

TaskReplayService remains the replay DTO source for channel-facing read-only replay.

## Explicit Non-Goals

- no API replay endpoint;
- no observability UI;
- no stream runtime replay;
- no live SSE listener queue persistence or restoration;
- no CPE or AgentShield enforcement;
- no customer-content inspection;
- no natural-language task lookup;
- no cross-channel replay routing;
- no Feishu card UI;
- no pagination;
- no TaskEventService schema change;
- no TaskTimelineService ordering or query change;
- no SessionRuntimeService change.

## Verification Gate

Channel replay adapter readiness is guarded by readiness audit tests, task-event closeout tests, architecture final closeout tests, ChannelHub tests, Feishu adapter tests, panel architecture tests, router/panel regression, and full pytest.

## Next Direction

Feishu `/replay <trace_id>` V1 is implemented through ChannelReplayService.

Observability product closeout is tracked in `docs/observability/observability-product-closeout-status.md`.

Future channel replay work beyond V1 requires a separate package and must keep FeishuAdapter as a protocol adapter, keep ChannelHub as channel glue, and call TaskReplayService for replay data.
