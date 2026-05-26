# AgentMind Phase 0 Baseline Report

Date: 2026-05-26

## Scope

This report records the pre-implementation baseline before Phase 1 service-layer
work. No production behavior changes are included in this checkpoint.

## Repository Baseline

- Local git repository initialized at project root.
- Initial baseline commit: `4b064f1 chore: establish initial project baseline`.
- Current implementation branch: `master`.
- Remote repository: none configured.

## Environment

- Python: `3.12.4`
- Test framework: `pytest`

## Test Collection

Command:

```bash
pytest --collect-only -q
```

Observed result:

```text
331 tests collected in 0.26s
```

## Full Test Baseline

Command:

```bash
pytest -q
```

Observed result before adding the Phase 0 retrieval fixture tests:

```text
316 passed, 15 failed, 4 warnings in 36.47s
```

Observed result after adding the two Phase 0 retrieval fixture tests:

```text
318 passed, 15 failed, 4 warnings in 35.90s
```

The failure set stayed in the same two known groups described below.

## Known Failure Groups

### 1. Test isolation leaks into real user data path

Several executor and Feishu-path tests write through `agentmind.storage.db` to
the real default `~/.agentmind` path instead of a temporary test directory.
Inside the sandbox this produces either `PermissionError` or readonly SQLite
errors.

Representative failures:

- `tests/test_e2e_scenarios.py::TestScenarioSelfReply::test_self_reply_json`
- `tests/test_e2e_scenarios.py::TestScenarioSelfReply::test_self_reply_text`
- `tests/test_feishu_path.py::TestRouteStream::test_normal_message_routes_to_agent`
- `tests/test_feishu_path.py::TestRouteStream::test_self_reply_yields_text`
- `tests/test_feishu_path.py::TestRouteStream::test_response_path_json_extraction`
- `tests/test_pipeline_executors.py::TestSelfReplyExecutor::test_run_json`
- `tests/test_pipeline_executors.py::TestSelfReplyExecutor::test_run_stream`
- `tests/test_pipeline_executors.py::TestSelfReplyExecutor::test_run_text`
- `tests/test_pipeline_executors.py::TestSingleAgentStreamFallback::test_run_stream_first_succeeds`
- `tests/test_pipeline_executors.py::TestSingleAgentStreamFallback::test_run_stream_first_fails_no_chunk_tries_next`
- `tests/test_pipeline_executors.py::TestSingleAgentRunText::test_run_text_with_response_path`
- `tests/test_pipeline_executors.py::TestSingleAgentRunText::test_run_text_without_response_path_streams`

Observed errors:

```text
PermissionError: [Errno 1] Operation not permitted: '/Users/jacky/.agentmind/data/results/t1.txt'
sqlite3.OperationalError: attempt to write a readonly database
```

### 2. Embedding status tests depend on local machine state

The current machine has a local embedding provider installed, so panel status
returns `本地模型已安装`. Tests currently assume no local model exists.

Representative failures:

- `tests/test_panel_api.py::TestEmbeddingStatus::test_status_disabled`
- `tests/test_panel_api.py::TestEmbeddingStatus::test_status_with_external_api`
- `tests/test_panel_api.py::TestEmbeddingStatus::test_status_no_source`

Observed mismatch:

```text
Expected: 未配置
Actual:   本地模型已安装
```

## Phase 0 Additions

The initial memory retrieval evaluation fixture was added at:

- `tests/fixtures/memory_retrieval_cases.yaml`

The fixture contract test was added at:

- `tests/test_memory_retrieval_eval.py`

Verification:

```bash
pytest tests/test_memory_retrieval_eval.py -q
```

Observed result:

```text
2 passed in 0.02s
```

## Phase 1 Entry Criteria

Before starting Phase 1, the team should explicitly accept one of these paths:

1. Fix the current test isolation and embedding-environment failures first.
2. Proceed with Phase 1 while treating the 15 failures above as known baseline
   failures, and require all Phase 1 touched-module tests to pass.

Recommended path: fix the test isolation and embedding-environment failures
before broad service-layer refactoring.
