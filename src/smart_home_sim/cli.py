from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer

from smart_home_sim.authoring import ingest_authoring_file, prepare_authoring_repair_file
from smart_home_sim.behavior import validate_behavior_files
from smart_home_sim.compiler import compile_file
from smart_home_sim.domain.authoring import (
    AuthoringIngestionReport,
    AuthoringRepairRequest,
    SimulationAuthoringBundle,
)
from smart_home_sim.domain.behavior import (
    ActionCatalog,
    ActivityCatalog,
    PersonalProcessPackage,
    VariableCatalog,
)
from smart_home_sim.domain.behavior_report import BehaviorValidationReport
from smart_home_sim.domain.compilation import CompilationReport
from smart_home_sim.domain.environment import (
    EnvironmentValidationReport,
    HomeModel,
    SimulationBundle,
)
from smart_home_sim.domain.models import Scenario
from smart_home_sim.domain.plan import CanonicalPlan
from smart_home_sim.domain.report import ValidationReport
from smart_home_sim.environment import build_bundle_files, validate_home_file
from smart_home_sim.formatting import (
    format_authoring_text_report,
    format_behavior_text_report,
    format_environment_text_report,
    format_text_report,
)
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
    simulation_authoring_bundle = "simulation-authoring-bundle"
    authoring_ingestion_report = "authoring-ingestion-report"
    authoring_repair_request = "authoring-repair-request"
    home_model = "home-model"
    environment_validation_report = "environment-validation-report"
    simulation_bundle = "simulation-bundle"


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


@app.command("validate-home")
def validate_home(
    home_path: Path,
    output_format: Annotated[OutputFormat, typer.Option("--format")] = OutputFormat.text,
    output: Annotated[Path | None, typer.Option("--output")] = None,
) -> None:
    """Validate executable topology, geometry, objects, and capabilities of one home."""
    report = validate_home_file(home_path)
    content = (
        report.model_dump_json(by_alias=True, indent=2)
        if output_format is OutputFormat.json
        else format_environment_text_report(report)
    )
    if output is None:
        typer.echo(content)
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(content + "\n", encoding="utf-8")
        typer.echo(f"Environment validation report written to: {output.resolve()}")
    if not report.valid:
        raise typer.Exit(code=1)


@app.command("build-simulation-bundle")
def build_simulation_bundle(
    scenario_path: Path,
    plan_path: Path,
    package_path: Path,
    home_path: Path,
    output: Annotated[Path, typer.Option("--output", "-o")],
    report_output: Annotated[Path | None, typer.Option("--report-output")] = None,
) -> None:
    """Bind all accepted M1-M4 artifacts into one fully resolved simulation bundle."""
    input_paths = {path.resolve() for path in (scenario_path, plan_path, package_path, home_path)}
    if output.resolve() in input_paths:
        raise typer.BadParameter(
            "Bundle output must not overwrite an input.", param_hint="--output"
        )
    if report_output is not None and (
        report_output.resolve() in input_paths or report_output.resolve() == output.resolve()
    ):
        raise typer.BadParameter(
            "Report output must differ from all inputs and the bundle output.",
            param_hint="--report-output",
        )
    result = build_bundle_files(scenario_path, plan_path, package_path, home_path)
    if report_output is not None:
        report_output.parent.mkdir(parents=True, exist_ok=True)
        report_output.write_text(
            result.report.model_dump_json(by_alias=True, indent=2) + "\n", encoding="utf-8"
        )
    if result.bundle is None:
        if report_output is None:
            typer.echo(format_environment_text_report(result.report))
        raise typer.Exit(code=1)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        result.bundle.model_dump_json(by_alias=True, indent=2) + "\n", encoding="utf-8"
    )
    typer.echo(f"Simulation bundle written to: {output.resolve()}")


@app.command("ingest-authoring-output")
def ingest_authoring_output(
    bundle_path: Path,
    output_dir: Annotated[Path, typer.Option("--output-dir")],
    output_format: Annotated[OutputFormat, typer.Option("--format")] = OutputFormat.text,
    report_output: Annotated[Path | None, typer.Option("--report-output")] = None,
    repair_request_output: Annotated[Path | None, typer.Option("--repair-request-output")] = None,
    repair_attempt: Annotated[int, typer.Option("--repair-attempt", min=1)] = 1,
) -> None:
    """Validate an LLM bundle, publishing inputs or an optional repair request."""
    if report_output is not None and report_output.resolve() == bundle_path.resolve():
        raise typer.BadParameter(
            "Report output must not overwrite the authoring bundle.",
            param_hint="--report-output",
        )
    if repair_request_output is not None:
        if repair_request_output.resolve() == bundle_path.resolve():
            raise typer.BadParameter(
                "Repair request output must not overwrite the rejected bundle.",
                param_hint="--repair-request-output",
            )
        if report_output is not None and repair_request_output.resolve() == report_output.resolve():
            raise typer.BadParameter(
                "Repair request and report outputs must be different files.",
                param_hint="--repair-request-output",
            )
    report = ingest_authoring_file(bundle_path, output_dir)
    content = (
        report.model_dump_json(by_alias=True, indent=2)
        if output_format is OutputFormat.json
        else format_authoring_text_report(report)
    )
    if report_output is None:
        typer.echo(content)
    else:
        report_output.parent.mkdir(parents=True, exist_ok=True)
        report_output.write_text(content + "\n", encoding="utf-8")
        typer.echo(f"Authoring ingestion report written to: {report_output.resolve()}")
    if report.valid:
        typer.echo(f"Canonical authoring inputs written to: {output_dir.resolve()}")
    else:
        if repair_request_output is not None:
            preparation = prepare_authoring_repair_file(bundle_path, attempt=repair_attempt)
            if preparation.request is None:
                typer.echo(
                    f"Repair request unavailable: {preparation.unavailable_reason}",
                    err=True,
                )
            else:
                repair_request_output.parent.mkdir(parents=True, exist_ok=True)
                repair_request_output.write_text(
                    preparation.request.model_dump_json(by_alias=True, indent=2) + "\n",
                    encoding="utf-8",
                )
                typer.echo(
                    f"Authoring repair request written to: {repair_request_output.resolve()}",
                    err=True,
                )
        raise typer.Exit(code=1)


@app.command("prepare-authoring-repair")
def prepare_authoring_repair(
    bundle_path: Path,
    output: Annotated[Path, typer.Option("--output", "-o")],
    attempt: Annotated[int, typer.Option("--attempt", min=1)] = 1,
) -> None:
    """Create a self-contained external-LLM request for one rejected bundle."""
    if output.resolve() == bundle_path.resolve():
        raise typer.BadParameter(
            "Repair request output must not overwrite the rejected bundle.",
            param_hint="--output",
        )
    preparation = prepare_authoring_repair_file(bundle_path, attempt=attempt)
    if preparation.request is None:
        typer.echo(format_authoring_text_report(preparation.report))
        typer.echo(f"Repair request unavailable: {preparation.unavailable_reason}", err=True)
        raise typer.Exit(code=1)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        preparation.request.model_dump_json(by_alias=True, indent=2) + "\n",
        encoding="utf-8",
    )
    typer.echo(f"Authoring repair request written to: {output.resolve()}")


@app.command()
def schema(
    contract: Annotated[SchemaContract, typer.Option("--contract")] = SchemaContract.scenario,
    output: Annotated[Path | None, typer.Option("--output")] = None,
) -> None:
    """Print or write one public versioned JSON Schema."""
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
        SchemaContract.simulation_authoring_bundle: SimulationAuthoringBundle,
        SchemaContract.authoring_ingestion_report: AuthoringIngestionReport,
        SchemaContract.authoring_repair_request: AuthoringRepairRequest,
        SchemaContract.home_model: HomeModel,
        SchemaContract.environment_validation_report: EnvironmentValidationReport,
        SchemaContract.simulation_bundle: SimulationBundle,
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
