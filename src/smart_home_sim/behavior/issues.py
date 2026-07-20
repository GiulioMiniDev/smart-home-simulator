from __future__ import annotations

from typing import Literal

from pydantic import JsonValue

from smart_home_sim.domain.behavior_report import (
    BEHAVIOR_ISSUE_CODES,
    BehaviorValidationIssue,
)


def behavior_issue(
    code: str,
    stage: Literal["structure", "catalog", "graph", "compatibility"],
    path: str,
    message: str,
    *,
    details: dict[str, JsonValue] | None = None,
) -> BehaviorValidationIssue:
    if code not in BEHAVIOR_ISSUE_CODES:
        raise ValueError(f"Unregistered behavior issue code: {code}")
    return BehaviorValidationIssue(
        code=code,
        stage=stage,
        path=path,
        message=message,
        details=details or {},
    )
