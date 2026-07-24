"""Stage A2b: author a persona's personal process package on the shared intent vocabulary.

The deterministic substrate retargets the bundled reference process models (proven simulatable in
the standard apartment) to the persona, assembles a ``PersonalProcessPackage``, and gates it with
the same behavior validator that manual inputs pass. A probe scenario — one activity per intent at
its default location — is what the gate validates against. An LLM per-intent authoring layer will
later sit on this substrate, falling back to the reference model when a proposal fails its checks.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from smart_home_sim.behavior.service import (
    default_action_catalog_path,
    default_activity_catalog_path,
    default_variable_catalog_path,
    validate_behavior,
)
from smart_home_sim.domain.behavior import (
    ActionCatalog,
    ActivityCatalog,
    BehaviorCatalogReferences,
    CatalogReference,
    PersonalProcessPackage,
    ProcessBinding,
    VariableCatalog,
)
from smart_home_sim.domain.behavior_report import BehaviorValidationReport
from smart_home_sim.domain.models import (
    Activity,
    AuthorType,
    DateTimeWindow,
    DayContext,
    DayPlan,
    DurationRange,
    Provenance,
    Scenario,
    SimulationWindow,
)
from smart_home_sim.hybrid_planning.intents import INTENT_CATALOG, reference_model
from smart_home_sim.hybrid_planning.persona import Persona
from smart_home_sim.hybrid_planning.world import PlanningWorld, assemble_scenario

GENERATOR_NAME = "smart-home-sim.hybrid_planning.package_authoring"
GENERATOR_VERSION = "1.0.0"

ACTIVITY_CATALOG_VERSION = "1.1.0"
VARIABLE_CATALOG_VERSION = "1.0.0"
ACTION_CATALOG_VERSION = "1.1.0"

_PROBE_START = date(2026, 1, 5)  # an arbitrary Monday; the probe scenario is throwaway
_PROBE_STEP = timedelta(minutes=25)


class PackageAuthoringError(ValueError):
    """The assembled package did not pass the behavior gate."""


@dataclass(frozen=True)
class ProcessPackageResult:
    package: PersonalProcessPackage
    report: BehaviorValidationReport


def build_reference_package(
    persona: Persona,
    world: PlanningWorld,
    *,
    package_version: str = "1.0.0",
    now: datetime | None = None,
) -> PersonalProcessPackage:
    """Retarget the bundled reference models to the persona and assemble a package (no LLM)."""
    resident_id = persona.persona_id
    models = []
    bindings = []
    for spec in INTENT_CATALOG:
        model_id = f"{resident_id}__{spec.intent_id}"
        models.append(
            reference_model(spec.intent_id).model_copy(
                update={"process_model_id": model_id, "resident_id": resident_id}
            )
        )
        bindings.append(
            ProcessBinding(
                binding_id=f"binding__{spec.intent_id}",
                resident_id=resident_id,
                intent=spec.intent_id,
                process_model_id=model_id,
            )
        )
    return PersonalProcessPackage(
        package_id=f"{resident_id}_package",
        package_version=package_version,
        source_scenario_id=world.scenario_id,
        source_scenario_version="1.0.0",
        language=world.language,
        provenance=Provenance(
            author_type=AuthorType.rule_generator,
            generator_name=GENERATOR_NAME,
            generator_version=GENERATOR_VERSION,
            generated_at=now or datetime.now(UTC),
        ),
        catalogs=BehaviorCatalogReferences(
            activity_catalog=CatalogReference(
                catalog_id="smart_home_activity_catalog", version=ACTIVITY_CATALOG_VERSION
            ),
            variable_catalog=CatalogReference(
                catalog_id="smart_home_variable_catalog", version=VARIABLE_CATALOG_VERSION
            ),
            action_catalog=CatalogReference(
                catalog_id="smart_home_action_catalog", version=ACTION_CATALOG_VERSION
            ),
        ),
        process_models=models,
        bindings=bindings,
    )


def build_probe_scenario(world: PlanningWorld) -> Scenario:
    """Assemble a throwaway scenario with one activity per intent, for gating the package."""
    tz = ZoneInfo(world.time_zone)
    start = datetime.combine(_PROBE_START, datetime.min.time(), tzinfo=tz)
    window = SimulationWindow(start=start, end=start + timedelta(days=1))
    moment = start + timedelta(hours=6)
    activities = []
    for index, spec in enumerate(INTENT_CATALOG):
        activities.append(
            Activity(
                activity_id=f"probe_{index}",
                actor_id=world.residents[0].resident_id,
                intent=spec.intent_id,
                location_ids=[spec.default_location],
                start_window=DateTimeWindow(earliest=moment, preferred=moment, latest=moment),
                duration=DurationRange(
                    minimum_minutes=10, preferred_minutes=10, maximum_minutes=10
                ),
            )
        )
        moment += _PROBE_STEP
    day = DayPlan(
        date=_PROBE_START, context=DayContext(day_type="working_day"), activities=activities
    )
    return assemble_scenario(world, days=[day], window=window)


def gate_package(package: PersonalProcessPackage, scenario: Scenario) -> BehaviorValidationReport:
    """Run the same behavior gate manual inputs pass, using the bundled catalogs."""
    return validate_behavior(
        package,
        scenario,
        ActivityCatalog.model_validate_json(
            default_activity_catalog_path(ACTIVITY_CATALOG_VERSION).read_text(encoding="utf-8")
        ),
        VariableCatalog.model_validate_json(
            default_variable_catalog_path().read_text(encoding="utf-8")
        ),
        ActionCatalog.model_validate_json(
            default_action_catalog_path(ACTION_CATALOG_VERSION).read_text(encoding="utf-8")
        ),
    )


def author_process_package(
    persona: Persona,
    world: PlanningWorld,
    *,
    package_version: str = "1.0.0",
    now: datetime | None = None,
) -> ProcessPackageResult:
    """Author and gate a persona's process package (deterministic substrate)."""
    package = build_reference_package(persona, world, package_version=package_version, now=now)
    report = gate_package(package, build_probe_scenario(world))
    if not report.valid:
        first = next((issue for issue in report.issues if issue.severity == "error"), None)
        detail = f"{first.code}: {first.message}" if first is not None else "unknown gate failure"
        raise PackageAuthoringError(f"Authored package failed the behavior gate ({detail})")
    return ProcessPackageResult(package=package, report=report)
