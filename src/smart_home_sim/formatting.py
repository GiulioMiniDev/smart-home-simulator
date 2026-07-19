from __future__ import annotations

from smart_home_sim.domain.report import ValidationReport


def format_text_report(report: ValidationReport) -> str:
    status = "VALID" if report.valid else "INVALID"
    identity = report.scenario_id or "unknown scenario"
    lines = [
        f"{status}: {identity}",
        f"Errors: {report.summary.error_count}; warnings: {report.summary.warning_count}",
    ]
    for item in report.issues:
        lines.append(
            f"[{item.severity.upper()}] {item.code} ({item.level}) {item.path}: {item.message}"
        )
    return "\n".join(lines)
