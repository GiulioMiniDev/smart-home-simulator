"""Authoritative simulation gate for hybrid-generated chunks (M8.1 Stage 2).

A generated weekly scenario can pass the plan-level gates (validation, compilation,
guardrails) yet still be impossible to execute — e.g. a resource precondition that no
ordering satisfies. The only authority on executability is the simulator itself. This
module materialises the home, builds the simulation bundle from a resident process package
and runs the M5 engine over the chunk, reporting whether it executes and, if not, which
activities (and therefore which days) are implicated so the plan can be repaired.

This runs only during authoring/generation. It never changes simulation semantics and is
never invoked by the runtime for already-accepted artifacts.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

from smart_home_sim.domain.behavior import PersonalProcessPackage
from smart_home_sim.domain.materialization import HomeGenerationPolicy
from smart_home_sim.domain.models import Scenario
from smart_home_sim.domain.plan import CanonicalPlan
from smart_home_sim.environment.service import build_bundle_files
from smart_home_sim.materialization.service import generate_home, load_home_policy
from smart_home_sim.simulation.service import simulate_bundle

_ACTIVITY_DATE = re.compile(r"(\d{4})(\d{2})(\d{2})")


@dataclass(frozen=True, slots=True)
class SimulationGateResult:
    success: bool
    stage: str  # "materialization" | "binding" | "execution" | "ok"
    messages: tuple[str, ...] = ()
    failing_activity_ids: frozenset[str] = frozenset()
    failing_dates: frozenset[date] = frozenset()


@dataclass(slots=True)
class _Issues:
    messages: list[str] = field(default_factory=list)
    activity_ids: set[str] = field(default_factory=set)


def _dates_from_activity_ids(activity_ids: set[str]) -> set[date]:
    dates: set[date] = set()
    for activity_id in activity_ids:
        match = _ACTIVITY_DATE.search(activity_id)
        if match:
            year, month, day = (int(part) for part in match.groups())
            try:
                dates.add(date(year, month, day))
            except ValueError:
                continue
    return dates


def simulate_chunk(
    scenario: Scenario,
    plan: CanonicalPlan,
    package: PersonalProcessPackage,
    *,
    home_policy: HomeGenerationPolicy | None = None,
) -> SimulationGateResult:
    """Materialise the home, build the bundle and simulate the chunk.

    Returns a structured result reporting the failing stage, human-readable messages and
    the activities/dates implicated by any failure. Never raises for a simulation-level
    failure; only unexpected infrastructure errors propagate.
    """

    policy = home_policy or load_home_policy(None)

    home_result = generate_home(scenario, package, policy)
    if home_result.home is None:
        return SimulationGateResult(
            success=False,
            stage="materialization",
            messages=tuple(issue.message for issue in home_result.report.issues) or (
                "home materialization failed",
            ),
        )

    with TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        scenario_file = tmp_path / "scenario.json"
        plan_file = tmp_path / "plan.json"
        package_file = tmp_path / "package.json"
        home_file = tmp_path / "home.json"
        scenario_file.write_text(scenario.model_dump_json(by_alias=True), encoding="utf-8")
        plan_file.write_text(plan.model_dump_json(by_alias=True), encoding="utf-8")
        package_file.write_text(package.model_dump_json(by_alias=True), encoding="utf-8")
        home_file.write_text(home_result.home.model_dump_json(by_alias=True), encoding="utf-8")

        bundle_result = build_bundle_files(scenario_file, plan_file, package_file, home_file)
        if bundle_result.bundle is None:
            issues = _collect(bundle_result.report.issues)
            return SimulationGateResult(
                success=False,
                stage="binding",
                messages=tuple(issues.messages) or ("bundle binding failed",),
                failing_activity_ids=frozenset(issues.activity_ids),
                failing_dates=frozenset(_dates_from_activity_ids(issues.activity_ids)),
            )

        sim_result = simulate_bundle(bundle_result.bundle)

    if sim_result.report.success and sim_result.trace is not None:
        return SimulationGateResult(success=True, stage="ok")

    issues = _collect(sim_result.report.issues)
    return SimulationGateResult(
        success=False,
        stage="execution",
        messages=tuple(issues.messages) or ("simulation failed",),
        failing_activity_ids=frozenset(issues.activity_ids),
        failing_dates=frozenset(_dates_from_activity_ids(issues.activity_ids)),
    )


def _collect(issues: object) -> _Issues:
    collected = _Issues()
    for issue in issues or []:  # type: ignore[union-attr]
        message = getattr(issue, "message", None)
        details = getattr(issue, "details", None) or {}
        activity_id = details.get("activityId") if isinstance(details, dict) else None
        code = getattr(issue, "code", "")
        if activity_id:
            collected.activity_ids.add(activity_id)
            collected.messages.append(f"{code} [{activity_id}]: {message}")
        else:
            collected.messages.append(f"{code}: {message}")
    return collected
