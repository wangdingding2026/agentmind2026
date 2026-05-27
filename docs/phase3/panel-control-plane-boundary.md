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

For these handlers, panel must not:

- traverse `agent_registry.executors`;
- construct executors;
- write settings, agents, or routes directly;
- reload `rule_engine` directly;
- query task storage directly;
- control Feishu or other channel runtime lifecycle;
- access session, attach, stream, connector discovery, or embedding runtime internals.

## Transition Handlers

These handlers still contain direct runtime/read-side logic and are intentionally classified as migration boundaries, not target architecture:

- `feishu_connect`
- `feishu_disconnect`
- `feishu_status`
- `active_sessions`
- `attach_to_task`
- `panel_task_stream`

Current boundary notes:

- `feishu_connect`, `feishu_disconnect`, and `feishu_status` belong with Phase 4 `ChannelHub` because they own channel lifecycle, app state, and adapter health.
- `active_sessions`, `attach_to_task`, and `panel_task_stream` should move behind a session/stream runtime service when that runtime state is made recoverable.

## Next Migration Direction

The next package should pick one runtime boundary and convert it to a service without widening panel responsibilities. The preferred order is:

1. Session/stream runtime service for attach and active sessions.
2. ChannelHub-backed Feishu lifecycle migration.
