"""Unit tests validating the 50-case Eval Set v0 schema and coverage (Phase 0 deliverable)."""

from __future__ import annotations

from pathlib import Path

import yaml

REQUIRED_CATEGORIES = {
    "faq",
    "status_lookup",
    "create_request",
    "unanswerable",
    "other_tenant_data",
    "prompt_injection",
    "emergency",
    "handoff",
}


def test_eval_set_v0_has_50_redacted_cases_and_covers_all_categories() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    eval_file = repo_root / "tests" / "evals" / "cases" / "eval_set_v0.yaml"
    assert eval_file.exists(), "tests/evals/cases/eval_set_v0.yaml must exist"

    raw = yaml.safe_load(eval_file.read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    cases = raw.get("cases")
    assert isinstance(cases, list)
    assert len(cases) == 50

    seen_ids: set[str] = set()
    seen_categories: set[str] = set()

    for case in cases:
        assert isinstance(case, dict)
        case_id = str(case["id"])
        assert case_id not in seen_ids, f"Duplicate eval case id: {case_id}"
        seen_ids.add(case_id)

        category = str(case["category"])
        assert category in REQUIRED_CATEGORIES
        seen_categories.add(category)

        assert case["role"] in {"tenant", "staff", "org_admin"}
        assert case["channel"] in {"web", "app", "sms"}
        assert isinstance(case["user_message"], str) and case["user_message"].strip()
        assert case["expected_route"] in {"rules", "small", "large"}
        assert isinstance(case["expected_outcome"], str)
        assert isinstance(case["grader"], str)

        if category == "emergency":
            assert case.get("providers_down") is True
            assert case["expected_route"] == "rules"
            assert case["expected_handoff"] == "waiting"

    assert seen_categories == REQUIRED_CATEGORIES
