from __future__ import annotations

from typing import Literal

from pydantic import JsonValue

from smart_home_sim.domain.report import ValidationIssue
from smart_home_sim.validation.codes import STABLE_ISSUE_CODES, WARNING_ISSUE_CODES


def issue(
    code: str,
    level: Literal["structure", "referential", "temporal", "semantic"],
    path: str,
    message: str,
    severity: Literal["error", "warning"] = "error",
    details: dict[str, JsonValue] | None = None,
) -> ValidationIssue:
    if code not in STABLE_ISSUE_CODES:
        raise ValueError(f"Unregistered validation issue code: {code}")
    expected_severity = "warning" if code in WARNING_ISSUE_CODES else "error"
    if severity != expected_severity:
        raise ValueError(
            f"Issue code {code} has frozen severity {expected_severity}, got {severity}"
        )
    return ValidationIssue(
        code=code,
        severity=severity,
        level=level,
        path=path,
        message=message,
        details=details or {},
    )


def duplicate_values(values: list[str]) -> set[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return duplicates
