# Feishu Route Callback Deletion Readiness

## Readiness Decision

This document defines Feishu route_callback deletion readiness.

`feishu.route_callback` fallback has been removed and is deleted in this package.

## Implemented Deletion

ChannelHub owns Feishu channel lifecycle, status, and standard message routing glue.

ChannelHub no longer constructs `route_callback`.

FeishuAdapter no longer executes `route_callback`.

The standard inbound path uses `ChannelMessage`.

The standard `message_callback` path remains supported.

Feishu discussion stop handling remains behind ChannelHub.

## Explicit Non-Goals

- no new Feishu business behavior;
- no route_stream fallback expansion;
- no channel replay adapter;
- no observability UI;
- no CPE or AgentShield enforcement;
- no customer-content inspection;
- no TaskEventService schema change;
- no SessionRuntimeService change.

## Verification Gate

Feishu route_callback deletion is guarded by readiness audit tests, ChannelHub tests, Feishu adapter tests, Phase 4 closure tests, panel architecture tests, router/panel regression, and full pytest.

## Next Direction

Overall architecture final closeout is tracked in `docs/architecture/final-closeout-status.md`.

Future Feishu work should use the standard `message_callback` / `ChannelMessage` path and keep panel/startup as adapters.
