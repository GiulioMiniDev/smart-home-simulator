from __future__ import annotations

from typing import Literal

from pydantic import JsonValue

from smart_home_sim.domain.compilation import (
    COMPILATION_ISSUE_CODES,
    COMPILATION_WARNING_CODES,
    CompilationIssue,
)


def compilation_issue(
    code: str,
    stage: Literal["input", "preflight", "main_plan", "contingency", "output"],
    path: str,
    message: str,
    details: dict[str, JsonValue] | None = None,
) -> CompilationIssue:
    if code not in COMPILATION_ISSUE_CODES:
        raise ValueError(f"Unregistered compilation issue code: {code}")
    severity = "warning" if code in COMPILATION_WARNING_CODES else "error"
    return CompilationIssue(
        code=code,
        severity=severity,
        stage=stage,
        path=path,
        message=message,
        details=details or {},
    )
