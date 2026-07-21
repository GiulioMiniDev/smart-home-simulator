from __future__ import annotations

from typing import Any

from smart_home_sim.domain.environment import EnvironmentValidationIssue


def environment_issue(
    code: str,
    stage: str,
    path: str,
    message: str,
    *,
    details: dict[str, Any] | None = None,
) -> EnvironmentValidationIssue:
    return EnvironmentValidationIssue(
        code=code,
        stage=stage,
        path=path,
        message=message,
        details=details or {},
    )
