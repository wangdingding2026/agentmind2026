# AgentMind Phase 2 Memory Retrieval Eval Quality Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the memory retrieval fixture from a shape check into a deterministic card-first quality regression that validates hit rate, isolation, conflict surfacing, result expansion, and continuation.

**Architecture:** Add a lightweight test-only evaluator under `tests/helpers/`. It seeds `MemoryService` through the public write API and evaluates the target Phase 2 memory path: `memory_cards` search, `result_sets` expansion/continuation, `raw_memory` lookup, Working Memory context, and conflict hints. It does not use legacy `memory_entries` as the evaluated path.

**Tech Stack:** Python 3.12, pytest, YAML fixture, existing `MemoryService`, `MemoryRetriever`, `ResultSetService`, `memory_cards`, `raw_memory`, and `result_sets`.

---

## Files

Create:

- `tests/helpers/memory_retrieval_eval_runner.py`

Modify:

- `tests/test_memory_retrieval_eval.py`

Do not modify in this package:

- `src/agentmind/storage/memory.py`
- `src/agentmind/memory/sqlite_store.py`
- `tests/fixtures/memory_retrieval_cases.yaml` unless a fixture is invalid.

## Scope

In scope:

- Seed fixture cases into the current memory architecture.
- Evaluate deterministic categories:
  - topic query
  - date query
  - agent source
  - current session working memory
  - historical session card recall
  - conflict memory
  - expand result
  - more results
  - sensitive isolation
- Report hit rate and per-case pass/fail details.

Out of scope:

- 50-case expansion.
- LLM scoring.
- Performance benchmarking beyond simple deterministic assertions.
- Legacy table quality gates.

## Strict Testing Rules

Every production/test helper change follows RED-GREEN:

1. Add a focused failing test.
2. Run that exact test and confirm it fails for the expected reason.
3. Implement the smallest helper code.
4. Run the exact test and confirm it passes.
5. Run package verification.

Package verification commands:

```bash
pytest tests/test_memory_retrieval_eval.py -q
pytest tests/test_memory_retrieval_eval.py tests/test_memory_conflict_detector.py tests/test_result_set_service.py tests/test_memory_cards_read_path.py tests/test_memory_retrieval_pipeline_cards.py tests/test_memory_layers.py tests/test_memory_layers_semantic.py tests/test_memory.py tests/test_session_service.py tests/test_memory_service_convergence.py -q
pytest tests/test_router.py tests/test_panel_api.py -q
pytest -q
```

---

### Task 1: Add executable quality gate

- [ ] Add failing test that imports `run_memory_retrieval_eval()` and asserts all fixture categories pass with hit rate >= 0.8.
- [ ] Implement evaluator helper with deterministic category checks.

### Task 2: Add Phase 2 invariants

- [ ] Add assertions that evaluated search hits use `_route=memory_cards`, expansion returns raw content, and conflicts surface `_conflict_notice`.
- [ ] Implement any missing test-helper plumbing only.

### Task 3: Package verification

- [ ] Run focused tests.
- [ ] Run memory/session related tests.
- [ ] Run router/panel regression.
- [ ] Run full suite.
