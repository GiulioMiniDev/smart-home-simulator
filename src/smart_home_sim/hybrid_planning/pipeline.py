"""End-to-end local generation: one brief to a simulatable batch manifest (no simulation).

Chains every stage — invent persona, author habits, build the world, author the process package,
roll the cadence calendar, optionally arrange days with the LLM, and merge into the batch manifest
plus the planned habit-mining ground truth. All artifacts are written to one output directory. This
is the reusable engine behind the CLI ``generate-dataset`` and the web generation job; it never
simulates (that stays the researcher's separate ``simulate-batch`` step).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path

from smart_home_sim.domain.base import ContractModel
from smart_home_sim.hybrid_planning.cadence import build_cadence_calendar
from smart_home_sim.hybrid_planning.habits import generate_habits
from smart_home_sim.hybrid_planning.horizon import HorizonResult, build_horizon
from smart_home_sim.hybrid_planning.llm_days import generate_llm_day_plans
from smart_home_sim.hybrid_planning.lmstudio import LMStudioClient
from smart_home_sim.hybrid_planning.package_authoring import author_process_package
from smart_home_sim.hybrid_planning.persona import generate_persona
from smart_home_sim.hybrid_planning.world import build_planning_world

ProgressCallback = Callable[[str, float, str], None]

# Ordered stages, for progress reporting.
STAGES: tuple[str, ...] = ("persona", "habits", "world", "package", "calendar", "days", "horizon")


def _emit(progress: ProgressCallback | None, index: int, message: str) -> None:
    if progress is not None:
        progress(STAGES[index], round((index / len(STAGES)) * 100, 1), message)


def _write(output_dir: Path, name: str, model: ContractModel) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / name).write_text(
        model.model_dump_json(by_alias=True, indent=2) + "\n", encoding="utf-8"
    )


def run_generation(
    brief: str,
    output_dir: Path,
    client: LMStudioClient,
    *,
    start_date: date,
    months: int = 1,
    use_llm_package: bool = False,
    use_llm_days: bool = False,
    seed: int | None = None,
    days: int | None = None,
    progress: ProgressCallback | None = None,
) -> HorizonResult:
    """Run the full local generation pipeline, writing every artifact under ``output_dir``."""
    _emit(progress, 0, "Inventing the persona")
    persona = generate_persona(brief, client, seed=seed).persona
    _write(output_dir, "persona.json", persona)

    _emit(progress, 1, "Authoring habits")
    profile = generate_habits(persona, client, seed=seed).profile
    _write(output_dir, "behavioral-profile.json", profile)

    _emit(progress, 2, "Building the planning world")
    world = build_planning_world(persona, seed=seed or 1)
    _write(output_dir, "planning-world.json", world)

    _emit(progress, 3, "Authoring the process package")
    package = author_process_package(
        persona, world, client=client if use_llm_package else None, seed=seed
    ).package
    _write(output_dir, "personal-process-package.json", package)

    _emit(progress, 4, "Rolling the cadence calendar")
    calendar = build_cadence_calendar(
        profile, start_date=start_date, months=months, seed=seed or 0
    ).calendar
    _write(output_dir, "cadence-calendar.json", calendar)

    day_plans = None
    if use_llm_days:
        _emit(progress, 5, "Arranging days with the LLM")
        day_plans = generate_llm_day_plans(world, calendar, client, days=days, seed=seed).day_plans
    else:
        _emit(progress, 5, "Using the deterministic day substrate")

    _emit(progress, 6, "Merging the horizon into a batch manifest")
    return build_horizon(world, package, calendar, output_dir, days=days, day_plans=day_plans)
