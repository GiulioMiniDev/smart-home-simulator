from __future__ import annotations

import json
from pathlib import Path

import typer
from pydantic import ValidationError

from smart_home_sim.domain.models import Scenario
from smart_home_sim.engine.simulator import run_simulation
from smart_home_sim.exporters.jsonl import write_jsonl
from smart_home_sim.io import load_scenario
from smart_home_sim.validation.scenario import ScenarioValidationError, require_valid_scenario

app = typer.Typer(no_args_is_help=True, help="Constrained smart-home simulator")


def _load_and_validate(path: Path) -> Scenario:
    try:
        scenario = load_scenario(path)
        require_valid_scenario(scenario)
        return scenario
    except (OSError, ValidationError, ScenarioValidationError) as error:
        typer.echo(f"Invalid scenario: {error}", err=True)
        raise typer.Exit(code=1) from error


@app.command()
def validate(scenario_path: Path) -> None:
    """Validate a scenario without executing it."""
    scenario = _load_and_validate(scenario_path)
    typer.echo(
        f"Valid scenario '{scenario.scenario_id}': "
        f"{len(scenario.activities)} activities, {len(scenario.sensors)} sensors"
    )


@app.command("run")
def run_command(
    scenario_path: Path,
    output_dir: Path = Path("outputs/latest"),
) -> None:
    """Execute a scenario and write observable and oracle logs."""
    scenario = _load_and_validate(scenario_path)
    result = run_simulation(scenario)

    raw_path = output_dir / "raw_sensor_events.jsonl"
    ground_truth_path = output_dir / "ground_truth.jsonl"
    execution_path = output_dir / "activity_executions.jsonl"
    write_jsonl(raw_path, result.raw_sensor_events)
    write_jsonl(ground_truth_path, result.ground_truth)
    write_jsonl(execution_path, result.activity_executions)

    typer.echo(
        f"Simulation complete: {len(result.raw_sensor_events)} raw events, "
        f"{len(result.ground_truth)} ground-truth primitives"
    )
    typer.echo(f"Output directory: {output_dir.resolve()}")


@app.command()
def schema(output: Path | None = None) -> None:
    """Print or write the current scenario JSON Schema."""
    content = json.dumps(Scenario.model_json_schema(by_alias=True), indent=2)
    if output is None:
        typer.echo(content)
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(content + "\n", encoding="utf-8")
    typer.echo(f"Schema written to: {output.resolve()}")


if __name__ == "__main__":
    app()
