"""Merge a generated horizon into one simulatable batch manifest (deterministic; no simulation).

Generation ends here: for each calendar day it builds a one-day scenario, compiles it, and binds it
into a bundle against a single shared home (materialised once from a probe scenario covering every
intent). It writes the per-day bundles and one ``batch-manifest.json`` referencing them.
The researcher reviews the result and, only if satisfied, runs ``simulate-batch`` on the manifest —
simulation (M5) and sensor projection (M6) are a separate, user-triggered step.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from smart_home_sim.compiler import compile_scenario
from smart_home_sim.domain.base import ContractModel
from smart_home_sim.domain.batch import SimulationBatchManifest, SimulationBatchRun
from smart_home_sim.domain.behavior import PersonalProcessPackage
from smart_home_sim.environment import build_bundle_files
from smart_home_sim.hybrid_planning.cadence import CadenceCalendar
from smart_home_sim.hybrid_planning.day_generation import build_day_scenario
from smart_home_sim.hybrid_planning.package_authoring import build_probe_scenario
from smart_home_sim.hybrid_planning.world import PlanningWorld
from smart_home_sim.materialization import generate_home


class HorizonError(ValueError):
    """The horizon could not be merged into a simulatable manifest."""


@dataclass(frozen=True)
class HorizonResult:
    manifest_path: Path
    day_count: int
    failed_days: list[str] = field(default_factory=list)


def _write(path: Path, model: ContractModel) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(model.model_dump_json(by_alias=True, indent=2) + "\n", encoding="utf-8")


def build_horizon(
    world: PlanningWorld,
    package: PersonalProcessPackage,
    calendar: CadenceCalendar,
    output_dir: Path,
    *,
    start_index: int = 0,
    days: int | None = None,
) -> HorizonResult:
    """Compile and bundle each calendar day, then write one batch manifest over them."""
    limit = len(calendar.days) if days is None else start_index + days
    day_slice = calendar.days[start_index:limit]
    if not day_slice:
        raise HorizonError("requested calendar slice is empty")

    package_path = output_dir / "package.json"
    home_path = output_dir / "home.json"
    _write(package_path, package)

    home_result = generate_home(build_probe_scenario(world), package)
    if home_result.home is None:
        raise HorizonError("shared home generation failed")
    _write(home_path, home_result.home)

    runs: list[SimulationBatchRun] = []
    failed: list[str] = []
    for day in day_slice:
        scenario = build_day_scenario(world, day)
        scenario_path = output_dir / "scenarios" / f"day-{day.date}.scenario.json"
        _write(scenario_path, scenario)

        compilation = compile_scenario(scenario)
        if compilation.plan is None:
            failed.append(day.date)
            continue
        plan_path = output_dir / "plans" / f"day-{day.date}.plan.json"
        _write(plan_path, compilation.plan)

        bundle_result = build_bundle_files(scenario_path, plan_path, package_path, home_path)
        if bundle_result.bundle is None:
            failed.append(day.date)
            continue
        relative = f"bundles/day-{day.date}.bundle.json"
        _write(output_dir / relative, bundle_result.bundle)
        runs.append(
            SimulationBatchRun(run_id=f"day-{day.date}", bundle_path=relative, seed=calendar.seed)
        )

    if not runs:
        raise HorizonError("no simulatable days were produced")

    manifest = SimulationBatchManifest(experiment_id=f"{world.persona_id}_horizon", runs=runs)
    manifest_path = output_dir / "batch-manifest.json"
    _write(manifest_path, manifest)
    return HorizonResult(
        manifest_path=manifest_path, day_count=len(runs), failed_days=failed
    )
