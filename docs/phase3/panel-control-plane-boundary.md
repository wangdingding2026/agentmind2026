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
- control Feishu or other channel runtime lifecycle;
- access session, attach, stream, connector discovery, or embedding runtime internals.

## Transition Handlers

No panel handlers are currently classified as transition boundaries.

Current boundary notes:

- `feishu_connect`, `feishu_disconnect`, and `feishu_status` now delegate to Phase 4 `ChannelHub`.
- Startup Feishu auto-start now delegates to Phase 4 `ChannelHub`; startup remains a lifecycle adapter.
- Feishu inbound messages now convert to standard `ChannelMessage` before business dispatch. `ChannelHub` owns the standard Feishu routing glue, while the old Feishu `route_callback` exists only as a migration fallback.
- Feishu discussion stop-word handling now lives behind the `ChannelHub` standard message boundary; `FeishuAdapter` no longer owns the session stop rule.
- `active_sessions`, `attach_to_task`, and `panel_task_stream` now delegate to `SessionRuntimeService`; active discussion state and attach bindings have startup recovery support, while stream listener queues remain volatile live runtime state for a later package.

## Next Migration Direction

The next package should pick one runtime boundary below the panel and convert it without widening panel responsibilities. The preferred order is:

1. Stream resumability design that does not try to persist live queue objects.
2. Remaining channel runtime concerns behind service/channel boundaries.
