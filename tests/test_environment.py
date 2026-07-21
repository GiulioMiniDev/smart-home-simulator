from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from smart_home_sim.cli import app
from smart_home_sim.domain.behavior import (
    PersonalProcessPackage,
    ValueExpression,
    ValueSource,
    VariableCatalog,
)
from smart_home_sim.domain.environment import (
    ConnectionKind,
    EnvironmentValidationReport,
    HomeConnection,
    HomeModel,
    KinematicDefaults,
    Point2D,
    Polygon2D,
    SimulationBundle,
    TraversalMode,
)
from smart_home_sim.domain.models import Scenario
from smart_home_sim.environment.navigation import plan_path
from smart_home_sim.environment.service import (
    _entity_candidates,
    _resolve_expression,
    build_bundle_files,
    validate_home_file,
    validate_home_model,
)
from smart_home_sim.formatting import format_environment_text_report

ROOT = Path(__file__).parents[1]
SCENARIO = ROOT / "examples/valid/mario_week.json"
PLAN = ROOT / "examples/compiled/mario_week.plan.json"
PACKAGE = ROOT / "examples/behavior/mario_rossi_week_2026_10_12.behavior.json"
HOME = ROOT / "examples/environment/mario_monteverde.home.json"


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def parsed_home(payload: dict[str, Any] | None = None) -> HomeModel:
    return HomeModel.model_validate_json(json.dumps(payload or load(HOME)))


def issue_codes(report: EnvironmentValidationReport) -> set[str]:
    return {issue.code for issue in report.issues}


def test_golden_home_and_bundle_are_fully_resolved_and_deterministic() -> None:
    home_report = validate_home_file(HOME)
    first = build_bundle_files(SCENARIO, PLAN, PACKAGE, HOME)
    second = build_bundle_files(SCENARIO, PLAN, PACKAGE, HOME)

    assert home_report.valid
    assert home_report.summary.region_count == 14
    assert first.report.valid and first.bundle is not None
    assert second.bundle == first.bundle
    assert first.report.summary.action_binding_count == 766
    assert first.report.summary.route_check_count == 441
    assert len(first.bundle.digests) == 4
    visualization = (ROOT / "examples/visualizations/mario_monteverde.m4-benchmark.html").read_text(
        encoding="utf-8"
    )
    assert first.report.home_sha256 is not None
    assert first.report.home_sha256[:16] in visualization
    assert first.report.home_sha256[-8:] in visualization
    assert {item.action_type for item in first.bundle.action_bindings} == {
        "activate",
        "change_posture",
        "clean",
        "close",
        "communicate",
        "consume",
        "deactivate",
        "dress",
        "enter_home",
        "exercise",
        "inspect",
        "laundry_step",
        "leave_home",
        "leisure",
        "manage_medication",
        "move_to",
        "move_to_capability",
        "open",
        "organize",
        "perform_work",
        "personal_care",
        "prepare_food",
        "put_item",
        "shop",
        "take_item",
        "travel_to",
        "wait",
    }
    distributed = SimulationBundle.model_validate_json(
        (ROOT / "examples/bundles/mario_week.simulation-bundle.json").read_text()
    )
    assert distributed == first.bundle
    tampered = distributed.model_dump(mode="json", by_alias=True)
    tampered["scenario"]["seed"] += 1
    with pytest.raises(ValidationError, match="digests"):
        SimulationBundle.model_validate_json(json.dumps(tampered))


def test_navigation_is_collision_free_deterministic_and_timestampable() -> None:
    home = parsed_home()
    path = plan_path(
        home,
        start_region_id="bedroom",
        start=Point2D(x=5.2, y=9),
        end_region_id="living_room",
        end=Point2D(x=13, y=10),
        walking_speed_meters_per_second=1.25,
        body_radius_meters=0.25,
        mobility_profile="unimpaired",
    )
    same_region = plan_path(
        home,
        start_region_id="living_room",
        start=Point2D(x=12, y=8.5),
        end_region_id="living_room",
        end=Point2D(x=19, y=9),
        walking_speed_meters_per_second=1.25,
        body_radius_meters=0.25,
        mobility_profile="unimpaired",
    )
    transport = plan_path(
        home,
        start_region_id="entrance",
        start=Point2D(x=9, y=1.2),
        end_region_id="workplace",
        end=Point2D(x=51, y=21),
        walking_speed_meters_per_second=1.25,
        body_radius_meters=0.25,
        mobility_profile="unimpaired",
    )

    assert path.duration_seconds == pytest.approx(path.distance_meters / 1.25)
    assert same_region.waypoints[0].region_id == "living_room"
    assert len(same_region.waypoints) > 2  # the table forces a visibility-graph detour
    assert any(point.traversal_mode == "transport" for point in transport.waypoints)
    assert transport.duration_seconds < transport.distance_meters / 1.25


@pytest.mark.parametrize("speed,radius", [(0, 0.2), (1.0, 0)])
def test_navigation_rejects_invalid_kinematics(speed: float, radius: float) -> None:
    with pytest.raises(ValueError, match="kinematic"):
        plan_path(
            parsed_home(),
            start_region_id="bedroom",
            start=Point2D(x=1, y=1),
            end_region_id="bedroom",
            end=Point2D(x=2, y=2),
            walking_speed_meters_per_second=speed,
            body_radius_meters=radius,
            mobility_profile="unimpaired",
        )


def test_navigation_rejects_unknown_region_and_blocked_endpoint() -> None:
    home = parsed_home()
    kwargs = {
        "home": home,
        "start_region_id": "unknown",
        "start": Point2D(x=1, y=1),
        "end_region_id": "bedroom",
        "end": Point2D(x=2, y=2),
        "walking_speed_meters_per_second": 1.0,
        "body_radius_meters": 0.25,
        "mobility_profile": "unimpaired",
    }
    with pytest.raises(ValueError, match="no route"):
        plan_path(**kwargs)
    kwargs["start_region_id"] = "living_room"
    kwargs["end_region_id"] = "living_room"
    kwargs["start"] = Point2D(x=16.5, y=8.5)
    with pytest.raises(ValueError, match="outside navigable"):
        plan_path(**kwargs)


@pytest.mark.parametrize(
    ("mutate", "start_region", "start", "end_region", "end"),
    [
        (
            lambda payload: payload["regions"][2].update({"traversable": False}),
            "bedroom",
            Point2D(x=5.2, y=9),
            "living_room",
            Point2D(x=13, y=10),
        ),
        (
            lambda payload: payload["connections"][0].update({"widthMeters": 0.4}),
            "bathroom",
            Point2D(x=5.2, y=3),
            "hallway",
            Point2D(x=9, y=6.5),
        ),
        (
            lambda payload: payload["connections"][0].update(
                {"allowedMobilityProfiles": ["wheelchair"]}
            ),
            "bathroom",
            Point2D(x=5.2, y=3),
            "hallway",
            Point2D(x=9, y=6.5),
        ),
        (
            lambda payload: payload["connections"][0].update({"bidirectional": False}),
            "hallway",
            Point2D(x=9, y=6.5),
            "bathroom",
            Point2D(x=5.2, y=3),
        ),
    ],
)
def test_navigation_enforces_traversability_clearance_access_and_direction(
    mutate: Any,
    start_region: str,
    start: Point2D,
    end_region: str,
    end: Point2D,
) -> None:
    payload = load(HOME)
    mutate(payload)
    with pytest.raises(ValueError, match="no route"):
        plan_path(
            parsed_home(payload),
            start_region_id=start_region,
            start=start,
            end_region_id=end_region,
            end=end,
            walking_speed_meters_per_second=1.0,
            body_radius_meters=0.25,
            mobility_profile="unimpaired",
        )


def test_home_contract_model_validators() -> None:
    with pytest.raises(ValidationError, match="distinct"):
        Polygon2D(vertices=[Point2D(x=0, y=0), Point2D(x=0, y=0), Point2D(x=1, y=1)])
    common = {
        "connection_id": "bad",
        "kind": ConnectionKind.transit,
        "region_a_id": "a",
        "region_b_id": "a",
        "portal_a": Point2D(x=0, y=0),
        "portal_b": Point2D(x=1, y=1),
        "width_meters": 1,
    }
    with pytest.raises(ValidationError, match="different"):
        HomeConnection(**common)
    common["region_b_id"] = "b"
    with pytest.raises(ValidationError, match="transport traversal"):
        HomeConnection(**common)
    with pytest.raises(ValidationError, match="distanceMeters"):
        HomeConnection(**common, traversal_mode=TraversalMode.transport)
    common["kind"] = ConnectionKind.doorway
    with pytest.raises(ValidationError, match="doorways"):
        HomeConnection(**common, traversal_mode=TraversalMode.transport, distance_meters=2)
    common["kind"] = ConnectionKind.passage
    with pytest.raises(ValidationError, match="passages"):
        HomeConnection(**common, traversal_mode=TraversalMode.transport, distance_meters=2)
    with pytest.raises(ValidationError, match="derive distance"):
        HomeConnection(**common, distance_meters=2)

    payload = load(HOME)
    payload["entities"][1]["initialState"].pop("active")
    with pytest.raises(ValidationError, match="initialState.active"):
        parsed_home(payload)
    payload = load(HOME)
    payload["entities"][3]["initialState"].pop("open")
    with pytest.raises(ValidationError, match="initialState.open"):
        parsed_home(payload)

    duplicate_cases = [
        ("connections", 0, "allowedMobilityProfiles", ["profile", "profile"]),
        ("locationBindings", 0, "regionIds", ["bedroom", "bedroom"]),
    ]
    for collection, index, field, value in duplicate_cases:
        payload = load(HOME)
        payload[collection][index][field] = value
        with pytest.raises(ValidationError, match="duplicates"):
            parsed_home(payload)
    payload = load(HOME)
    payload["entities"][0]["capabilities"][0]["roles"].append("bag_storage")
    with pytest.raises(ValidationError, match="duplicates"):
        parsed_home(payload)
    payload = load(HOME)
    payload["entities"][0]["capabilities"][0]["supportedOperations"] = []
    with pytest.raises(ValidationError, match="at least 1"):
        parsed_home(payload)
    payload = load(HOME)
    payload["entities"][0]["access"]["allowedResidentIds"] = ["resident", "resident"]
    with pytest.raises(ValidationError, match="duplicates"):
        parsed_home(payload)


def test_home_validation_rejects_overlapping_obstacles_and_nonlocal_doors() -> None:
    payload = load(HOME)
    duplicate_obstacle = copy.deepcopy(payload["obstacles"][0])
    duplicate_obstacle["obstacleId"] = "overlapping_bedroom_obstacle"
    payload["obstacles"].append(duplicate_obstacle)
    payload["connections"][0]["portalA"] = {"x": 5.0, "y": 3.8}
    payload["connections"][1]["widthMeters"] = 0.4
    payload["interactionPoints"][0]["approachRadiusMeters"] = 4.0

    report = validate_home_model(parsed_home(payload))

    assert {"CONNECTION_INVALID", "INTERACTION_POINT_INVALID", "OBSTACLE_INVALID"} <= issue_codes(
        report
    )
    assert any("overlap" in issue.message for issue in report.issues)


def test_geometric_and_referential_validation_reports_all_issue_families() -> None:
    payload = load(HOME)
    payload["regions"][1]["regionId"] = payload["regions"][0]["regionId"]
    payload["regions"][2]["boundary"] = payload["regions"][3]["boundary"]
    payload["obstacles"][0]["regionId"] = "unknown"
    payload["interactionPoints"][0]["position"] = {"x": 999, "y": 999}
    payload["connections"][0]["regionAId"] = "unknown"
    payload["entities"][0]["regionId"] = "unknown"
    payload["entities"][1]["capabilities"].append(
        copy.deepcopy(payload["entities"][1]["capabilities"][0])
    )
    with pytest.raises(ValidationError, match="four positive"):
        KinematicDefaults(posture_transition_seconds={})
    payload["locationBindings"][0]["regionIds"] = ["unknown"]
    payload["locationBindings"][1]["anchorInteractionPointId"] = "unknown"
    payload["resourceBindings"][0]["entityId"] = "unknown"
    report = validate_home_model(parsed_home(payload))

    assert {
        "CONNECTION_INVALID",
        "DUPLICATE_IDENTIFIER",
        "ENTITY_INVALID",
        "GEOMETRY_INVALID",
        "INTERACTION_POINT_INVALID",
        "LOCATION_BINDING_INVALID",
        "OBSTACLE_INVALID",
        "RESOURCE_BINDING_INVALID",
        "TOPOLOGY_DISCONNECTED",
    } <= issue_codes(report)


def test_home_file_parser_failures(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert issue_codes(validate_home_file(tmp_path / "missing.json")) == {"FILE_NOT_FOUND"}
    malformed = tmp_path / "malformed.json"
    malformed.write_text('{"x":', encoding="utf-8")
    assert issue_codes(validate_home_file(malformed)) == {"JSON_SYNTAX"}
    malformed.write_bytes(b"\xff")
    assert issue_codes(validate_home_file(malformed)) == {"FILE_ENCODING_ERROR"}
    write_json(malformed, [])
    assert issue_codes(validate_home_file(malformed)) == {"STRUCTURE_INVALID"}
    write_json(malformed, {"schemaVersion": "9.0.0"})
    assert issue_codes(validate_home_file(malformed)) == {"UNSUPPORTED_SCHEMA_VERSION"}
    monkeypatch.setattr("smart_home_sim.environment.service.MAX_SCENARIO_BYTES", 2)
    assert issue_codes(validate_home_file(HOME)) == {"FILE_TOO_LARGE"}


def test_bundle_preflight_and_compatibility_failures(tmp_path: Path) -> None:
    missing = build_bundle_files(tmp_path / "missing", PLAN, PACKAGE, HOME)
    assert "FILE_NOT_FOUND" in issue_codes(missing.report)

    invalid_scenario = write_json(tmp_path / "scenario.json", {})
    result = build_bundle_files(invalid_scenario, PLAN, PACKAGE, HOME)
    assert issue_codes(result.report) == {"INPUT_SCENARIO_INVALID"}

    invalid_plan = write_json(tmp_path / "plan.json", {})
    result = build_bundle_files(SCENARIO, invalid_plan, PACKAGE, HOME)
    assert issue_codes(result.report) == {"STRUCTURE_INVALID"}

    plan_payload = load(PLAN)
    plan_payload["sourceScenarioId"] = "other"
    wrong_plan = write_json(tmp_path / "wrong-plan.json", plan_payload)
    result = build_bundle_files(SCENARIO, wrong_plan, PACKAGE, HOME)
    assert "PLAN_SCENARIO_MISMATCH" in issue_codes(result.report)

    plan_payload = load(PLAN)
    plan_payload["objectiveValues"]["optionalActivityCount"] += 1
    noncanonical_plan = write_json(tmp_path / "noncanonical-plan.json", plan_payload)
    result = build_bundle_files(SCENARIO, noncanonical_plan, PACKAGE, HOME)
    assert "INPUT_PLAN_INVALID" in issue_codes(result.report)

    home_payload = load(HOME)
    home_payload["homeVersion"] = "other"
    wrong_home = write_json(tmp_path / "wrong-home.json", home_payload)
    result = build_bundle_files(SCENARIO, PLAN, PACKAGE, wrong_home)
    assert "HOME_REFERENCE_MISMATCH" in issue_codes(result.report)

    home_payload = load(HOME)
    home_payload["entities"][0]["access"]["allowedResidentIds"] = ["unknown_resident"]
    inaccessible_home = write_json(tmp_path / "unknown-access-resident.json", home_payload)
    result = build_bundle_files(SCENARIO, PLAN, PACKAGE, inaccessible_home)
    assert "ENTITY_INVALID" in issue_codes(result.report)


def test_bundle_reports_missing_scenario_and_action_bindings(tmp_path: Path) -> None:
    payload = load(HOME)
    payload["locationBindings"] = payload["locationBindings"][1:]
    payload["resourceBindings"] = payload["resourceBindings"][1:]
    path = write_json(tmp_path / "missing-bindings.json", payload)
    report = build_bundle_files(SCENARIO, PLAN, PACKAGE, path).report
    assert {"LOCATION_BINDING_INVALID", "RESOURCE_BINDING_INVALID"} <= issue_codes(report)

    payload = load(HOME)
    for entity in payload["entities"]:
        for provided in entity["capabilities"]:
            if provided["capability"] == "retail_service":
                provided["supportedOperations"] = ["not_shop"]
    path = write_json(tmp_path / "missing-capability.json", payload)
    report = build_bundle_files(SCENARIO, PLAN, PACKAGE, path).report
    assert "ACTION_BINDING_UNRESOLVED" in issue_codes(report)


def test_expression_resolution_and_candidate_access_policy() -> None:
    scenario = Scenario.model_validate_json(SCENARIO.read_text())
    package = PersonalProcessPackage.model_validate_json(PACKAGE.read_text())
    variables = VariableCatalog.model_validate_json(
        (ROOT / "src/smart_home_sim/catalogs/variable-catalog-1.0.0.json").read_text()
    )
    day = scenario.days[0]
    activity = day.activities[0]
    definitions = {item.variable_id: item for item in variables.variables}
    assert _resolve_expression(
        ValueExpression(source=ValueSource.actor),
        activity=activity,
        scenario=scenario,
        day=day,
        variables=definitions,
    ) == (True, activity.actor_id)
    missing_resource = _resolve_expression(
        ValueExpression(source=ValueSource.activity_resource, index=99),
        activity=activity,
        scenario=scenario,
        day=day,
        variables=definitions,
    )
    assert missing_resource == (False, None)
    assert package.process_models

    home = parsed_home()
    candidates = _entity_candidates(
        home,
        capability="food_preparation",
        role_value=None,
        actor_id="resident_mario_rossi",
        mobility_profile="unimpaired",
        preferred_regions={"kitchen"},
        action_type="prepare_food",
    )
    assert candidates[0][0].entity_id == "kitchen_workstation"


def test_environment_cli_success_failure_and_atomic_bundle_output(tmp_path: Path) -> None:
    runner = CliRunner()
    valid = runner.invoke(app, ["validate-home", str(HOME)])
    invalid = runner.invoke(app, ["validate-home", str(tmp_path / "missing")])
    bundle = tmp_path / "bundle.json"
    report = tmp_path / "report.json"
    built = runner.invoke(
        app,
        [
            "build-simulation-bundle",
            str(SCENARIO),
            str(PLAN),
            str(PACKAGE),
            str(HOME),
            "--output",
            str(bundle),
            "--report-output",
            str(report),
        ],
    )

    assert valid.exit_code == 0 and "VALID" in valid.stdout
    assert invalid.exit_code == 1 and "FILE_NOT_FOUND" in invalid.stdout
    assert built.exit_code == 0
    assert bundle.exists() and report.exists()
    assert SimulationBundle.model_validate_json(bundle.read_text())


def test_environment_report_text_and_empty_factory() -> None:
    report = EnvironmentValidationReport.from_issues([])
    assert report.valid
    assert "unknown home" in format_environment_text_report(report)
