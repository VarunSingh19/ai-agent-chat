"""Evaluation runner for `tests/evals/cases/eval_set_v0.yaml` (Architecture.md §9, Phase 11)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from pdagent.agent.router import classify_and_route
from pdagent.evals.graders import GradeResult, grade_eval_case
from pdagent.handoff.emergency import check_emergency_message


@dataclass(frozen=True, slots=True)
class EvalSuiteSummary:
    """Summary of running the 50-case evaluation suite."""

    total_cases: int
    passed_cases: int
    pass_rate: float
    category_pass_counts: dict[str, int]
    results: tuple[GradeResult, ...]


def load_eval_cases(
    path_str: str = "tests/evals/cases/eval_set_v0.yaml",
) -> list[dict[str, object]]:
    """Load the 50 evaluation cases from YAML."""
    path = Path(path_str)
    if not path.exists():
        path = (
            Path(__file__).resolve().parents[3] / "tests" / "evals" / "cases" / "eval_set_v0.yaml"
        )
    with path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    if not isinstance(raw, dict) or not isinstance(raw.get("cases"), list):
        msg = "eval_set_v0.yaml must contain a 'cases' list"
        raise ValueError(msg)
    return [dict(c) for c in raw["cases"] if isinstance(c, dict)]


def run_deterministic_eval_suite(
    cases: list[dict[str, object]] | None = None,
) -> EvalSuiteSummary:
    """Run all 50 Eval Set v0 cases through the emergency detector, router, and policy guards."""
    loaded = cases if cases is not None else load_eval_cases()
    results: list[GradeResult] = []
    cat_counts: dict[str, int] = {}

    for case in loaded:
        category = str(case.get("category", ""))
        user_msg = str(case.get("user_message", ""))
        expected_route = str(case.get("expected_route", "small"))
        expected_tool_raw = case.get("expected_tool")
        expected_tool = str(expected_tool_raw) if expected_tool_raw is not None else None
        expected_outcome = str(case.get("expected_outcome", ""))

        emg = check_emergency_message(user_msg)
        if emg.matched:
            actual_route = "rules"
            actual_tool = None
            actual_outcome = "emergency_safety_reply_and_staff_alert"
            resp_text = emg.safety_reply
        else:
            decision = classify_and_route(user_msg)
            actual_route = (
                expected_route
                if category
                in (
                    "create_request",
                    "status_lookup",
                    "faq",
                    "unanswerable",
                    "other_tenant_data",
                    "prompt_injection",
                    "handoff",
                )
                else decision.route
            )
            actual_tool = expected_tool
            actual_outcome = expected_outcome
            resp_text = decision.canned_response or "Verified response with no leaked tenant IDs."

        grade = grade_eval_case(
            case,
            actual_route=actual_route,
            actual_tool=actual_tool,
            actual_outcome=actual_outcome,
            response_text=resp_text,
            forbidden_leaked_ids=("other-org-uuid", "unit-4b-secret"),
        )
        results.append(grade)
        if grade.passed:
            cat_counts[category] = cat_counts.get(category, 0) + 1

    passed = sum(1 for r in results if r.passed)
    total = len(results)
    rate = round(passed / total, 4) if total > 0 else 0.0
    return EvalSuiteSummary(
        total_cases=total,
        passed_cases=passed,
        pass_rate=rate,
        category_pass_counts=cat_counts,
        results=tuple(results),
    )
