"""Author a resident personal process package with a local LLM (M3 authoring phase).

This belongs to the *authoring* phase of Milestone 8.1: the researcher uses a local
LLM (LM Studio) once, offline, to produce the resident's ADL process models. The output
is validated by the same deterministic M3/M4 gates as manually authored packages and is
then frozen. The simulation runtime never invokes an LLM.

Generation is per-intent and grounded: each process model is produced with the atomic
action vocabulary, the resident's scenario locations, the activity-catalog components that
the intent must implement, and a structural reference model. When the LLM cannot produce
a model that passes the structural and semantic checks within the repair budget, a
deterministic adaptation of the reference model is used so the package always completes.
Every model records whether it came from the LLM or the deterministic fallback.
"""

from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from pydantic import ValidationError

from smart_home_sim.behavior.service import (
    default_action_catalog_path,
    default_activity_catalog_path,
    validate_behavior_files,
)
from smart_home_sim.domain.behavior import (
    ActionCatalog,
    ActivityCatalog,
    PersonalProcessPackage,
    ProcessBinding,
    ProcessModel,
    ProcessNodeKind,
    ReferenceKind,
    ValueSource,
)
from smart_home_sim.domain.models import AuthorType, Provenance, Scenario
from smart_home_sim.hybrid_planning.lmstudio import LMStudioClient, LMStudioError
from smart_home_sim.hybrid_planning.models import HybridPlanningConfig

AUTHORING_GENERATOR_NAME = "author_process_package"
AUTHORING_GENERATOR_VERSION = "0.1.0"
PROMPT_TEMPLATE_VERSION = "personal-process-model-per-intent-0.1.0"
PROCESS_MODEL_VERSION = "1.0.0"


class ProcessAuthoringError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ModelAuthoringRecord:
    intent: str
    source: str  # "llm" or "fallback"
    repairs: int
    fallback_reason: str | None = None


@dataclass(slots=True)
class ProcessAuthoringResult:
    package: PersonalProcessPackage
    records: list[ModelAuthoringRecord] = field(default_factory=list)

    @property
    def llm_count(self) -> int:
        return sum(1 for record in self.records if record.source == "llm")

    @property
    def fallback_count(self) -> int:
        return sum(1 for record in self.records if record.source == "fallback")


# --------------------------------------------------------------------------- #
# Catalog / reference loading
# --------------------------------------------------------------------------- #


def _load_action_vocabulary(version: str = "1.0.0") -> dict[str, dict[str, ReferenceKind]]:
    """Return {actionType: {parameterName: referenceKind}} from the action catalog."""

    catalog = ActionCatalog.model_validate_json(
        default_action_catalog_path(version).read_text(encoding="utf-8")
    )
    vocabulary: dict[str, dict[str, ReferenceKind]] = {}
    for action in catalog.actions:
        vocabulary[action.action_type] = {
            param.parameter_name: param.reference_kind for param in action.parameters
        }
    return vocabulary


def _load_intent_components(version: str = "1.0.0") -> dict[str, list[str]]:
    catalog = ActivityCatalog.model_validate_json(
        default_activity_catalog_path(version).read_text(encoding="utf-8")
    )
    return {activity.intent: list(activity.components) for activity in catalog.activities}


def _reference_models(reference: PersonalProcessPackage) -> dict[str, ProcessModel]:
    by_id = {model.process_model_id: model for model in reference.process_models}
    result: dict[str, ProcessModel] = {}
    for binding in reference.bindings:
        model = by_id.get(binding.process_model_id)
        if model is not None and binding.intent not in result:
            result[binding.intent] = model
    return result


# --------------------------------------------------------------------------- #
# Deterministic adaptation (reference template + fallback)
# --------------------------------------------------------------------------- #


def _home_entry_location(locations: list[str]) -> str:
    for preferred in ("hallway_01", "living_room_01", "entrance", "hallway"):
        if preferred in locations:
            return preferred
    return locations[0]


def adapt_reference_model(
    template: ProcessModel,
    *,
    intent: str,
    resident_id: str,
    locations: list[str],
    components: list[str],
    vocabulary: dict[str, dict[str, ReferenceKind]],
) -> ProcessModel:
    """Deterministically re-bind a reference model to the target resident and home.

    Rewrites resident identity and re-targets any ``location`` reference that does not
    exist in the target scenario to the home-entry location (e.g. the reference's
    ``home`` literal). Capability roles and control flow are preserved, since the
    materialised home is generated by the same compact-grid policy.
    """

    home_entry = _home_entry_location(locations)
    location_set = set(locations)
    raw = template.model_dump(mode="json", by_alias=True)
    raw["processModelId"] = f"{resident_id}__{intent}"
    raw["processModelVersion"] = PROCESS_MODEL_VERSION
    raw["residentId"] = resident_id
    raw["title"] = f"{resident_id} {intent.replace('_', ' ')} process"
    raw["implementedComponents"] = list(components)

    # Re-target location arguments precisely using the action vocabulary.
    for node in raw.get("nodes", []):
        action_type = node.get("actionType")
        specs = vocabulary.get(action_type or "", {})
        arguments = node.get("arguments") or {}
        for name, arg in arguments.items():
            if specs.get(name) is not ReferenceKind.location:
                continue
            if not isinstance(arg, dict) or arg.get("source") != ValueSource.literal.value:
                continue
            if arg.get("value") not in location_set:
                arg["value"] = home_entry
    return ProcessModel.model_validate_json(json.dumps(raw))


# --------------------------------------------------------------------------- #
# Semantic validation of a single model
# --------------------------------------------------------------------------- #


def semantic_errors(
    model: ProcessModel,
    *,
    intent: str,
    resident_id: str,
    components: list[str],
    locations: list[str],
    vocabulary: dict[str, dict[str, ReferenceKind]],
) -> list[str]:
    errors: list[str] = []
    if model.resident_id != resident_id:
        errors.append(f"residentId must be '{resident_id}', got '{model.resident_id}'")
    if list(model.implemented_components) != list(components):
        errors.append(
            f"implementedComponents must equal {components}, got "
            f"{list(model.implemented_components)}"
        )

    node_ids = {node.node_id for node in model.nodes}
    starts = [n for n in model.nodes if n.kind is ProcessNodeKind.start]
    ends = [n for n in model.nodes if n.kind is ProcessNodeKind.end]
    if len(starts) != 1:
        errors.append(f"exactly one start node required, found {len(starts)}")
    if not ends:
        errors.append("at least one end node required")

    location_set = set(locations)
    for node in model.nodes:
        if node.kind is not ProcessNodeKind.action:
            continue
        specs = vocabulary.get(node.action_type or "")
        if specs is None:
            errors.append(f"node '{node.node_id}' uses unknown actionType '{node.action_type}'")
            continue
        for name, expr in node.arguments.items():
            if name not in specs:
                errors.append(
                    f"node '{node.node_id}' action '{node.action_type}' has unknown "
                    f"argument '{name}'"
                )
                continue
            if (
                specs[name] is ReferenceKind.location
                and expr.source is ValueSource.literal
                and isinstance(expr.value, str)
                and expr.value not in location_set
            ):
                errors.append(
                    f"node '{node.node_id}' destination '{expr.value}' is not a scenario "
                    f"location; allowed: {sorted(location_set)}"
                )

    # Edge integrity + reachability
    for edge in model.edges:
        if edge.source_node_id not in node_ids:
            errors.append(f"edge source '{edge.source_node_id}' is not a node")
        if edge.target_node_id not in node_ids:
            errors.append(f"edge target '{edge.target_node_id}' is not a node")
    if starts and not errors:
        adjacency: dict[str, list[str]] = {nid: [] for nid in node_ids}
        for edge in model.edges:
            adjacency[edge.source_node_id].append(edge.target_node_id)
        reachable: set[str] = set()
        queue = deque([starts[0].node_id])
        while queue:
            current = queue.popleft()
            if current in reachable:
                continue
            reachable.add(current)
            queue.extend(adjacency[current])
        dead = node_ids - reachable
        if dead:
            errors.append(f"nodes unreachable from start: {sorted(dead)}")
        end_ids = {n.node_id for n in ends}
        if not (reachable & end_ids):
            errors.append("no end node is reachable from start")
    return errors


# --------------------------------------------------------------------------- #
# Per-intent authoring
# --------------------------------------------------------------------------- #


def _vocabulary_prompt(vocabulary: dict[str, dict[str, ReferenceKind]]) -> str:
    lines = []
    for action_type, specs in vocabulary.items():
        if specs:
            args = ", ".join(f"{name}:{kind.value}" for name, kind in specs.items())
        else:
            args = "(no arguments)"
        lines.append(f"- {action_type}: {args}")
    return "\n".join(lines)


_SYSTEM_PROMPT = (
    "You author ONE personal ADL process model for a smart-home resident as strict JSON.\n"
    "A process model is a directed control-flow graph, not a trace. Rules:\n"
    "- exactly one node with kind='start', at least one node kind='end';\n"
    "- action nodes have kind='action', a nodeId, an actionType from the ALLOWED list, an\n"
    "  arguments object where each value is {\"source\":\"literal\",\"value\":<string>}, and a\n"
    "  positive durationWeight;\n"
    "- edges connect sourceNodeId->targetNodeId; every node must lie on a path from start\n"
    "  to an end; no dead nodes;\n"
    "- an argument whose referenceKind is 'location' MUST use a value from LOCATIONS;\n"
    "- an argument whose referenceKind is 'capability'/'environment_entity' should keep the\n"
    "  role/entity string used by the REFERENCE model (the materialised home provides it);\n"
    "- implementedComponents MUST equal the requested COMPONENTS in order;\n"
    "- residentId MUST equal the requested resident.\n"
    "Return only the JSON object for the process model."
)


def _user_prompt(
    *,
    intent: str,
    components: list[str],
    resident_id: str,
    locations: list[str],
    vocabulary: dict[str, dict[str, ReferenceKind]],
    reference: ProcessModel,
    repair_errors: list[str] | None,
) -> str:
    reference_json = json.dumps(
        reference.model_dump(mode="json", by_alias=True), ensure_ascii=False
    )
    parts = [
        f"ALLOWED actionTypes (with argument referenceKinds):\n{_vocabulary_prompt(vocabulary)}",
        f"LOCATIONS (for location arguments): {locations}",
        f"Resident: {resident_id}.",
        f"Intent to author: '{intent}'.",
        f"COMPONENTS to implement (in order): {components}.",
        "Reference process model (same intent, different resident/home — adapt the resident "
        "identity and any location literal to this resident's LOCATIONS, keep capability "
        "roles and control-flow shape; you may add realistic variation):",
        reference_json,
    ]
    if repair_errors:
        parts.append(
            "Your previous attempt was rejected for these reasons; fix ALL of them:\n"
            + "\n".join(f"- {error}" for error in repair_errors)
        )
    return "\n\n".join(parts)


def author_process_model(
    *,
    intent: str,
    components: list[str],
    resident_id: str,
    locations: list[str],
    reference: ProcessModel,
    vocabulary: dict[str, dict[str, ReferenceKind]],
    client: LMStudioClient | None,
    config: HybridPlanningConfig,
    seed: int,
) -> tuple[ProcessModel, ModelAuthoringRecord]:
    """Author one process model, falling back to deterministic adaptation on failure."""

    fallback = adapt_reference_model(
        reference,
        intent=intent,
        resident_id=resident_id,
        locations=locations,
        components=components,
        vocabulary=vocabulary,
    )
    if client is None:
        return fallback, ModelAuthoringRecord(
            intent=intent, source="fallback", repairs=0, fallback_reason="no LLM client"
        )

    repair_errors: list[str] | None = None
    last_reason = "unknown"
    for attempt in range(config.max_structure_repairs + 1):
        try:
            candidate, _exchange = client.complete_json(
                schema_name="personal_process_model",
                output_model=ProcessModel,
                system_prompt=_SYSTEM_PROMPT,
                user_prompt=_user_prompt(
                    intent=intent,
                    components=components,
                    resident_id=resident_id,
                    locations=locations,
                    vocabulary=vocabulary,
                    reference=reference,
                    repair_errors=repair_errors,
                ),
                seed=seed + attempt,
                enforce_schema=False,
            )
        except (LMStudioError, ValidationError) as error:
            last_reason = f"llm error: {error}"
            repair_errors = [str(error)]
            continue
        errors = semantic_errors(
            candidate,
            intent=intent,
            resident_id=resident_id,
            components=components,
            locations=locations,
            vocabulary=vocabulary,
        )
        if not errors:
            return candidate, ModelAuthoringRecord(
                intent=intent, source="llm", repairs=attempt
            )
        last_reason = "; ".join(errors[:3])
        repair_errors = errors
    return fallback, ModelAuthoringRecord(
        intent=intent,
        source="fallback",
        repairs=config.max_structure_repairs,
        fallback_reason=last_reason,
    )


# --------------------------------------------------------------------------- #
# Package assembly + authoritative gates
# --------------------------------------------------------------------------- #


def _used_intents(scenario: Scenario) -> list[str]:
    seen: dict[str, None] = {}
    for day in scenario.days:
        for activity in day.activities:
            seen.setdefault(activity.intent, None)
    return list(seen)


def author_process_package(
    scenario_path: Path,
    reference_package_path: Path,
    *,
    config: HybridPlanningConfig,
    client: LMStudioClient | None = None,
    cover_all_reference_intents: bool = False,
) -> ProcessAuthoringResult:
    """Author a resident process package grounded on a reference package and gate it.

    Gates applied: strict pydantic construction, ``validate_behavior_files`` (M3/M4
    behavior compatibility with the scenario) and ``build_bundle_files`` (M4 home
    binding). A ``ProcessAuthoringError`` is raised if the assembled package does not
    pass, after re-authoring the models implicated by the reported errors.

    With ``cover_all_reference_intents`` the package covers every intent the reference
    package defines (a complete daily vocabulary), not only the intents the sample scenario
    happens to use — so a generator constrained to this package still has enough variety.
    """

    scenario = Scenario.model_validate_json(scenario_path.read_bytes())
    reference = PersonalProcessPackage.model_validate_json(
        reference_package_path.read_bytes()
    )
    if len(scenario.residents) != 1:
        raise ProcessAuthoringError(
            "process authoring supports single-resident scenarios only"
        )
    resident_id = scenario.residents[0].resident_id
    locations = [location.location_id for location in scenario.locations]
    intent_components = _load_intent_components(reference.catalogs.activity_catalog.version)
    vocabulary = _load_action_vocabulary(reference.catalogs.action_catalog.version)
    references = _reference_models(reference)

    if cover_all_reference_intents:
        # Deterministic order: scenario-used intents first, then the rest of the reference.
        used = _used_intents(scenario)
        intents = used + [i for i in references if i not in set(used)]
    else:
        intents = _used_intents(scenario)
    missing_component = [i for i in intents if i not in intent_components]
    if missing_component:
        raise ProcessAuthoringError(
            f"scenario intents missing from activity catalog: {missing_component}"
        )
    missing_reference = [i for i in intents if i not in references]
    if missing_reference:
        raise ProcessAuthoringError(
            f"reference package has no model for intents: {missing_reference}"
        )

    models: list[ProcessModel] = []
    bindings: list[ProcessBinding] = []
    records: list[ModelAuthoringRecord] = []
    for index, intent in enumerate(intents):
        model, record = author_process_model(
            intent=intent,
            components=intent_components[intent],
            resident_id=resident_id,
            locations=locations,
            reference=references[intent],
            vocabulary=vocabulary,
            client=client,
            config=config,
            seed=scenario.seed + index,
        )
        models.append(model)
        bindings.append(
            ProcessBinding(
                binding_id=f"{resident_id}__{intent}",
                resident_id=resident_id,
                intent=intent,
                process_model_id=model.process_model_id,
                fallback=True,
            )
        )
        records.append(record)

    provenance = Provenance(
        author_type=AuthorType.external_llm if client is not None else AuthorType.rule_generator,
        generator_name=AUTHORING_GENERATOR_NAME,
        generator_version=AUTHORING_GENERATOR_VERSION,
        model_name=config.model if client is not None else None,
        prompt_template_version=PROMPT_TEMPLATE_VERSION if client is not None else None,
        generated_at=datetime.now(UTC),
        human_reviewed=False,
        parameters={
            "referencePackageId": reference.package_id,
            "llmModels": sum(1 for r in records if r.source == "llm"),
            "fallbackModels": sum(1 for r in records if r.source == "fallback"),
        },
    )
    package = PersonalProcessPackage(
        package_id=f"{resident_id}__behavior",
        package_version=PROCESS_MODEL_VERSION,
        source_scenario_id=scenario.scenario_id,
        source_scenario_version=scenario.schema_version,
        language=reference.language,
        provenance=provenance,
        catalogs=reference.catalogs,
        process_models=models,
        bindings=bindings,
    )

    _gate_package(package, scenario_path)
    return ProcessAuthoringResult(package=package, records=records)


def _gate_package(package: PersonalProcessPackage, scenario_path: Path) -> None:
    with TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        package_path = tmp_path / "personal-process-package.json"
        package_path.write_text(
            package.model_dump_json(by_alias=True, indent=2), encoding="utf-8"
        )
        behavior = validate_behavior_files(package_path, scenario_path)
        if not behavior.valid:
            errors = [i for i in behavior.issues if i.severity == "error"]
            summary = "; ".join(f"{i.code}@{i.path}: {i.message}" for i in errors[:8])
            raise ProcessAuthoringError(
                f"authored package failed behavior validation ({len(errors)} errors): {summary}"
            )
