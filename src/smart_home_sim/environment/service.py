from __future__ import annotations

import json
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Any

import networkx as nx
from pydantic import ValidationError
from shapely.geometry import Point, Polygon

from smart_home_sim.behavior.service import (
    _binding_applies,
    _resolve_variable,
    default_action_catalog_path,
    default_activity_catalog_path,
    default_variable_catalog_path,
    validate_behavior_files,
)
from smart_home_sim.compiler.service import canonical_sha256, compile_scenario
from smart_home_sim.domain.behavior import (
    ActionCatalog,
    PersonalProcessPackage,
    ProcessNodeKind,
    ValueSource,
    VariableCatalog,
)
from smart_home_sim.domain.environment import (
    ArtifactDigest,
    BundleBuildResult,
    ConnectionKind,
    EnvironmentValidationIssue,
    EnvironmentValidationReport,
    HomeEntity,
    HomeModel,
    ResolvedActionBinding,
    ResolvedCapabilityBinding,
    ResolvedKinematics,
    SimulationBundle,
)
from smart_home_sim.domain.models import DayPlan, Scenario
from smart_home_sim.domain.plan import CanonicalPlan
from smart_home_sim.environment.issues import environment_issue
from smart_home_sim.environment.navigation import plan_path
from smart_home_sim.validation.service import (
    MAX_JSON_NESTING,
    MAX_SCENARIO_BYTES,
    DuplicateJsonKeyError,
    InvalidJsonConstantError,
    _exceeds_json_nesting_limit,
    _json_path,
    _reject_duplicate_keys,
    _reject_non_finite_constant,
    validate_file,
)

SUPPORTED_ENVIRONMENT_VERSION = "1.0.0"


def _polygon(vertices: list[Any]) -> Polygon:
    return Polygon([(point.x, point.y) for point in vertices])


def _sort_issues(issues: list[EnvironmentValidationIssue]) -> list[EnvironmentValidationIssue]:
    return sorted(issues, key=lambda item: (item.path, item.code, item.message))


def _read_json(path: Path, artifact: str) -> tuple[Any | None, EnvironmentValidationIssue | None]:
    try:
        if path.stat().st_size > MAX_SCENARIO_BYTES:
            return None, environment_issue(
                "FILE_TOO_LARGE", "structure", "$", f"{artifact} exceeds the input size limit."
            )
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None, environment_issue(
            "FILE_NOT_FOUND", "structure", "$", f"{artifact} file was not found."
        )
    except UnicodeDecodeError:
        return None, environment_issue(
            "FILE_ENCODING_ERROR", "structure", "$", f"{artifact} must be UTF-8."
        )
    except OSError as error:
        return None, environment_issue(
            "FILE_READ_ERROR", "structure", "$", f"Could not read {artifact}: {error}."
        )
    if _exceeds_json_nesting_limit(raw):
        return None, environment_issue(
            "JSON_NESTING_TOO_DEEP",
            "structure",
            "$",
            f"{artifact} exceeds {MAX_JSON_NESTING} nesting levels.",
        )
    try:
        return (
            json.loads(
                raw,
                object_pairs_hook=_reject_duplicate_keys,
                parse_constant=_reject_non_finite_constant,
            ),
            None,
        )
    except (DuplicateJsonKeyError, InvalidJsonConstantError, json.JSONDecodeError) as error:
        return None, environment_issue(
            "JSON_SYNTAX", "structure", "$", f"Invalid JSON in {artifact}: {error}."
        )


def _parse_home(payload: Any) -> tuple[HomeModel | None, list[EnvironmentValidationIssue]]:
    if not isinstance(payload, dict):
        return None, [
            environment_issue(
                "STRUCTURE_INVALID", "structure", "$", "Home model must be an object."
            )
        ]
    if payload.get("schemaVersion") != SUPPORTED_ENVIRONMENT_VERSION:
        return None, [
            environment_issue(
                "UNSUPPORTED_SCHEMA_VERSION",
                "structure",
                "$.schemaVersion",
                f"Expected home schemaVersion '{SUPPORTED_ENVIRONMENT_VERSION}'.",
            )
        ]
    try:
        return HomeModel.model_validate_json(json.dumps(payload, separators=(",", ":"))), []
    except ValidationError as error:
        return None, [
            environment_issue(
                "STRUCTURE_INVALID", "structure", _json_path(item["loc"]), item["msg"]
            )
            for item in error.errors(include_url=False, include_context=False, include_input=False)
        ]


def _duplicates(values: list[str]) -> list[str]:
    return sorted(value for value, count in Counter(values).items() if count > 1)


def validate_home_model(home: HomeModel) -> EnvironmentValidationReport:
    issues: list[EnvironmentValidationIssue] = []
    groups = {
        "regions": [item.region_id for item in home.regions],
        "connections": [item.connection_id for item in home.connections],
        "obstacles": [item.obstacle_id for item in home.obstacles],
        "interactionPoints": [item.interaction_point_id for item in home.interaction_points],
        "entities": [item.entity_id for item in home.entities],
        "locationBindings": [item.scenario_location_id for item in home.location_bindings],
        "resourceBindings": [item.scenario_resource_id for item in home.resource_bindings],
    }
    for group, identifiers in groups.items():
        for duplicate in _duplicates(identifiers):
            issues.append(
                environment_issue(
                    "DUPLICATE_IDENTIFIER",
                    "structure",
                    f"$.{group}",
                    f"Duplicate identifier '{duplicate}'.",
                )
            )

    regions = {item.region_id: item for item in home.regions}
    polygons: dict[str, Polygon] = {}
    for index, region in enumerate(home.regions):
        polygon = _polygon(region.boundary.vertices)
        polygons[region.region_id] = polygon
        if not polygon.is_valid or polygon.area <= 0:
            issues.append(
                environment_issue(
                    "GEOMETRY_INVALID",
                    "geometry",
                    f"$.regions[{index}].boundary",
                    f"Region '{region.region_id}' has an invalid polygon.",
                )
            )
    ordered_regions = sorted(polygons)
    for index, left_id in enumerate(ordered_regions):
        for right_id in ordered_regions[index + 1 :]:
            if polygons[left_id].intersection(polygons[right_id]).area > 1e-9:
                issues.append(
                    environment_issue(
                        "GEOMETRY_INVALID",
                        "geometry",
                        "$.regions",
                        f"Regions '{left_id}' and '{right_id}' overlap in their interiors.",
                    )
                )

    obstacle_polygons: dict[str, list[Polygon]] = {}
    for index, obstacle in enumerate(home.obstacles):
        polygon = _polygon(obstacle.boundary.vertices)
        obstacle_polygons.setdefault(obstacle.region_id, []).append(polygon)
        region_polygon = polygons.get(obstacle.region_id)
        if (
            region_polygon is None
            or not polygon.is_valid
            or polygon.area <= 0
            or not region_polygon.contains(polygon)
        ):
            issues.append(
                environment_issue(
                    "OBSTACLE_INVALID",
                    "geometry",
                    f"$.obstacles[{index}]",
                    f"Obstacle '{obstacle.obstacle_id}' is not validly contained in its region.",
                )
            )

    for region_id, obstacles in obstacle_polygons.items():
        for index, left in enumerate(obstacles):
            for right in obstacles[index + 1 :]:
                if left.intersection(right).area > 1e-9:
                    issues.append(
                        environment_issue(
                            "OBSTACLE_INVALID",
                            "geometry",
                            "$.obstacles",
                            f"Obstacles overlap in region '{region_id}'.",
                        )
                    )

    interaction_points = {item.interaction_point_id: item for item in home.interaction_points}
    for index, interaction in enumerate(home.interaction_points):
        point = Point(interaction.position.x, interaction.position.y)
        region_polygon = polygons.get(interaction.region_id)
        blocked = any(
            obstacle.buffer(interaction.approach_radius_meters, join_style="mitre").covers(point)
            for obstacle in obstacle_polygons.get(interaction.region_id, [])
        )
        has_clearance = region_polygon is not None and region_polygon.buffer(
            -interaction.approach_radius_meters, join_style="mitre"
        ).covers(point)
        if not has_clearance or blocked:
            issues.append(
                environment_issue(
                    "INTERACTION_POINT_INVALID",
                    "geometry",
                    f"$.interactionPoints[{index}]",
                    f"Interaction point '{interaction.interaction_point_id}' is not in free space.",
                )
            )

    graph = nx.Graph()
    graph.add_nodes_from(region.region_id for region in home.regions if region.traversable)
    for index, connection in enumerate(home.connections):
        left = polygons.get(connection.region_a_id)
        right = polygons.get(connection.region_b_id)
        portal_a = Point(connection.portal_a.x, connection.portal_a.y)
        portal_b = Point(connection.portal_b.x, connection.portal_b.y)
        local_connection_invalid = (
            connection.kind in {ConnectionKind.doorway, ConnectionKind.passage}
            and left is not None
            and right is not None
            and (
                left.distance(right) > 1e-9
                or portal_a.distance(portal_b) > connection.width_meters + 1e-9
            )
        )
        insufficient_clearance = (
            connection.width_meters + 1e-9 < home.kinematic_defaults.body_radius_meters * 2
        )
        if (
            left is None
            or right is None
            or not left.covers(portal_a)
            or not right.covers(portal_b)
            or local_connection_invalid
            or insufficient_clearance
        ):
            issues.append(
                environment_issue(
                    "CONNECTION_INVALID",
                    "topology",
                    f"$.connections[{index}]",
                    f"Connection '{connection.connection_id}' has an invalid region or portal.",
                )
            )
            continue
        if (
            regions[connection.region_a_id].traversable
            and regions[connection.region_b_id].traversable
        ):
            graph.add_edge(connection.region_a_id, connection.region_b_id)
    if graph.number_of_nodes() and not nx.is_connected(graph):
        components = [sorted(component) for component in nx.connected_components(graph)]
        issues.append(
            environment_issue(
                "TOPOLOGY_DISCONNECTED",
                "topology",
                "$.connections",
                "Traversable regions do not form one connected topology.",
                details={"components": components},
            )
        )

    for index, entity in enumerate(home.entities):
        interaction = interaction_points.get(entity.interaction_point_id or "")
        if entity.region_id not in regions or (
            entity.interaction_point_id is not None
            and (interaction is None or interaction.region_id != entity.region_id)
        ):
            issues.append(
                environment_issue(
                    "ENTITY_INVALID",
                    "compatibility",
                    f"$.entities[{index}]",
                    f"Entity '{entity.entity_id}' has inconsistent spatial references.",
                )
            )
        capabilities = [capability.capability for capability in entity.capabilities]
        if len(capabilities) != len(set(capabilities)):
            issues.append(
                environment_issue(
                    "ENTITY_INVALID",
                    "compatibility",
                    f"$.entities[{index}].capabilities",
                    f"Entity '{entity.entity_id}' repeats a capability.",
                )
            )

    for index, binding in enumerate(home.location_bindings):
        if any(region_id not in regions for region_id in binding.region_ids):
            issues.append(
                environment_issue(
                    "LOCATION_BINDING_INVALID",
                    "compatibility",
                    f"$.locationBindings[{index}].regionIds",
                    "Location binding references an unknown region.",
                )
            )
        anchor = interaction_points.get(binding.anchor_interaction_point_id)
        if anchor is None or anchor.region_id not in binding.region_ids:
            issues.append(
                environment_issue(
                    "LOCATION_BINDING_INVALID",
                    "compatibility",
                    f"$.locationBindings[{index}].anchorInteractionPointId",
                    "Location anchor must belong to one of the bound regions.",
                )
            )
    entities = {item.entity_id for item in home.entities}
    for index, binding in enumerate(home.resource_bindings):
        if binding.entity_id not in entities:
            issues.append(
                environment_issue(
                    "RESOURCE_BINDING_INVALID",
                    "compatibility",
                    f"$.resourceBindings[{index}].entityId",
                    "Resource binding references an unknown entity.",
                )
            )
    digest = canonical_sha256(home)
    return EnvironmentValidationReport.from_issues(
        _sort_issues(issues), home=home, home_sha256=digest
    )


def validate_home_file(path: Path) -> EnvironmentValidationReport:
    payload, read_issue = _read_json(path, "home model")
    if read_issue:
        return EnvironmentValidationReport.from_issues([read_issue])
    home, issues = _parse_home(payload)
    if home is None:
        return EnvironmentValidationReport.from_issues(_sort_issues(issues))
    return validate_home_model(home)


def _parse_artifact[ModelT](
    payload: Any, model: type[ModelT], artifact: str
) -> tuple[ModelT | None, list[EnvironmentValidationIssue]]:
    try:
        encoded = json.dumps(payload, separators=(",", ":"))
        return model.model_validate_json(encoded), []  # type: ignore[attr-defined]
    except ValidationError as error:
        return None, [
            environment_issue(
                "STRUCTURE_INVALID",
                "structure",
                _json_path(item["loc"]),
                f"Invalid {artifact}: {item['msg']}",
            )
            for item in error.errors(include_url=False, include_context=False, include_input=False)
        ]


def _scenario_compatibility(
    home: HomeModel, scenario: Scenario
) -> list[EnvironmentValidationIssue]:
    issues: list[EnvironmentValidationIssue] = []
    reference = scenario.model_references.home_model
    if reference.reference_id != home.home_id or reference.version != home.home_version:
        issues.append(
            environment_issue(
                "HOME_REFERENCE_MISMATCH",
                "compatibility",
                "$.modelReferences.homeModel",
                "Scenario home reference does not match the supplied home model.",
            )
        )
    locations = {item.scenario_location_id: item for item in home.location_bindings}
    for location in scenario.locations:
        if location.location_id not in locations:
            issues.append(
                environment_issue(
                    "LOCATION_BINDING_INVALID",
                    "compatibility",
                    "$.locationBindings",
                    f"Scenario location '{location.location_id}' has no concrete binding.",
                )
            )
    resources = {item.scenario_resource_id: item for item in home.resource_bindings}
    entities = {item.entity_id: item for item in home.entities}
    resident_ids = {item.resident_id for item in scenario.residents}
    for entity in home.entities:
        unknown_residents = set(entity.access.allowed_resident_ids) - resident_ids
        if unknown_residents:
            issues.append(
                environment_issue(
                    "ENTITY_INVALID",
                    "compatibility",
                    "$.entities",
                    f"Entity '{entity.entity_id}' grants access to unknown residents: "
                    f"{sorted(unknown_residents)}.",
                )
            )
    for resource in scenario.resources:
        binding = resources.get(resource.resource_id)
        if binding is None:
            issues.append(
                environment_issue(
                    "RESOURCE_BINDING_INVALID",
                    "compatibility",
                    "$.resourceBindings",
                    f"Scenario resource '{resource.resource_id}' has no concrete binding.",
                )
            )
            continue
        entity = entities.get(binding.entity_id)
        location = locations.get(resource.location_id)
        if entity is None or location is None or entity.region_id not in location.region_ids:
            issues.append(
                environment_issue(
                    "RESOURCE_BINDING_INVALID",
                    "compatibility",
                    "$.resourceBindings",
                    f"Resource '{resource.resource_id}' is bound outside its scenario location.",
                )
            )
    return issues


def _resolved_kinematics(home: HomeModel, scenario: Scenario) -> list[ResolvedKinematics]:
    result: list[ResolvedKinematics] = []
    defaults = home.kinematic_defaults
    for resident in scenario.residents:
        mobility = resident.profile.get("mobility", {})
        mobility = mobility if isinstance(mobility, dict) else {}
        profile = str(mobility.get("profile", "default"))
        raw_speed = mobility.get(
            "walkingSpeedMetersPerSecond", defaults.default_walking_speed_meters_per_second
        )
        speed = float(raw_speed) if isinstance(raw_speed, (int, float)) else 0.0
        if speed < defaults.minimum_walking_speed_meters_per_second:
            speed = defaults.minimum_walking_speed_meters_per_second
        result.append(
            ResolvedKinematics(
                resident_id=resident.resident_id,
                mobility_profile=profile,
                walking_speed_meters_per_second=speed,
                body_radius_meters=defaults.body_radius_meters,
                posture_transition_seconds=defaults.posture_transition_seconds,
            )
        )
    return result


def _resolve_expression(
    expression: Any,
    *,
    activity: Any,
    scenario: Scenario,
    day: DayPlan,
    variables: dict[str, Any],
) -> tuple[bool, Any]:
    if expression.source is ValueSource.literal:
        return True, expression.value
    if expression.source is ValueSource.activity_location:
        return True, activity.location_ids[expression.index]
    if expression.source is ValueSource.activity_resource:
        if expression.index >= len(activity.required_resources):
            return False, None
        return True, activity.required_resources[expression.index].resource_id
    if expression.source is ValueSource.activity_intent:
        return True, activity.intent
    if expression.source is ValueSource.actor:
        return True, activity.actor_id
    definition = variables.get(expression.variable_id)
    if definition is None:
        return False, None
    return _resolve_variable(definition, scenario, day, activity.actor_id)


def _entity_candidates(
    home: HomeModel,
    *,
    capability: str,
    role_value: str | None,
    actor_id: str,
    mobility_profile: str,
    preferred_regions: set[str],
    action_type: str,
) -> list[tuple[HomeEntity, Any]]:
    candidates: list[tuple[HomeEntity, Any]] = []
    for entity in home.entities:
        if (
            entity.access.allowed_resident_ids
            and actor_id not in entity.access.allowed_resident_ids
        ):
            continue
        if (
            entity.access.allowed_mobility_profiles
            and mobility_profile not in entity.access.allowed_mobility_profiles
        ):
            continue
        for provided in entity.capabilities:
            role_matches = role_value is None or role_value in provided.roles
            operation_matches = action_type in provided.supported_operations
            if provided.capability == capability and role_matches and operation_matches:
                candidates.append((entity, provided))
    return sorted(
        candidates,
        key=lambda item: (item[0].region_id not in preferred_regions, item[0].entity_id),
    )


def _build_action_bindings(
    home: HomeModel,
    scenario: Scenario,
    package: PersonalProcessPackage,
    actions: ActionCatalog,
    variables: VariableCatalog,
) -> tuple[list[ResolvedActionBinding], list[EnvironmentValidationIssue]]:
    issues: list[EnvironmentValidationIssue] = []
    result: list[ResolvedActionBinding] = []
    models = {item.process_model_id: item for item in package.process_models}
    action_definitions = {item.action_type: item for item in actions.actions}
    variable_definitions = {item.variable_id: item for item in variables.variables}
    locations = {item.scenario_location_id: item for item in home.location_bindings}
    interaction_points = {item.interaction_point_id: item for item in home.interaction_points}
    days = {day.date: day for day in scenario.days}
    mobility_profiles = {
        resident.resident_id: str(
            resident.profile.get("mobility", {}).get("profile", "default")
            if isinstance(resident.profile.get("mobility", {}), dict)
            else "default"
        )
        for resident in scenario.residents
    }
    for day in scenario.days:
        for activity in day.activities:
            matching = [
                binding
                for binding in package.bindings
                if binding.resident_id == activity.actor_id
                and binding.intent == activity.intent
                and _binding_applies(
                    binding, scenario, day, activity.actor_id, variable_definitions
                )
            ]
            if len(matching) != 1:
                issues.append(
                    environment_issue(
                        "ACTION_BINDING_UNRESOLVED",
                        "binding",
                        f"$.days[{day.date}].activities[{activity.activity_id}]",
                        "Activity does not resolve to exactly one process model.",
                    )
                )
                continue
            model = models[matching[0].process_model_id]
            preferred_regions = {
                region_id
                for location_id in activity.location_ids
                for region_id in locations[location_id].region_ids
            }
            for node in model.nodes:
                if node.kind is not ProcessNodeKind.action:
                    continue
                definition = action_definitions[node.action_type]
                resolved_arguments: dict[str, Any] = {}
                failed = False
                for name, expression in node.arguments.items():
                    present, value = _resolve_expression(
                        expression,
                        activity=activity,
                        scenario=scenario,
                        day=days[day.date],
                        variables=variable_definitions,
                    )
                    if not present:
                        failed = True
                        issues.append(
                            environment_issue(
                                "ACTION_BINDING_UNRESOLVED",
                                "binding",
                                f"$.processModels.{model.process_model_id}.{node.node_id}.arguments.{name}",
                                "Action argument cannot be resolved for this activity.",
                            )
                        )
                    else:
                        resolved_arguments[name] = value
                capability_bindings: list[ResolvedCapabilityBinding] = []
                destination_regions: list[str] = []
                destination_interaction_point_id: str | None = None
                for requirement in definition.required_capabilities:
                    role_value = (
                        str(resolved_arguments.get(requirement.parameter_name))
                        if requirement.parameter_name
                        and requirement.parameter_name in resolved_arguments
                        else None
                    )
                    if requirement.capability in {"reachable", "transport_reachable"}:
                        location = locations.get(role_value or "")
                        if location is None:
                            failed = True
                            issues.append(
                                environment_issue(
                                    "ACTION_BINDING_UNRESOLVED",
                                    "binding",
                                    f"$.processModels.{model.process_model_id}.{node.node_id}",
                                    f"Location '{role_value}' has no executable binding.",
                                )
                            )
                            continue
                        destination_regions = location.region_ids
                        destination_interaction_point_id = location.anchor_interaction_point_id
                        capability_bindings.append(
                            ResolvedCapabilityBinding(
                                role=requirement.role,
                                capability=requirement.capability,
                                provider_type="location",
                                provider_id=f"location:{role_value}",
                                interaction_point_id=location.anchor_interaction_point_id,
                            )
                        )
                        continue
                    if requirement.capability == "posture_control":
                        capability_bindings.append(
                            ResolvedCapabilityBinding(
                                role=requirement.role,
                                capability=requirement.capability,
                                provider_type="resident",
                                provider_id=activity.actor_id,
                            )
                        )
                        continue
                    candidates = _entity_candidates(
                        home,
                        capability=requirement.capability,
                        role_value=role_value,
                        actor_id=activity.actor_id,
                        mobility_profile=mobility_profiles[activity.actor_id],
                        preferred_regions=preferred_regions,
                        action_type=node.action_type,
                    )
                    if not candidates:
                        failed = True
                        issues.append(
                            environment_issue(
                                "ACTION_BINDING_UNRESOLVED",
                                "binding",
                                f"$.processModels.{model.process_model_id}.{node.node_id}",
                                f"No provider exposes capability '{requirement.capability}'"
                                + (f" for role '{role_value}'." if role_value else "."),
                            )
                        )
                        continue
                    entity, _ = candidates[0]
                    capability_bindings.append(
                        ResolvedCapabilityBinding(
                            role=requirement.role,
                            capability=requirement.capability,
                            provider_type="entity",
                            provider_id=entity.entity_id,
                            interaction_point_id=entity.interaction_point_id,
                        )
                    )
                    if entity.interaction_point_id:
                        destination_interaction_point_id = entity.interaction_point_id
                        destination_regions = [
                            interaction_points[entity.interaction_point_id].region_id
                        ]
                if not failed:
                    result.append(
                        ResolvedActionBinding(
                            source_activity_id=activity.activity_id,
                            actor_id=activity.actor_id,
                            intent=activity.intent,
                            process_model_id=model.process_model_id,
                            node_id=node.node_id,
                            action_type=node.action_type,
                            resolved_arguments=resolved_arguments,
                            capability_bindings=capability_bindings,
                            destination_region_ids=destination_regions,
                            destination_interaction_point_id=destination_interaction_point_id,
                        )
                    )
    return result, issues


def _validate_routes(
    home: HomeModel,
    scenario: Scenario,
    kinematics: list[ResolvedKinematics],
) -> tuple[int, list[EnvironmentValidationIssue]]:
    issues: list[EnvironmentValidationIssue] = []
    interactions = {item.interaction_point_id: item for item in home.interaction_points}
    bindings = sorted(home.location_bindings, key=lambda item: item.scenario_location_id)
    route_checks = 0
    # Composite scenario locations often share the same concrete anchor. Validate every
    # ordered binding pair for the public count/report, but solve identical metric routes
    # only once per resident. The cache stores the failure text as well as successful
    # outcomes so duplicate aliases preserve the exact validation semantics.
    route_outcomes: dict[tuple[object, ...], str | None] = {}
    for resident in kinematics:
        for source in bindings:
            for target in bindings:
                route_checks += 1
                start = interactions[source.anchor_interaction_point_id]
                end = interactions[target.anchor_interaction_point_id]
                route_key = (
                    resident.resident_id,
                    resident.mobility_profile,
                    resident.walking_speed_meters_per_second,
                    resident.body_radius_meters,
                    start.region_id,
                    start.position.x,
                    start.position.y,
                    end.region_id,
                    end.position.x,
                    end.position.y,
                )
                if route_key not in route_outcomes:
                    try:
                        plan_path(
                            home,
                            start_region_id=start.region_id,
                            start=start.position,
                            end_region_id=end.region_id,
                            end=end.position,
                            walking_speed_meters_per_second=(
                                resident.walking_speed_meters_per_second
                            ),
                            body_radius_meters=resident.body_radius_meters,
                            mobility_profile=resident.mobility_profile,
                        )
                        route_outcomes[route_key] = None
                    except ValueError as error:
                        route_outcomes[route_key] = str(error)
                if error_message := route_outcomes[route_key]:
                    issues.append(
                        environment_issue(
                            "PATH_UNREACHABLE",
                            "topology",
                            "$.locationBindings",
                            f"Route {source.scenario_location_id} -> "
                            f"{target.scenario_location_id} is not executable: {error_message}",
                            details={"residentId": resident.resident_id},
                        )
                    )
    return route_checks, issues


def build_bundle_files(
    scenario_path: Path,
    plan_path: Path,
    package_path: Path,
    home_path: Path,
) -> BundleBuildResult:
    inputs = [
        (scenario_path, "scenario"),
        (plan_path, "canonical plan"),
        (package_path, "behavior package"),
        (home_path, "home model"),
    ]
    payloads: list[Any] = []
    issues: list[EnvironmentValidationIssue] = []
    for path, artifact in inputs:
        payload, read_issue = _read_json(path, artifact)
        if read_issue:
            issues.append(read_issue)
        payloads.append(payload)
    if issues:
        return BundleBuildResult(
            report=EnvironmentValidationReport.from_issues(_sort_issues(issues))
        )

    scenario_report = validate_file(scenario_path)
    if not scenario_report.valid:
        return BundleBuildResult(
            report=EnvironmentValidationReport.from_issues(
                [
                    environment_issue(
                        "INPUT_SCENARIO_INVALID",
                        "compatibility",
                        "$",
                        "Source scenario is invalid.",
                    )
                ]
            )
        )
    scenario, scenario_issues = _parse_artifact(payloads[0], Scenario, "scenario")
    plan, plan_issues = _parse_artifact(payloads[1], CanonicalPlan, "canonical plan")
    package, package_issues = _parse_artifact(
        payloads[2], PersonalProcessPackage, "behavior package"
    )
    home, home_issues = _parse_home(payloads[3])
    issues.extend(scenario_issues + plan_issues + package_issues + home_issues)
    if issues or scenario is None or plan is None or package is None or home is None:
        return BundleBuildResult(
            report=EnvironmentValidationReport.from_issues(_sort_issues(issues))
        )

    home_report = validate_home_model(home)
    issues.extend(home_report.issues)
    behavior_report = validate_behavior_files(package_path, scenario_path)
    if not behavior_report.valid:
        issues.append(
            environment_issue(
                "BEHAVIOR_INVALID",
                "compatibility",
                "$",
                "Behavior package is not accepted for this scenario.",
                details={"behaviorErrorCount": behavior_report.summary.error_count},
            )
        )
    if (
        plan.source_scenario_id != scenario.scenario_id
        or plan.source_scenario_sha256 != canonical_sha256(scenario)
    ):
        issues.append(
            environment_issue(
                "PLAN_SCENARIO_MISMATCH",
                "compatibility",
                "$.canonicalPlan",
                "Canonical plan does not match the supplied scenario and digest.",
            )
        )
    elif canonical_sha256(plan) != _compiled_plan_digest(scenario.model_dump_json(by_alias=True)):
        issues.append(
            environment_issue(
                "INPUT_PLAN_INVALID",
                "compatibility",
                "$.canonicalPlan",
                "Canonical plan differs from the deterministic M2 compilation output.",
            )
        )
    issues.extend(_scenario_compatibility(home, scenario))
    if issues:
        return BundleBuildResult(
            report=EnvironmentValidationReport.from_issues(
                _sort_issues(issues), home=home, home_sha256=canonical_sha256(home)
            )
        )

    action_catalog = ActionCatalog.model_validate_json(
        default_action_catalog_path(package.catalogs.action_catalog.version).read_text()
    )
    variable_catalog = VariableCatalog.model_validate_json(
        default_variable_catalog_path().read_text()
    )
    # Loading this catalog proves that every package reference still resolves to all M3 inputs.
    default_activity_catalog_path(package.catalogs.activity_catalog.version).read_bytes()
    action_bindings, binding_issues = _build_action_bindings(
        home, scenario, package, action_catalog, variable_catalog
    )
    issues.extend(binding_issues)
    kinematics = _resolved_kinematics(home, scenario)
    route_checks, route_issues = _validate_routes(home, scenario, kinematics)
    issues.extend(route_issues)
    if issues:
        return BundleBuildResult(
            report=EnvironmentValidationReport.from_issues(
                _sort_issues(issues),
                home=home,
                home_sha256=canonical_sha256(home),
                action_binding_count=len(action_bindings),
                route_check_count=route_checks,
            )
        )
    digests = [
        ArtifactDigest(
            artifact_id=scenario.scenario_id,
            version=scenario.schema_version,
            sha256=canonical_sha256(scenario),
        ),
        ArtifactDigest(
            artifact_id=f"plan:{scenario.scenario_id}",
            version=plan.plan_version,
            sha256=canonical_sha256(plan),
        ),
        ArtifactDigest(
            artifact_id=package.package_id,
            version=package.package_version,
            sha256=canonical_sha256(package),
        ),
        ArtifactDigest(
            artifact_id=home.home_id,
            version=home.home_version,
            sha256=canonical_sha256(home),
        ),
    ]
    behavior_marker = (
        "" if package.package_version == "1.0.0" else f"__behavior_{package.package_version}"
    )
    bundle = SimulationBundle(
        bundle_id=f"{scenario.scenario_id}__{home.home_id}{behavior_marker}__1.0.0",
        seed=scenario.seed,
        scenario=scenario,
        canonical_plan=plan,
        behavior_package=package,
        home_model=home,
        digests=digests,
        resident_kinematics=kinematics,
        action_bindings=action_bindings,
    )
    bundle_digest = canonical_sha256(bundle)
    report = EnvironmentValidationReport.from_issues(
        [],
        home=home,
        home_sha256=canonical_sha256(home),
        bundle_sha256=bundle_digest,
        action_binding_count=len(action_bindings),
        route_check_count=route_checks,
    )
    return BundleBuildResult(report=report, bundle=bundle)


@lru_cache(maxsize=4)
def _compiled_plan_digest(scenario_json: str) -> str:
    scenario = Scenario.model_validate_json(scenario_json)
    result = compile_scenario(scenario)
    if result.plan is None:
        raise ValueError("accepted scenario unexpectedly failed deterministic compilation")
    return canonical_sha256(result.plan)
