# Task Event Observability Readiness

## Readiness Decision

This document defines task-event observability readiness.

persistent task-event replay remains a later package. This package only defines boundaries and entry conditions for a future task-event implementation.

## Service Boundaries

TaskService owns task lifecycle state.

TraceService owns routing traces and routing explanation source data.

AuditService owns audit events, governance records, configuration records, and security-relevant records.

Future TaskEventService owns ordered task timeline events.

panel/API/channel remain adapters and must not assemble task-event timelines themselves.

## Future Task Event Shape

The future task-event package should define a stable event model before adding persistence.

The first event vocabulary should include:

- `task_started`
- `routing_started`
- `agent_selected`
- `execution_started`
- `partial_output`
- `completed`
- `failed`

Events should be ordered by trace id and creation time. Event payloads should be structured metadata, not raw stream queue objects.

## Runtime Boundary

stream_snapshot remains in-process backlog only.

live SSE listener queues are not persisted or restored.

Persistent task-event replay should replay stored task timeline events, not reconstruct live SSE listener queues.

## Explicit Non-Goals

- no observability UI in this package;
- no persistent task-event replay in this package;
- no stream runtime behavior changes;
- no panel/API/channel task timeline assembly;
- no CPE or AgentShield enforcement.

## Verification Gate

Task-event readiness is guarded by architecture audit tests plus Phase 4 and Phase 5 closure tests.

## Next Direction

After this readiness gate, the next package can add a minimal TaskEventService skeleton and storage contract. That package should remain service-level only before any replay or panel UI work.
