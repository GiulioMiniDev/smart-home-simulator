from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer

from smart_home_sim.behavior import validate_behavior_files
from smart_home_sim.compiler import compile_file
from smart_home_sim.domain.behavior import (
    ActionCatalog,
    ActivityCatalog,
    PersonalProcessPackage,
    VariableCatalog,
)
from smart_home_sim.domain.behavior_report import BehaviorValidationReport
from smart_home_sim.domain.compilation import CompilationReport
from smart_home_sim.domain.models import Scenario
from smart_home_sim.domain.plan import CanonicalPlan
from smart_home_sim.domain.report import ValidationReport
from smart_home_sim.formatting import format_behavior_text_report, format_text_report
from smart_home_sim.validation.service import validate_file


class OutputFormat(StrEnum):
    text = "text"
    json = "json"


class SchemaContract(StrEnum):
    scenario = "scenario"
    validation_report = "validation-report"
    canonical_plan = "canonical-plan"
    compilation_report = "compilation-report"
    activity_catalog = "activity-catalog"
    variable_catalog = "variable-catalog"
    action_catalog = "action-catalog"
    personal_process_package = "personal-process-package"
    behavior_validation_report = "behavior-validation-report"


app = typer.Typer(
    no_args_is_help=True,
    help="Smart-home scenario, behavior authoring, validation, and compilation",
)


@app.command()
def validate(
    scenario_path: Path,
    output_format: Annotated[OutputFormat, typer.Option("--format")] = OutputFormat.text,
    output: Annotated[Path | None, typer.Option("--output")] = None,
    warnings_as_errors: Annotated[bool, typer.Option("--warnings-as-errors")] = False,
) -> None:
    """Validate one scenario without modifying or executing it."""
    report = validate_file(scenario_path)
    if output_format is OutputFormat.json:
        content = report.model_dump_json(by_alias=True, indent=2)
    else:
        content = format_text_report(report)

    if output is None:
        typer.echo(content)
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(content + "\n", encoding="utf-8")
        typer.echo(f"Validation report written to: {output.resolve()}")

    failed = not report.valid or (warnings_as_errors and report.summary.warning_count > 0)
    if failed:
        raise typer.Exit(code=1)


@app.command()
def compile(
    scenario_path: Path,
    output: Annotated[Path | None, typer.Option("--output", "-o")] = None,
    report_output: Annotated[Path | None, typer.Option("--report-output")] = None,
) -> None:
    """Compile one valid scenario into a deterministic canonical plan."""
    result = compile_file(scenario_path)
    if report_output is not None:
        report_output.parent.mkdir(parents=True, exist_ok=True)
        report_output.write_text(
            result.report.model_dump_json(by_alias=True, indent=2) + "\n",
            encoding="utf-8",
        )

    if result.plan is None:
        if report_output is None:
            typer.echo(result.report.model_dump_json(by_alias=True, indent=2))
        raise typer.Exit(code=1)

    content = result.plan.model_dump_json(by_alias=True, indent=2)
    if output is None:
        typer.echo(content)
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(content + "\n", encoding="utf-8")
        typer.echo(f"Canonical plan written to: {output.resolve()}")


@app.command("validate-behavior")
def validate_behavior(
    package_path: Path,
    scenario_path: Path,
    output_format: Annotated[OutputFormat, typer.Option("--format")] = OutputFormat.text,
    output: Annotated[Path | None, typer.Option("--output")] = None,
    activity_catalog: Annotated[Path | None, typer.Option("--activity-catalog")] = None,
    variable_catalog: Annotated[Path | None, typer.Option("--variable-catalog")] = None,
    action_catalog: Annotated[Path | None, typer.Option("--action-catalog")] = None,
) -> None:
    """Validate personal ADL process models and their scenario compatibility."""
    report = validate_behavior_files(
        package_path,
        scenario_path,
        activity_catalog_path=activity_catalog,
        variable_catalog_path=variable_catalog,
        action_catalog_path=action_catalog,
    )
    content = (
        report.model_dump_json(by_alias=True, indent=2)
        if output_format is OutputFormat.json
        else format_behavior_text_report(report)
    )
    if output is None:
        typer.echo(content)
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(content + "\n", encoding="utf-8")
        typer.echo(f"Behavior validation report written to: {output.resolve()}")
    if not report.valid:
        raise typer.Exit(code=1)


@app.command()
def schema(
    contract: Annotated[SchemaContract, typer.Option("--contract")] = SchemaContract.scenario,
    output: Annotated[Path | None, typer.Option("--output")] = None,
) -> None:
    """Print or write a public version 1.0.0 JSON Schema."""
    models = {
        SchemaContract.scenario: Scenario,
        SchemaContract.validation_report: ValidationReport,
        SchemaContract.canonical_plan: CanonicalPlan,
        SchemaContract.compilation_report: CompilationReport,
        SchemaContract.activity_catalog: ActivityCatalog,
        SchemaContract.variable_catalog: VariableCatalog,
        SchemaContract.action_catalog: ActionCatalog,
        SchemaContract.personal_process_package: PersonalProcessPackage,
        SchemaContract.behavior_validation_report: BehaviorValidationReport,
    }
    model = models[contract]
    content = json.dumps(model.model_json_schema(by_alias=True), indent=2)
    if output is None:
        typer.echo(content)
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(content + "\n", encoding="utf-8")
        typer.echo(f"Schema written to: {output.resolve()}")


if __name__ == "__main__":
    app()
