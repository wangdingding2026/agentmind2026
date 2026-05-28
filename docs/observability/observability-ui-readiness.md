# Observability UI Readiness

## Readiness Decision

This document defines observability UI readiness.

The panel observability UI exposes a task replay timeline view for task debugging, failure inspection, and partial output review.

Panel Observability UI V1 is implemented as a separate small package.

## UI Boundary

The panel observability UI must consume the existing panel replay endpoint `/panel/api/tasks/{trace_id}/replay`.

The panel replay endpoint is backed by TaskReplayService.

The UI must render the service DTO returned by the panel replay endpoint.

Panel Observability UI V1 renders the existing replay DTO from `/panel/api/tasks/{trace_id}/replay`.

Panel Observability UI V1 remains read-only and does not add backend APIs.

The UI must be read-only.

The UI must support found and missing states.

The UI should use bounded event display.

partial_output events may be displayed from the replay DTO.

## Architecture Constraints

The UI must not assemble timeline data.

The UI must not query TaskEventService.

The UI must not call TaskTimelineService directly.

The UI must not connect to stream queues.

The UI must not reconstruct live SSE listener queues.

The UI must not implement stream runtime replay.

The UI must not create an API replay endpoint.

The UI must not expand channel replay UX.

The UI must not enable CPE or AgentShield enforcement.

The UI must not inspect customer content.

## Explicit Non-Goals

- no API replay endpoint;
- no channel replay UX expansion;
- no stream runtime replay;
- no live SSE listener queue persistence or restoration;
- no CPE or AgentShield enforcement;
- no customer-content inspection;
- no TaskEventService schema change;
- no TaskTimelineService ordering or query change;
- no SessionRuntimeService change.

## Verification Gate

Observability UI readiness is guarded by readiness audit tests, task-event closeout tests, architecture final closeout tests, panel architecture tests, router/panel regression, and full pytest.

## Next Direction

Future observability UI work beyond V1 requires a separate package.
