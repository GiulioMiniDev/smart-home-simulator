from __future__ import annotations

from typing import Literal

from smart_home_sim.domain.report import ValidationIssue


def issue(
    code: str,
    level: Literal["structure", "referential", "temporal", "semantic"],
    path: str,
    message: str,
    severity: Literal["error", "warning"] = "error",
) -> ValidationIssue:
    return ValidationIssue(
        code=code,
        severity=severity,
        level=level,
        path=path,
        message=message,
    )


def duplicate_values(values: list[str]) -> set[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return duplicates


def minutes_since_midnight(value: object) -> float:
    return value.hour * 60 + value.minute + value.second / 60 + value.microsecond / 60_000_000
