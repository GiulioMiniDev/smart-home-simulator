from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer

from smart_home_sim.domain.models import Scenario
from smart_home_sim.domain.report import ValidationReport
from smart_home_sim.formatting import format_text_report
from smart_home_sim.validation.service import validate_file


class OutputFormat(StrEnum):
    text = "text"
    json = "json"


class SchemaContract(StrEnum):
    scenario = "scenario"
    validation_report = "validation-report"


app = typer.Typer(no_args_is_help=True, help="Smart-home scenario validation")


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
def schema(
    contract: Annotated[SchemaContract, typer.Option("--contract")] = SchemaContract.scenario,
    output: Annotated[Path | None, typer.Option("--output")] = None,
) -> None:
    """Print or write a public version 1.0.0 JSON Schema."""
    model = Scenario if contract is SchemaContract.scenario else ValidationReport
    content = json.dumps(model.model_json_schema(by_alias=True), indent=2)
    if output is None:
        typer.echo(content)
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(content + "\n", encoding="utf-8")
        typer.echo(f"Schema written to: {output.resolve()}")


if __name__ == "__main__":
    app()
