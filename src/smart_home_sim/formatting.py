from __future__ import annotations

from smart_home_sim.domain.authoring import AuthoringIngestionReport
from smart_home_sim.domain.behavior_report import BehaviorValidationReport
from smart_home_sim.domain.environment import EnvironmentValidationReport
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


def format_behavior_text_report(report: BehaviorValidationReport) -> str:
    status = "VALID" if report.valid else "INVALID"
    identity = report.package_id or "unknown behavior package"
    lines = [
        f"{status}: {identity}",
        f"Models: {report.summary.process_model_count}; bindings: {report.summary.binding_count}; "
        f"covered activities: {report.summary.covered_activity_count}",
        f"Errors: {report.summary.error_count}; warnings: {report.summary.warning_count}",
    ]
    for item in report.issues:
        lines.append(
            f"[{item.severity.upper()}] {item.code} ({item.stage}) {item.path}: {item.message}"
        )
    return "\n".join(lines)


def format_authoring_text_report(report: AuthoringIngestionReport) -> str:
    status = "VALID" if report.valid else "INVALID"
    identity = report.scenario_id or "unknown-scenario"
    lines = [f"{status}: authoring bundle for {identity}"]
    for item in report.issues:
        lines.append(
            f"[{item.severity.upper()}] {item.stage}/{item.code} {item.path}: {item.message}"
        )
    if report.valid:
        for artifact in report.artifacts:
            lines.append(f"ARTIFACT: {artifact.filename} sha256={artifact.sha256}")
    lines.append(
        f"Summary: {report.summary.error_count} error(s), {report.summary.warning_count} warning(s)"
    )
    return "\n".join(lines)


def format_environment_text_report(report: EnvironmentValidationReport) -> str:
    status = "VALID" if report.valid else "INVALID"
    identity = report.home_id or "unknown home"
    summary = report.summary
    lines = [
        f"{status}: {identity}",
        f"Regions: {summary.region_count}; connections: {summary.connection_count}; "
        f"entities: {summary.entity_count}; action bindings: {summary.action_binding_count}; "
        f"route checks: {summary.route_check_count}",
        f"Errors: {summary.error_count}; warnings: {summary.warning_count}",
    ]
    for item in report.issues:
        lines.append(
            f"[{item.severity.upper()}] {item.code} ({item.stage}) {item.path}: {item.message}"
        )
    return "\n".join(lines)
