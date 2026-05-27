# Phase 4 Closure Status

## Closure Decision

Phase 4 is closed for control-panel runtime and channel boundary work.

This closure keeps the architecture rule intact:

- panel and startup code stay adapters;
- `ChannelHub` owns channel lifecycle, channel status, and Feishu channel glue;
- `SessionRuntimeService` owns panel-facing runtime views and controls;
- runtime primitives remain below services and do not leak back into panel handlers.

## Completed Boundaries

- `ChannelHub` owns channel lifecycle and channel status.
- Panel Feishu handlers delegate `feishu_connect`, `feishu_disconnect`, and `feishu_status` to `ChannelHub`.
- startup Feishu auto-start delegates to `ChannelHub`.
- Feishu inbound messages convert to `ChannelMessage` before business dispatch.
- Feishu discussion stop-word handling lives behind the `ChannelHub` standard message boundary.
- `SessionRuntimeService` owns `active_sessions`, `attach_to_task`, `panel_task_stream`, and `stream_snapshot`.
- active discussion state and attach bindings have startup recovery through `SessionRuntimeService`.

## Compatibility Boundaries

- `feishu.route_callback` remains a migration fallback only; delete after Feishu inbound handling no longer needs `route_callback` fallback and all supported Feishu inbound paths use `ChannelMessage`.
- live stream listener queues remain volatile and are not restored. `stream_snapshot` exposes only in-process backlog snapshots.

## Explicit Non-Goals

- persistent task-event replay is deferred to a later observability/task-event package.
- Phase 5 readiness does not require deleting `feishu.route_callback`; it requires keeping it bounded and documented.
- Phase 5 CPE and AgentShield work is not part of Phase 4.

## Verification Gate

Phase 4 closure is guarded by ChannelHub, Feishu adapter, startup, panel boundary, session runtime, stream, router/panel, and full pytest suites.

## Next Direction

Start Phase 5 readiness in `docs/phase5/phase-5-readiness.md` only after this closure audit remains green.
