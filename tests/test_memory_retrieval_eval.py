from pathlib import Path

import yaml


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "memory_retrieval_cases.yaml"


def test_memory_retrieval_fixture_exists_and_has_required_shape():
    assert FIXTURE_PATH.exists()

    data = yaml.safe_load(FIXTURE_PATH.read_text(encoding="utf-8"))

    assert isinstance(data, dict)
    assert data.get("version") == 1
    cases = data.get("cases")
    assert isinstance(cases, list)
    assert len(cases) >= 8

    required_fields = {
        "id",
        "category",
        "query",
        "expected_behavior",
        "seed_memories",
    }
    for case in cases:
        assert required_fields <= set(case)
        assert isinstance(case["seed_memories"], list)
        assert case["seed_memories"]


def test_memory_retrieval_fixture_covers_phase0_categories():
    data = yaml.safe_load(FIXTURE_PATH.read_text(encoding="utf-8"))
    categories = {case["category"] for case in data["cases"]}

    assert {
        "current_session",
        "historical_session",
        "date_query",
        "topic_query",
        "agent_source",
        "expand_result",
        "more_results",
        "conflict_memory",
        "sensitive_isolation",
    } <= categories


def test_memory_retrieval_fixture_runs_card_first_quality_gate():
    from tests.helpers.memory_retrieval_eval_runner import run_memory_retrieval_eval

    report = run_memory_retrieval_eval(FIXTURE_PATH)

    assert report["total"] >= 9
    assert report["passed"] == report["total"], report
    assert report["hit_rate"] >= 0.8, report
    assert not report["failures"], report


def test_memory_retrieval_eval_reports_phase2_invariants():
    from tests.helpers.memory_retrieval_eval_runner import run_memory_retrieval_eval

    report = run_memory_retrieval_eval(FIXTURE_PATH)
    invariants = report["invariants"]

    assert invariants["card_first_hits"] >= 4
    assert invariants["raw_expansion_checked"] is True
    assert invariants["result_pagination_checked"] is True
    assert invariants["conflict_notice_checked"] is True
    assert invariants["sensitive_shared_isolation_checked"] is True
