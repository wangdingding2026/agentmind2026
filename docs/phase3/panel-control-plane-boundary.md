# Phase 3 Panel Control Plane Boundary

## Target Architecture

Panel HTTP handlers are adapters. They parse request inputs, call service-layer methods, translate service `None` results into HTTP errors when needed, and return service results.

The service layer owns control-plane work: task views, agent management views and actions, rule/config saves, audit/event views, routing explanations, and control overview aggregation.

The rule/core layer owns rules and decisions. Panel and services may call rule/core boundaries, but panel must not build routing rules, mutate rule files, or reload rule engines directly for service-backed paths.

## Service-Backed Handlers

These handlers are already migrated and should stay service delegated:

- `list_tasks`
- `task_stats`
- `recent_errors`
- `task_detail`
- `task_explanation`
- `task_replay`
- `routing_trace`
- `audit_events`
- `routing_explanation`
- `routing_strategies`
- `control_overview`
- `list_agents`
- `list_agent_capabilities`
- `add_agent`
- `restart_agent`
- `update_agent_tags`
- `toggle_agent`
- `service_status`
- `memory_search`
- `memory_stats`
- `memory_delete`
- `memory_cleanup`
- `service_metrics`
- `list_connectors`
- `feishu_get_config`
- `feishu_save_config`
- `list_rules`
- `save_rule`
- `delete_rule`
- `get_settings`
- `save_settings`
- `embedding_status`
- `active_sessions`
- `attach_to_task`
- `panel_task_stream`
- `feishu_connect`
- `feishu_disconnect`
- `feishu_status`

For these handlers, panel must not:

- traverse `agent_registry.executors`;
- construct executors;
- write settings, agents, or routes directly;
- reload `rule_engine` directly;
- query task storage directly;
- assemble, replay, or query task replay timelines directly; panel replay adapters must call `TaskReplayService` and return its DTO.
- control Feishu or other channel runtime lifecycle;
- access session, attach, stream, connector discovery, or embedding runtime internals.

## Transition Handlers

No panel handlers are currently classified as transition boundaries.

Current boundary notes:

- `feishu_connect`, `feishu_disconnect`, and `feishu_status` now delegate to Phase 4 `ChannelHub`.
- Startup Feishu auto-start now delegates to Phase 4 `ChannelHub`; startup remains a lifecycle adapter.
- Feishu inbound messages now convert to standard `ChannelMessage` before business dispatch. `ChannelHub` owns the standard Feishu routing glue, while the old `feishu.route_callback` exists only as a migration fallback. Delete after Feishu inbound handling no longer needs `route_callback` fallback and all supported Feishu inbound paths use `ChannelMessage`.
- Feishu discussion stop-word handling now lives behind the `ChannelHub` standard message boundary; `FeishuAdapter` no longer owns the session stop rule.
- `active_sessions`, `attach_to_task`, and `panel_task_stream` now delegate to `SessionRuntimeService`; active discussion state and attach bindings have startup recovery support. Stream resumability is limited to in-process backlog snapshots, and live listener queues remain volatile.

## Next Migration Direction

The next package should pick one runtime boundary below the panel and convert it without widening panel responsibilities. The preferred order is:

1. Phase 5 readiness, using `docs/phase4/phase-4-closure-status.md` as the Phase 4 closure source.
2. Decide whether persistent task-event replay belongs in a later observability package rather than Phase 4 live stream runtime.
