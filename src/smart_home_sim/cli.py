from __future__ import annotations

import json
import os
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Annotated
from uuid import uuid4

import typer

from smart_home_sim.authoring import ingest_authoring_file, prepare_authoring_repair_file
from smart_home_sim.behavior import validate_behavior_files
from smart_home_sim.compiler import compile_file
from smart_home_sim.domain.application import (
    ExportManifest,
    JobRecord,
    ReplayVerification,
    WorkspaceManifest,
)
from smart_home_sim.domain.authoring import (
    AuthoringIngestionReport,
    AuthoringRepairRequest,
    SimulationAuthoringBundle,
)
from smart_home_sim.domain.batch import SimulationBatchManifest, SimulationBatchReport
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
from smart_home_sim.domain.execution import ExecutionTrace, ReplayReport, SimulationReport
from smart_home_sim.domain.materialization import (
    HomeGenerationPolicy,
    HomeGenerationReport,
    SensorDeploymentPolicy,
    SensorDeploymentReport,
    SyntheticWorkspaceManifest,
)
from smart_home_sim.domain.models import Scenario
from smart_home_sim.domain.plan import CanonicalPlan
from smart_home_sim.domain.report import ValidationReport
from smart_home_sim.domain.sensors import (
    ObservableSensorLog,
    OracleMapping,
    SensorModel,
    SensorProjectionIssue,
    SensorProjectionReport,
)
from smart_home_sim.environment import build_bundle_files, validate_home_file
from smart_home_sim.formatting import (
    format_authoring_text_report,
    format_behavior_text_report,
    format_environment_text_report,
    format_text_report,
)
from smart_home_sim.hybrid_planning import (
    BehavioralProfile,
    CadenceError,
    HabitsGenerationError,
    HorizonError,
    LMStudioClient,
    LMStudioConfig,
    LMStudioError,
    PackageAuthoringError,
    Persona,
    PersonaGenerationError,
    PlanningWorld,
    author_process_package,
    build_cadence_calendar,
    build_day_scenarios,
    build_horizon,
    build_planning_world,
    generate_habits,
    generate_llm_day_plans,
    generate_persona,
    run_generation,
)
from smart_home_sim.hybrid_planning.cadence import CadenceCalendar
from smart_home_sim.hybrid_planning.lmstudio import DEFAULT_BASE_URL, DEFAULT_MODEL
from smart_home_sim.materialization import deploy_sensors, generate_home, materialize_workspace
from smart_home_sim.materialization.service import (
    load_home_policy,
    load_sensor_policy,
    load_source_models,
)
from smart_home_sim.sensors import project_sensor_files
from smart_home_sim.simulation import (
    BatchLockedError,
    BatchManifestError,
    replay_files,
    run_batch_file,
    simulate_file,
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
    execution_trace = "execution-trace"
    simulation_report = "simulation-report"
    replay_report = "replay-report"
    simulation_batch_manifest = "simulation-batch-manifest"
    simulation_batch_report = "simulation-batch-report"
    sensor_model = "sensor-model"
    observable_sensor_log = "observable-sensor-log"
    oracle_mapping = "oracle-mapping"
    sensor_projection_report = "sensor-projection-report"
    home_generation_policy = "home-generation-policy"
    home_generation_report = "home-generation-report"
    sensor_deployment_policy = "sensor-deployment-policy"
    sensor_deployment_report = "sensor-deployment-report"
    synthetic_workspace_manifest = "synthetic-workspace-manifest"
    application_workspace_manifest = "application-workspace-manifest"
    application_job = "application-job"
    application_export_manifest = "application-export-manifest"
    application_replay = "application-replay"


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
        output.write_text(content + "\n", encoding="utf-8", newline="\n")
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
            newline="\n",
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
        output.write_text(content + "\n", encoding="utf-8", newline="\n")
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
        output.write_text(content + "\n", encoding="utf-8", newline="\n")
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
        output.write_text(content + "\n", encoding="utf-8", newline="\n")
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
            result.report.model_dump_json(by_alias=True, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    if result.bundle is None:
        if report_output is None:
            typer.echo(format_environment_text_report(result.report))
        raise typer.Exit(code=1)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        result.bundle.model_dump_json(by_alias=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    typer.echo(f"Simulation bundle written to: {output.resolve()}")


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        temporary.write_text(content + "\n", encoding="utf-8", newline="\n")
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _atomic_write_many(outputs: dict[Path, str]) -> None:
    temporary_paths: dict[Path, Path] = {}
    try:
        for path, content in outputs.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
            temporary.write_text(content + "\n", encoding="utf-8", newline="\n")
            temporary_paths[path] = temporary
        for path, temporary in temporary_paths.items():
            temporary.replace(path)
    finally:
        for temporary in temporary_paths.values():
            if temporary.exists():
                temporary.unlink()


@app.command()
def simulate(
    bundle_path: Path,
    output: Annotated[Path, typer.Option("--output", "-o")],
    report_output: Annotated[Path | None, typer.Option("--report-output")] = None,
) -> None:
    """Execute one M4 bundle into an authoritative M5 trace."""
    paths = [bundle_path.resolve(), output.resolve()]
    if len(set(paths)) != len(paths):
        raise typer.BadParameter(
            "Trace output must not overwrite the bundle.", param_hint="--output"
        )
    if report_output is not None and report_output.resolve() in set(paths):
        raise typer.BadParameter(
            "Report output must differ from the bundle and trace output.",
            param_hint="--report-output",
        )
    result = simulate_file(bundle_path)
    if report_output is not None:
        _atomic_write(report_output, result.report.model_dump_json(by_alias=True, indent=2))
    if result.trace is None:
        if report_output is None:
            typer.echo(result.report.model_dump_json(by_alias=True, indent=2))
        raise typer.Exit(code=1)
    _atomic_write(output, result.trace.model_dump_json(by_alias=True, indent=2))
    typer.echo(f"Execution trace written to: {output.resolve()}")


@app.command()
def replay(
    bundle_path: Path,
    trace_path: Path,
    output: Annotated[Path | None, typer.Option("--output", "-o")] = None,
) -> None:
    """Re-execute a bundle and compare its semantic digest with a trace."""
    report = replay_files(bundle_path, trace_path)
    content = report.model_dump_json(by_alias=True, indent=2)
    if output is None:
        typer.echo(content)
    else:
        if output.resolve() in {bundle_path.resolve(), trace_path.resolve()}:
            raise typer.BadParameter(
                "Replay output must not overwrite an input.", param_hint="--output"
            )
        _atomic_write(output, content)
        typer.echo(f"Replay report written to: {output.resolve()}")
    if not report.matches:
        raise typer.Exit(code=1)


@app.command("project-sensors")
def project_sensors_command(
    trace_path: Path,
    sensor_model_path: Path,
    bundle_path: Annotated[Path, typer.Option("--bundle")],
    output: Annotated[Path, typer.Option("--output", "-o")],
    oracle_output: Annotated[Path, typer.Option("--oracle-output")],
    report_output: Annotated[Path, typer.Option("--report-output")],
) -> None:
    """Project an M5 trace into a public sensor log and separate oracle mapping."""
    inputs = {trace_path.resolve(), bundle_path.resolve(), sensor_model_path.resolve()}
    outputs = {output.resolve(), oracle_output.resolve(), report_output.resolve()}
    if len(outputs) != 3 or inputs & outputs:
        raise typer.BadParameter(
            "Sensor outputs must be distinct and must not overwrite either input."
        )
    result = project_sensor_files(trace_path, bundle_path, sensor_model_path)
    if result.observable_log is None or result.oracle_mapping is None:
        _atomic_write(report_output, result.report.model_dump_json(by_alias=True, indent=2))
        typer.echo(result.report.model_dump_json(by_alias=True, indent=2), err=True)
        raise typer.Exit(code=1)
    try:
        _atomic_write_many(
            {
                output: result.observable_log.model_dump_json(by_alias=True, indent=2),
                oracle_output: result.oracle_mapping.model_dump_json(by_alias=True, indent=2),
                report_output: result.report.model_dump_json(by_alias=True, indent=2),
            }
        )
    except OSError as error:
        issue = SensorProjectionIssue(
            code="OUTPUT_WRITE_ERROR",
            stage="output",
            path="$",
            message=f"Cannot publish sensor projection artifacts: {error}",
        )
        failed_summary = result.report.summary.model_copy(update={"error_count": 1})
        failed_report = SensorProjectionReport.model_validate(
            result.report.model_copy(
                update={
                    "success": False,
                    "observable_log_sha256": None,
                    "oracle_mapping_sha256": None,
                    "issues": [issue],
                    "summary": failed_summary,
                }
            ).model_dump()
        )
        try:
            _atomic_write(report_output, failed_report.model_dump_json(by_alias=True, indent=2))
        except OSError:
            typer.echo(failed_report.model_dump_json(by_alias=True, indent=2), err=True)
        raise typer.Exit(code=1) from error
    typer.echo(f"Observable sensor log written to: {output.resolve()}")
    typer.echo(f"Oracle mapping written to: {oracle_output.resolve()}")


@app.command("generate-home")
def generate_home_command(
    scenario_path: Path,
    package_path: Path,
    output: Annotated[Path, typer.Option("--output", "-o")],
    report_output: Annotated[Path, typer.Option("--report-output")],
    policy_path: Annotated[Path | None, typer.Option("--policy")] = None,
) -> None:
    """Generate a deterministic executable home from accepted M3 artifacts."""
    inputs = {scenario_path.resolve(), package_path.resolve()}
    if policy_path is not None:
        inputs.add(policy_path.resolve())
    outputs = {output.resolve(), report_output.resolve()}
    if len(outputs) != 2 or inputs & outputs:
        raise typer.BadParameter("Home outputs must be distinct and must not overwrite inputs.")
    behavior_report = validate_behavior_files(package_path, scenario_path)
    if not behavior_report.valid:
        typer.echo(behavior_report.model_dump_json(by_alias=True, indent=2), err=True)
        raise typer.Exit(code=1)
    try:
        scenario, package = load_source_models(scenario_path, package_path)
        result = generate_home(scenario, package, load_home_policy(policy_path))
    except (OSError, UnicodeDecodeError, ValueError) as error:
        typer.echo(f"Cannot generate home: {error}", err=True)
        raise typer.Exit(code=2) from error
    _atomic_write(report_output, result.report.model_dump_json(by_alias=True, indent=2))
    if result.home is None:
        typer.echo(result.report.model_dump_json(by_alias=True, indent=2), err=True)
        raise typer.Exit(code=1)
    _atomic_write(output, result.home.model_dump_json(by_alias=True, indent=2))
    typer.echo(f"Generated home written to: {output.resolve()}")


@app.command("deploy-sensors")
def deploy_sensors_command(
    bundle_path: Path,
    output: Annotated[Path, typer.Option("--output", "-o")],
    report_output: Annotated[Path, typer.Option("--report-output")],
    policy_path: Annotated[Path | None, typer.Option("--policy")] = None,
) -> None:
    """Derive a deterministic sensor deployment from one resolved M4 bundle."""
    inputs = {bundle_path.resolve()}
    if policy_path is not None:
        inputs.add(policy_path.resolve())
    outputs = {output.resolve(), report_output.resolve()}
    if len(outputs) != 2 or inputs & outputs:
        raise typer.BadParameter("Sensor outputs must be distinct and must not overwrite inputs.")
    try:
        bundle = SimulationBundle.model_validate_json(bundle_path.read_text(encoding="utf-8"))
        result = deploy_sensors(bundle, load_sensor_policy(policy_path))
    except (OSError, UnicodeDecodeError, ValueError) as error:
        typer.echo(f"Cannot deploy sensors: {error}", err=True)
        raise typer.Exit(code=2) from error
    _atomic_write(report_output, result.report.model_dump_json(by_alias=True, indent=2))
    if result.sensor_model is None:
        typer.echo(result.report.model_dump_json(by_alias=True, indent=2), err=True)
        raise typer.Exit(code=1)
    _atomic_write(output, result.sensor_model.model_dump_json(by_alias=True, indent=2))
    typer.echo(f"Generated sensor model written to: {output.resolve()}")


@app.command("run-synthetic")
def run_synthetic_command(
    scenario_path: Path,
    package_path: Path,
    output_directory: Annotated[Path, typer.Option("--output-dir", "-o")],
    home_policy_path: Annotated[Path | None, typer.Option("--home-policy")] = None,
    sensor_policy_path: Annotated[Path | None, typer.Option("--sensor-policy")] = None,
) -> None:
    """Run the transactional scenario-first M3-to-M6 workflow."""
    try:
        manifest = materialize_workspace(
            scenario_path,
            package_path,
            output_directory,
            home_policy=load_home_policy(home_policy_path),
            sensor_policy=load_sensor_policy(sensor_policy_path),
        )
    except FileExistsError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=2) from error
    except (OSError, UnicodeDecodeError, ValueError, RuntimeError) as error:
        typer.echo(f"Synthetic workflow failed transactionally: {error}", err=True)
        raise typer.Exit(code=1) from error
    typer.echo(
        f"Synthetic workspace written to: {output_directory.resolve()} "
        f"({len(manifest.artifacts)} verified artifacts)"
    )


@app.command("simulate-batch")
def simulate_batch(
    manifest_path: Path,
    output_directory: Annotated[Path, typer.Option("--output-dir", "-o")],
    workers: Annotated[int, typer.Option("--workers", "-j", min=1)] = max(
        1, min(4, (os.cpu_count() or 2) - 1)
    ),
    resume: Annotated[bool, typer.Option("--resume/--no-resume")] = True,
) -> None:
    """Execute independent simulation runs in an isolated process pool."""
    try:
        report = run_batch_file(
            manifest_path,
            output_directory=output_directory,
            workers=workers,
            resume=resume,
        )
    except BatchManifestError as error:
        typer.echo(
            json.dumps(
                {
                    "success": False,
                    "issues": [item.model_dump(by_alias=True) for item in error.issues],
                },
                indent=2,
            ),
            err=True,
        )
        raise typer.Exit(code=2) from error
    except BatchLockedError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=2) from error
    typer.echo(f"Batch report written to: {(output_directory / 'batch-report.json').resolve()}")
    if not report.success:
        raise typer.Exit(code=1)


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
        report_output.write_text(content + "\n", encoding="utf-8", newline="\n")
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
                    newline="\n",
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
        newline="\n",
    )
    typer.echo(f"Authoring repair request written to: {output.resolve()}")


@app.command("generate-persona")
def generate_persona_command(
    brief: str,
    output: Annotated[Path, typer.Option("--output", "-o")],
    model: Annotated[str, typer.Option("--model")] = DEFAULT_MODEL,
    base_url: Annotated[str, typer.Option("--base-url")] = DEFAULT_BASE_URL,
    temperature: Annotated[float, typer.Option("--temperature")] = 0.3,
    timezone: Annotated[str, typer.Option("--timezone")] = "Europe/Rome",
    seed: Annotated[int | None, typer.Option("--seed")] = None,
    exchange_output: Annotated[Path | None, typer.Option("--exchange-output")] = None,
) -> None:
    """Invent one frozen resident persona locally through LM Studio."""
    if exchange_output is not None and exchange_output.resolve() == output.resolve():
        raise typer.BadParameter(
            "Exchange output must differ from the persona output.",
            param_hint="--exchange-output",
        )
    client = LMStudioClient(
        LMStudioConfig(base_url=base_url, model=model, temperature=temperature, seed=seed)
    )
    try:
        result = generate_persona(brief, client, timezone=timezone, seed=seed)
    except LMStudioError as error:
        typer.echo(f"LM Studio generation failed: {error}", err=True)
        raise typer.Exit(code=2) from error
    except PersonaGenerationError as error:
        typer.echo(f"Persona generation failed: {error}", err=True)
        raise typer.Exit(code=1) from error
    _atomic_write(output, result.persona.model_dump_json(by_alias=True, indent=2))
    typer.echo(f"Persona written to: {output.resolve()}")
    if exchange_output is not None:
        exchange = {
            "request": result.completion.request,
            "response": result.completion.response,
            "content": result.completion.content,
            "durationSeconds": result.completion.duration_seconds,
            "finishReason": result.completion.finish_reason,
            "usage": result.completion.usage,
        }
        _atomic_write(exchange_output, json.dumps(exchange, ensure_ascii=False, indent=2))
        typer.echo(f"Generation exchange written to: {exchange_output.resolve()}")


@app.command("generate-habits")
def generate_habits_command(
    persona_path: Path,
    output: Annotated[Path, typer.Option("--output", "-o")],
    model: Annotated[str, typer.Option("--model")] = DEFAULT_MODEL,
    base_url: Annotated[str, typer.Option("--base-url")] = DEFAULT_BASE_URL,
    temperature: Annotated[float, typer.Option("--temperature")] = 0.3,
    seed: Annotated[int | None, typer.Option("--seed")] = None,
    max_repairs: Annotated[int, typer.Option("--max-repairs", min=0)] = 2,
    exchange_output: Annotated[Path | None, typer.Option("--exchange-output")] = None,
) -> None:
    """Generate a frozen behavioural profile (habit ground truth) from a persona via LM Studio."""
    outputs = {output.resolve()}
    if exchange_output is not None:
        if exchange_output.resolve() in {output.resolve(), persona_path.resolve()}:
            raise typer.BadParameter(
                "Exchange output must differ from the persona and profile outputs.",
                param_hint="--exchange-output",
            )
        outputs.add(exchange_output.resolve())
    if persona_path.resolve() in outputs:
        raise typer.BadParameter(
            "Profile output must not overwrite the persona input.", param_hint="--output"
        )
    try:
        persona = Persona.model_validate_json(persona_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as error:
        typer.echo(f"Cannot load persona: {error}", err=True)
        raise typer.Exit(code=2) from error

    client = LMStudioClient(
        LMStudioConfig(base_url=base_url, model=model, temperature=temperature, seed=seed)
    )
    try:
        result = generate_habits(persona, client, max_repairs=max_repairs, seed=seed)
    except LMStudioError as error:
        typer.echo(f"LM Studio generation failed: {error}", err=True)
        raise typer.Exit(code=2) from error
    except HabitsGenerationError as error:
        typer.echo(f"Habit generation failed: {error}", err=True)
        raise typer.Exit(code=1) from error

    _atomic_write(output, result.profile.model_dump_json(by_alias=True, indent=2))
    typer.echo(
        f"Behavioural profile written to: {output.resolve()} "
        f"({len(result.profile.habits)} habits, {result.repair_attempts} repair attempt(s))"
    )
    if exchange_output is not None:
        exchange = {
            "request": result.completion.request,
            "response": result.completion.response,
            "content": result.completion.content,
            "durationSeconds": result.completion.duration_seconds,
            "finishReason": result.completion.finish_reason,
            "usage": result.completion.usage,
        }
        _atomic_write(exchange_output, json.dumps(exchange, ensure_ascii=False, indent=2))
        typer.echo(f"Generation exchange written to: {exchange_output.resolve()}")


@app.command("build-planning-world")
def build_planning_world_command(
    persona_path: Path,
    output: Annotated[Path, typer.Option("--output", "-o")],
    seed: Annotated[int, typer.Option("--seed")] = 1,
    activity_catalog_version: Annotated[str, typer.Option("--activity-catalog-version")] = "1.0.0",
    home_model_version: Annotated[str, typer.Option("--home-model-version")] = "1.0.0",
) -> None:
    """Deterministically build a persona's standard-apartment planning world (no LLM)."""
    if persona_path.resolve() == output.resolve():
        raise typer.BadParameter(
            "World output must not overwrite the persona input.", param_hint="--output"
        )
    try:
        persona = Persona.model_validate_json(persona_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as error:
        typer.echo(f"Cannot load persona: {error}", err=True)
        raise typer.Exit(code=2) from error
    world = build_planning_world(
        persona,
        seed=seed,
        activity_catalog_version=activity_catalog_version,
        home_model_version=home_model_version,
    )
    _atomic_write(output, world.model_dump_json(by_alias=True, indent=2))
    typer.echo(
        f"Planning world written to: {output.resolve()} "
        f"({len(world.locations)} locations, {len(world.resources)} resources)"
    )


@app.command("author-process-package")
def author_process_package_command(
    persona_path: Path,
    world_path: Path,
    output: Annotated[Path, typer.Option("--output", "-o")],
    use_llm: Annotated[bool, typer.Option("--use-llm/--no-use-llm")] = False,
    model: Annotated[str, typer.Option("--model")] = DEFAULT_MODEL,
    base_url: Annotated[str, typer.Option("--base-url")] = DEFAULT_BASE_URL,
    temperature: Annotated[float, typer.Option("--temperature")] = 0.3,
    seed: Annotated[int | None, typer.Option("--seed")] = None,
    max_repairs: Annotated[int, typer.Option("--max-repairs", min=0)] = 1,
) -> None:
    """Author and gate a persona's personal process package from its planning world.

    Deterministic by default (retargets reference models); pass --use-llm to author each model
    with LM Studio, keeping a proposal only when it still passes the gate.
    """
    inputs = {persona_path.resolve(), world_path.resolve()}
    if output.resolve() in inputs:
        raise typer.BadParameter(
            "Package output must not overwrite an input.", param_hint="--output"
        )
    try:
        persona = Persona.model_validate_json(persona_path.read_text(encoding="utf-8"))
        world = PlanningWorld.model_validate_json(world_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as error:
        typer.echo(f"Cannot load inputs: {error}", err=True)
        raise typer.Exit(code=2) from error
    client = (
        LMStudioClient(
            LMStudioConfig(base_url=base_url, model=model, temperature=temperature, seed=seed)
        )
        if use_llm
        else None
    )
    try:
        result = author_process_package(
            persona, world, client=client, seed=seed, max_repairs=max_repairs
        )
    except LMStudioError as error:
        typer.echo(f"LM Studio authoring failed: {error}", err=True)
        raise typer.Exit(code=2) from error
    except PackageAuthoringError as error:
        typer.echo(f"Package authoring failed: {error}", err=True)
        raise typer.Exit(code=1) from error
    _atomic_write(output, result.package.model_dump_json(by_alias=True, indent=2))
    typer.echo(
        f"Personal process package written to: {output.resolve()} "
        f"({len(result.package.process_models)} process models, "
        f"{result.llm_authored_count} LLM-authored, {result.fallback_count} reference)"
    )


@app.command("generate-dataset")
def generate_dataset_command(
    brief: str,
    output_dir: Annotated[Path, typer.Option("--output-dir", "-o")],
    start: Annotated[str, typer.Option("--start")],
    months: Annotated[int, typer.Option("--months", min=1)] = 1,
    use_llm_days: Annotated[bool, typer.Option("--use-llm-days/--no-use-llm-days")] = False,
    use_llm_package: Annotated[
        bool, typer.Option("--use-llm-package/--no-use-llm-package")
    ] = False,
    model: Annotated[str, typer.Option("--model")] = DEFAULT_MODEL,
    base_url: Annotated[str, typer.Option("--base-url")] = DEFAULT_BASE_URL,
    temperature: Annotated[float, typer.Option("--temperature")] = 0.6,
    seed: Annotated[int | None, typer.Option("--seed")] = None,
) -> None:
    """Generate a whole horizon from one brief (persona to batch manifest; does not simulate)."""
    try:
        start_date = date.fromisoformat(start)
    except ValueError as error:
        raise typer.BadParameter(
            f"Start date must be YYYY-MM-DD: {error}", param_hint="--start"
        ) from error
    client = LMStudioClient(
        LMStudioConfig(base_url=base_url, model=model, temperature=temperature, seed=seed)
    )

    def progress(stage: str, percent: float, message: str) -> None:
        typer.echo(f"[{percent:5.1f}%] {stage}: {message}")

    try:
        result = run_generation(
            brief,
            output_dir,
            client,
            start_date=start_date,
            months=months,
            use_llm_package=use_llm_package,
            use_llm_days=use_llm_days,
            seed=seed,
            progress=progress,
        )
    except (LMStudioError, PersonaGenerationError, HabitsGenerationError, PackageAuthoringError,
            CadenceError, HorizonError) as error:
        typer.echo(f"Generation failed: {error}", err=True)
        raise typer.Exit(code=1) from error
    typer.echo(
        f"Batch manifest written to: {result.manifest_path.resolve()} "
        f"({result.day_count} days bundled)"
    )
    typer.echo(
        "Generation complete. To simulate, run: "
        f"smart-home-sim simulate-batch {result.manifest_path} --output-dir <dir>"
    )


@app.command("generate-horizon")
def generate_horizon_command(
    world_path: Path,
    package_path: Path,
    calendar_path: Path,
    output_dir: Annotated[Path, typer.Option("--output-dir", "-o")],
    start_index: Annotated[int, typer.Option("--start-index", min=0)] = 0,
    days: Annotated[int | None, typer.Option("--days", min=1)] = None,
    use_llm: Annotated[bool, typer.Option("--use-llm/--no-use-llm")] = False,
    model: Annotated[str, typer.Option("--model")] = DEFAULT_MODEL,
    base_url: Annotated[str, typer.Option("--base-url")] = DEFAULT_BASE_URL,
    temperature: Annotated[float, typer.Option("--temperature")] = 0.6,
    seed: Annotated[int | None, typer.Option("--seed")] = None,
) -> None:
    """Merge the horizon into one simulatable batch manifest (deterministic; does not simulate).

    Days are the deterministic substrate by default; pass --use-llm to arrange each week with LM
    Studio, keeping a generated day only when it still compiles (else the substrate day is used).
    """
    try:
        world = PlanningWorld.model_validate_json(world_path.read_text(encoding="utf-8"))
        package = PersonalProcessPackage.model_validate_json(
            package_path.read_text(encoding="utf-8")
        )
        calendar = CadenceCalendar.model_validate_json(calendar_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as error:
        typer.echo(f"Cannot load inputs: {error}", err=True)
        raise typer.Exit(code=2) from error
    day_plans = None
    llm_note = ""
    if use_llm:
        client = LMStudioClient(
            LMStudioConfig(base_url=base_url, model=model, temperature=temperature, seed=seed)
        )
        try:
            llm_result = generate_llm_day_plans(
                world, calendar, client, start_index=start_index, days=days, seed=seed
            )
        except LMStudioError as error:
            typer.echo(f"LM Studio day generation failed: {error}", err=True)
            raise typer.Exit(code=2) from error
        day_plans = llm_result.day_plans
        llm_note = (
            f" ({llm_result.llm_authored_count} LLM-authored, "
            f"{llm_result.fallback_count} substrate)"
        )
    try:
        result = build_horizon(
            world,
            package,
            calendar,
            output_dir,
            start_index=start_index,
            days=days,
            day_plans=day_plans,
        )
    except HorizonError as error:
        typer.echo(f"Horizon merge failed: {error}", err=True)
        raise typer.Exit(code=1) from error
    typer.echo(
        f"Batch manifest written to: {result.manifest_path.resolve()} "
        f"({result.day_count} days bundled, {len(result.failed_days)} skipped){llm_note}"
    )
    if result.trace_path is not None:
        typer.echo(f"Planned habit ground-truth written to: {result.trace_path.resolve()}")
    typer.echo(
        "Generation complete. To simulate, run: "
        f"smart-home-sim simulate-batch {result.manifest_path} --output-dir <dir>"
    )


@app.command("generate-days")
def generate_days_command(
    world_path: Path,
    calendar_path: Path,
    output_dir: Annotated[Path, typer.Option("--output-dir", "-o")],
    start_index: Annotated[int, typer.Option("--start-index", min=0)] = 0,
    days: Annotated[int | None, typer.Option("--days", min=1)] = None,
) -> None:
    """Build one simulatable one-day scenario per calendar day (deterministic substrate)."""
    try:
        world = PlanningWorld.model_validate_json(world_path.read_text(encoding="utf-8"))
        calendar = CadenceCalendar.model_validate_json(calendar_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as error:
        typer.echo(f"Cannot load inputs: {error}", err=True)
        raise typer.Exit(code=2) from error
    try:
        scenarios = build_day_scenarios(world, calendar, start_index=start_index, days=days)
    except ValueError as error:
        typer.echo(f"Cannot generate days: {error}", err=True)
        raise typer.Exit(code=1) from error
    for scenario in scenarios:
        day = scenario.days[0].date.isoformat()
        _atomic_write(
            output_dir / f"day-{day}.scenario.json",
            scenario.model_dump_json(by_alias=True, indent=2),
        )
    typer.echo(f"Wrote {len(scenarios)} day scenarios to: {output_dir.resolve()}")


@app.command("build-cadence-calendar")
def build_cadence_calendar_command(
    profile_path: Path,
    output: Annotated[Path, typer.Option("--output", "-o")],
    start: Annotated[str, typer.Option("--start")],
    months: Annotated[int, typer.Option("--months", min=1)] = 1,
    seed: Annotated[int, typer.Option("--seed")] = 0,
    timezone: Annotated[str, typer.Option("--timezone")] = "Europe/Rome",
) -> None:
    """Deterministically expand a behavioural profile into a per-day cadence calendar."""
    if profile_path.resolve() == output.resolve():
        raise typer.BadParameter(
            "Calendar output must not overwrite the profile input.", param_hint="--output"
        )
    try:
        start_date = date.fromisoformat(start)
    except ValueError as error:
        raise typer.BadParameter(
            f"Start date must be YYYY-MM-DD: {error}", param_hint="--start"
        ) from error
    try:
        profile = BehavioralProfile.model_validate_json(profile_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as error:
        typer.echo(f"Cannot load behavioural profile: {error}", err=True)
        raise typer.Exit(code=2) from error
    try:
        result = build_cadence_calendar(
            profile, start_date=start_date, months=months, seed=seed, timezone=timezone
        )
    except CadenceError as error:
        typer.echo(f"Cadence calendar failed: {error}", err=True)
        raise typer.Exit(code=1) from error
    _atomic_write(output, result.calendar.model_dump_json(by_alias=True, indent=2))
    typer.echo(
        f"Cadence calendar written to: {output.resolve()} "
        f"({len(result.calendar.days)} days, {result.total_occurrences} habit occurrences)"
    )


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
        SchemaContract.execution_trace: ExecutionTrace,
        SchemaContract.simulation_report: SimulationReport,
        SchemaContract.replay_report: ReplayReport,
        SchemaContract.simulation_batch_manifest: SimulationBatchManifest,
        SchemaContract.simulation_batch_report: SimulationBatchReport,
        SchemaContract.sensor_model: SensorModel,
        SchemaContract.observable_sensor_log: ObservableSensorLog,
        SchemaContract.oracle_mapping: OracleMapping,
        SchemaContract.sensor_projection_report: SensorProjectionReport,
        SchemaContract.home_generation_policy: HomeGenerationPolicy,
        SchemaContract.home_generation_report: HomeGenerationReport,
        SchemaContract.sensor_deployment_policy: SensorDeploymentPolicy,
        SchemaContract.sensor_deployment_report: SensorDeploymentReport,
        SchemaContract.synthetic_workspace_manifest: SyntheticWorkspaceManifest,
        SchemaContract.application_workspace_manifest: WorkspaceManifest,
        SchemaContract.application_job: JobRecord,
        SchemaContract.application_export_manifest: ExportManifest,
        SchemaContract.application_replay: ReplayVerification,
    }
    model = models[contract]
    content = json.dumps(model.model_json_schema(by_alias=True), indent=2)
    if output is None:
        typer.echo(content)
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(content + "\n", encoding="utf-8", newline="\n")
        typer.echo(f"Schema written to: {output.resolve()}")


if __name__ == "__main__":
    app()
