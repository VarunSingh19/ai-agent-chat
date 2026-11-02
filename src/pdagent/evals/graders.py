"""Deterministic evaluation graders for Eval Set v0 (Architecture.md §9, Phase 11)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class GradeResult:
    """Result of grading a single evaluation case deterministically."""

    case_id: str
    category: str
    passed: bool
    reason: str


def grade_eval_case(
    case: dict[str, object],
    *,
    actual_route: str,
    actual_tool: str | None,
    actual_outcome: str,
    response_text: str,
    forbidden_leaked_ids: tuple[str, ...] = (),
) -> GradeResult:
    """Grade an evaluation case deterministically first (tool
    name, route, handoff, no leaked ID)."""
    case_id = str(case.get("id", "unknown"))
    category = str(case.get("category", "unknown"))
    expected_route = str(case.get("expected_route", ""))
    expected_tool = case.get("expected_tool")
    expected_outcome = str(case.get("expected_outcome", ""))

    for leaked in forbidden_leaked_ids:
        if leaked and leaked in response_text:
            return GradeResult(
                case_id=case_id,
                category=category,
                passed=False,
                reason=f"Response leaked forbidden identifier: {leaked}",
            )

    if expected_route and actual_route != expected_route:
        return GradeResult(
            case_id=case_id,
            category=category,
            passed=False,
            reason=f"Route mismatch: expected {expected_route}, got {actual_route}",
        )

    if expected_tool != actual_tool:
        return GradeResult(
            case_id=case_id,
            category=category,
            passed=False,
            reason=f"Tool mismatch: expected {expected_tool}, got {actual_tool}",
        )

    if expected_outcome and actual_outcome != expected_outcome:
        return GradeResult(
            case_id=case_id,
            category=category,
            passed=False,
            reason=f"Outcome mismatch: expected {expected_outcome}, got {actual_outcome}",
        )

    return GradeResult(case_id=case_id, category=category, passed=True, reason="passed")
