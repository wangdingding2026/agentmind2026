# Feishu Route Callback Deletion Readiness

## Readiness Decision

This document defines Feishu route_callback deletion readiness.

`feishu.route_callback` remains a bounded migration fallback and is not deleted in this package.

## Current Boundaries

ChannelHub owns Feishu channel lifecycle, status, and standard message routing glue.

The standard inbound path uses `ChannelMessage`.

FeishuAdapter prefers `message_callback` over `route_callback`.

The legacy fallback path still exists through `route_callback`.

The compatibility boundary remains explicit in ChannelHub with status `migration_fallback`.

## Deletion Blockers

Deletion is blocked until all supported Feishu inbound paths use `ChannelMessage`.

Deletion is blocked while compatibility fallback tests still document supported legacy behavior.

Deletion is blocked until startup and panel Feishu lifecycle paths remain green without relying on route_callback fallback behavior.

## Future Deletion Package Requirements

A future deletion package must:

- remove `route_callback` construction from ChannelHub;
- remove fallback execution from FeishuAdapter;
- remove legacy fallback tests deliberately;
- keep the standard `message_callback` / `ChannelMessage` path green;
- keep Feishu discussion stop handling behind ChannelHub;
- keep panel and startup code as adapters.

## Explicit Non-Goals

- no deletion in this package;
- no new Feishu business behavior;
- no route_stream fallback expansion;
- no channel replay adapter;
- no observability UI;
- no CPE or AgentShield enforcement;
- no customer-content inspection;
- no TaskEventService schema change;
- no SessionRuntimeService change.

## Verification Gate

Feishu route_callback deletion readiness is guarded by readiness audit tests, ChannelHub tests, Feishu adapter tests, Phase 4 closure tests, panel architecture tests, router/panel regression, and full pytest.

## Next Direction

If Feishu fallback cleanup remains the priority, the next package should be a deletion implementation plan that removes the fallback only after this readiness gate stays green.
