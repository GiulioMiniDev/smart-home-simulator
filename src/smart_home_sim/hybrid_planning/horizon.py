"""Merge a generated horizon into one simulatable batch manifest (deterministic; no simulation).

Generation ends here: for each calendar day it builds a one-day scenario, compiles it, and binds it
into a bundle against a single shared home (materialised once from a probe scenario covering every
intent). It writes the per-day bundles and one ``batch-manifest.json`` referencing them.
The researcher reviews the result and, only if satisfied, runs ``simulate-batch`` on the manifest —
simulation (M5) and sensor projection (M6) are a separate, user-triggered step.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from smart_home_sim.compiler import compile_scenario
from smart_home_sim.domain.base import ContractModel
from smart_home_sim.domain.batch import SimulationBatchManifest, SimulationBatchRun
from smart_home_sim.domain.behavior import PersonalProcessPackage
from smart_home_sim.domain.models import DayPlan, Scenario, SimulationWindow
from smart_home_sim.environment import build_bundle_files
from smart_home_sim.hybrid_planning.cadence import CadenceCalendar, CalendarDay
from smart_home_sim.hybrid_planning.day_generation import (
    build_day_scenario,
    build_scenario_from_day_plan,
    habit_to_intent,
)
from smart_home_sim.hybrid_planning.drives import DayRhythm, RhythmProfile, plan_rhythms
from smart_home_sim.hybrid_planning.habit_trace import build_planned_trace
from smart_home_sim.hybrid_planning.intents import IntentCategory, intent_spec
from smart_home_sim.hybrid_planning.package_authoring import build_probe_scenario
from smart_home_sim.hybrid_planning.world import PlanningWorld, assemble_scenario
from smart_home_sim.materialization import generate_home


class HorizonError(ValueError):
    """The horizon could not be merged into a simulatable manifest."""


@dataclass(frozen=True)
class HorizonResult:
    manifest_path: Path
    day_count: int
    trace_path: Path | None = None
    failed_days: list[str] = field(default_factory=list)
    scenario_path: Path | None = None


def _scheduled_drive_load(
    day_slice: list[CalendarDay],
) -> tuple[dict[date, int], dict[date, int]]:
    """Count, per day, the scheduled meals and social contacts the drives are allowed to spend.

    Hunger and the need for company are only halfway modelled if they accumulate without ever being
    consumed: they climb to their ceiling and stop varying. This reads what the calendar actually
    scheduled so the drive layer can subtract it.
    """
    meals: dict[date, int] = {}
    social: dict[date, int] = {}
    for day in day_slice:
        key = date.fromisoformat(day.date)
        meal_count = 0
        social_count = 0
        for occurrence in day.occurrences:
            intent = habit_to_intent(occurrence.label, occurrence.kind.value)
            category = intent_spec(intent).category
            if category is IntentCategory.meal:
                meal_count += 1
            elif category is IntentCategory.social:
                social_count += 1
        meals[key] = meal_count
        social[key] = social_count
    return meals, social


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
    day_plans: dict[str, DayPlan] | None = None,
    rhythm_profile: RhythmProfile | None = None,
) -> HorizonResult:
    """Compile and bundle each calendar day, then write one batch manifest over them.

    When ``day_plans`` maps a date to a DayPlan (e.g. from the LLM layer), that plan is used for the
    date; otherwise the deterministic substrate day is built.

    With ``rhythm_profile`` set, the substrate days are shaped by homeostatic drive state carried
    across the horizon instead of the fixed 06:00/22:30 scaffold, and activity durations are drawn
    per occurrence. The rhythms are computed over the whole slice in one pass because day N's
    sleep debt is what day N-1 left behind.
    """
    limit = len(calendar.days) if days is None else start_index + days
    day_slice = calendar.days[start_index:limit]
    if not day_slice:
        raise HorizonError("requested calendar slice is empty")

    rhythms: dict[str, DayRhythm] = {}
    if rhythm_profile is not None:
        meals_by_day, social_by_day = _scheduled_drive_load(day_slice)
        rhythms = plan_rhythms(
            rhythm_profile,
            [date.fromisoformat(day.date) for day in day_slice],
            seed=calendar.seed,
            meals_by_day=meals_by_day,
            social_by_day=social_by_day,
        )

    package_path = output_dir / "package.json"
    home_path = output_dir / "home.json"
    _write(package_path, package)

    home_result = generate_home(build_probe_scenario(world), package)
    if home_result.home is None:
        raise HorizonError("shared home generation failed")
    _write(home_path, home_result.home)

    runs: list[SimulationBatchRun] = []
    failed: list[str] = []
    simulatable_days: list[DayPlan] = []
    for day in day_slice:
        if day_plans is not None and day.date in day_plans:
            scenario = build_scenario_from_day_plan(world, day_plans[day.date])
        else:
            scenario = build_day_scenario(
                world,
                day,
                rhythm=rhythms.get(day.date),
                seed=calendar.seed if rhythm_profile is not None else None,
            )
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
        simulatable_days.append(scenario.days[0])

    if not runs:
        raise HorizonError("no simulatable days were produced")

    manifest = SimulationBatchManifest(experiment_id=f"{world.persona_id}_horizon", runs=runs)
    manifest_path = output_dir / "batch-manifest.json"
    _write(manifest_path, manifest)

    trace_path = output_dir / "planned-habit-trace.json"
    _write(trace_path, build_planned_trace(calendar, start_index=start_index, days=days))

    scenario_path = output_dir / "horizon-scenario.json"
    _write(scenario_path, _horizon_scenario(world, simulatable_days))

    return HorizonResult(
        manifest_path=manifest_path,
        day_count=len(runs),
        trace_path=trace_path,
        failed_days=failed,
        scenario_path=scenario_path,
    )


def _horizon_scenario(world: PlanningWorld, days: list[DayPlan]) -> Scenario:
    """One scenario document covering every simulatable day of the horizon.

    This is the researcher-facing INPUT record of what was generated, imported into the workspace
    like any other authored scenario. It is deliberately never compiled as a whole — CP-SAT does not
    scale past a handful of days — so each day keeps its own compiled plan and bundle; the horizon
    document exists so the home has one inspectable, exportable source of truth for its behaviour.
    """
    timezone = ZoneInfo(world.time_zone)
    start = datetime.combine(days[0].date, time(0, 0), tzinfo=timezone)
    end = datetime.combine(days[-1].date + timedelta(days=1), time(0, 0), tzinfo=timezone)
    return assemble_scenario(world, days=days, window=SimulationWindow(start=start, end=end))
