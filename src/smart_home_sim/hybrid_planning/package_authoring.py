"""Stage A2b: author a persona's personal process package on the shared intent vocabulary.

The deterministic substrate retargets the bundled reference process models (proven simulatable in
the standard apartment) to the persona, assembles a ``PersonalProcessPackage``, and gates it with
the same behavior validator that manual inputs pass. A probe scenario — one activity per intent at
its default location — is what the gate validates against.

The optional LLM layer sits on this substrate: for each intent the model proposes a process model
grounded on the (already valid, retargeted) reference; a candidate is accepted only if swapping it
in keeps the whole package passing the gate, else the reference is kept. The result is therefore
always valid, and the LLM contributes variation only where it stays physically coherent.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo

from pydantic import ValidationError

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
    ProcessModel,
    ProcessNodeKind,
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
from smart_home_sim.hybrid_planning.lmstudio import (
    ChatMessage,
    LMStudioClient,
    LMStudioContentError,
)
from smart_home_sim.hybrid_planning.persona import Persona
from smart_home_sim.hybrid_planning.world import PlanningWorld, assemble_scenario

GENERATOR_NAME = "smart-home-sim.hybrid_planning.package_authoring"
GENERATOR_VERSION = "1.0.0"

ACTIVITY_CATALOG_VERSION = "1.1.0"
VARIABLE_CATALOG_VERSION = "1.0.0"
ACTION_CATALOG_VERSION = "1.1.0"

# A single process model is small, but a reasoning model spends completion tokens thinking first.
MODEL_MAX_TOKENS = 8192

_PROBE_START = date(2026, 1, 5)  # an arbitrary Monday; the probe scenario is throwaway
_PROBE_STEP = timedelta(minutes=25)


class PackageAuthoringError(ValueError):
    """The assembled package did not pass the behavior gate."""


class _ModelParseError(ValueError):
    """An LLM process-model proposal could not be normalised into a valid model."""


@dataclass(frozen=True)
class ProcessPackageResult:
    package: PersonalProcessPackage
    report: BehaviorValidationReport
    llm_authored_count: int = 0
    fallback_count: int = 0


def _retarget_reference(intent_id: str, resident_id: str) -> ProcessModel:
    return reference_model(intent_id).model_copy(
        update={"process_model_id": f"{resident_id}__{intent_id}", "resident_id": resident_id}
    )


def _assemble_package(
    persona: Persona,
    world: PlanningWorld,
    models_by_intent: dict[str, ProcessModel],
    *,
    package_version: str,
    now: datetime | None,
) -> PersonalProcessPackage:
    resident_id = persona.persona_id
    bindings = [
        ProcessBinding(
            binding_id=f"binding__{spec.intent_id}",
            resident_id=resident_id,
            intent=spec.intent_id,
            process_model_id=f"{resident_id}__{spec.intent_id}",
        )
        for spec in INTENT_CATALOG
    ]
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
        process_models=[models_by_intent[spec.intent_id] for spec in INTENT_CATALOG],
        bindings=bindings,
    )


def build_reference_package(
    persona: Persona,
    world: PlanningWorld,
    *,
    package_version: str = "1.0.0",
    now: datetime | None = None,
) -> PersonalProcessPackage:
    """Retarget the bundled reference models to the persona and assemble a package (no LLM)."""
    models = {
        spec.intent_id: _retarget_reference(spec.intent_id, persona.persona_id)
        for spec in INTENT_CATALOG
    }
    return _assemble_package(persona, world, models, package_version=package_version, now=now)


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


@lru_cache(maxsize=1)
def _catalogs() -> tuple[ActivityCatalog, VariableCatalog, ActionCatalog]:
    return (
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


def _action_vocabulary() -> set[str]:
    return {action.action_type for action in _catalogs()[2].actions}


def gate_package(package: PersonalProcessPackage, scenario: Scenario) -> BehaviorValidationReport:
    """Run the same behavior gate manual inputs pass, using the bundled catalogs."""
    activity_catalog, variable_catalog, action_catalog = _catalogs()
    return validate_behavior(package, scenario, activity_catalog, variable_catalog, action_catalog)


def author_process_package(
    persona: Persona,
    world: PlanningWorld,
    *,
    client: LMStudioClient | None = None,
    seed: int | None = None,
    max_repairs: int = 1,
    package_version: str = "1.0.0",
    now: datetime | None = None,
) -> ProcessPackageResult:
    """Author and gate a persona's process package; use the LLM layer when a client is supplied."""
    resident_id = persona.persona_id
    accepted = {
        spec.intent_id: _retarget_reference(spec.intent_id, resident_id) for spec in INTENT_CATALOG
    }
    llm_count = 0

    if client is not None:
        vocabulary = _action_vocabulary()
        probe = build_probe_scenario(world)
        for spec in INTENT_CATALOG:
            candidate = _author_model_via_llm(
                client, spec.intent_id, accepted[spec.intent_id], vocabulary, resident_id,
                seed=seed, max_repairs=max_repairs,
            )
            if candidate is None:
                continue
            trial = {**accepted, spec.intent_id: candidate}
            report = gate_package(
                _assemble_package(persona, world, trial, package_version=package_version, now=now),
                probe,
            )
            if report.valid:
                accepted = trial
                llm_count += 1

    package = _assemble_package(persona, world, accepted, package_version=package_version, now=now)
    report = gate_package(package, build_probe_scenario(world))
    if not report.valid:
        first = next((issue for issue in report.issues if issue.severity == "error"), None)
        detail = f"{first.code}: {first.message}" if first is not None else "unknown gate failure"
        raise PackageAuthoringError(f"Authored package failed the behavior gate ({detail})")
    return ProcessPackageResult(
        package=package,
        report=report,
        llm_authored_count=llm_count,
        fallback_count=len(INTENT_CATALOG) - llm_count,
    )


def _author_model_via_llm(
    client: LMStudioClient,
    intent_id: str,
    reference: ProcessModel,
    vocabulary: set[str],
    resident_id: str,
    *,
    seed: int | None,
    max_repairs: int,
) -> ProcessModel | None:
    """Ask the model for a coherent variant of the reference; return a parsed model or None."""
    messages = _model_messages(intent_id, reference, vocabulary)
    for _ in range(max_repairs + 1):
        try:
            completion = client.complete_json(messages, seed=seed, max_tokens=MODEL_MAX_TOKENS)
            return _parse_model(completion.data, intent_id, reference, vocabulary, resident_id)
        except (LMStudioContentError, _ModelParseError) as error:
            messages = _repair_messages(intent_id, reference, vocabulary, str(error))
    return None


def _parse_model(
    data: object,
    intent_id: str,
    reference: ProcessModel,
    vocabulary: set[str],
    resident_id: str,
) -> ProcessModel:
    if not isinstance(data, dict):
        raise _ModelParseError("process model must be a JSON object")
    try:
        model = ProcessModel.model_validate_json(json.dumps(data))
    except ValidationError as error:
        raise _ModelParseError(f"invalid process model: {error}") from error
    used = {
        node.action_type
        for node in model.nodes
        if node.kind is ProcessNodeKind.action and node.action_type is not None
    }
    unknown = used - vocabulary
    if unknown:
        raise _ModelParseError(f"unknown action types: {sorted(unknown)}")
    return model.model_copy(
        update={
            "process_model_id": f"{resident_id}__{intent_id}",
            "resident_id": resident_id,
            "implemented_components": list(reference.implemented_components),
        }
    )


def _model_messages(
    intent_id: str, reference: ProcessModel, vocabulary: set[str]
) -> list[ChatMessage]:
    system = (
        "You author one ADL process model as strict JSON for a smart-home simulator. "
        "Reply with a single JSON object and no prose."
    )
    user = (
        f"Intent: {intent_id}. Here is a valid reference process model:\n"
        f"{reference.model_dump_json(by_alias=True)}\n\n"
        "Produce a process model for the same intent and resident. Keep the same JSON structure "
        "(nodes with nodeId, kind, actionType, arguments, durationWeight, effects; edges with "
        "sourceNodeId, targetNodeId). You may keep or slightly vary the action sequence, but it "
        "must stay physically coherent, begin at the 'start' node and reach the 'end' node. "
        f"Use ONLY these action types: {sorted(vocabulary)}. Output the full JSON model."
    )
    return [ChatMessage("system", system), ChatMessage("user", user)]


def _repair_messages(
    intent_id: str, reference: ProcessModel, vocabulary: set[str], error: str
) -> list[ChatMessage]:
    base = _model_messages(intent_id, reference, vocabulary)
    base.append(
        ChatMessage(
            "user",
            f"The previous attempt was rejected: {error}. Return a corrected single JSON model "
            "matching the reference structure exactly.",
        )
    )
    return base
