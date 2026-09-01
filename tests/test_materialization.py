from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from shapely.geometry import Polygon as ShapelyPolygon
from shapely.ops import unary_union
from typer.testing import CliRunner

from smart_home_sim.behavior.service import (
    default_action_catalog_path,
    default_variable_catalog_path,
)
from smart_home_sim.cli import app
from smart_home_sim.compiler import CompilationResult, compile_scenario
from smart_home_sim.compiler.service import canonical_sha256
from smart_home_sim.domain.behavior import (
    ActionCatalog,
    PersonalProcessPackage,
    ProcessEdge,
    ValueExpression,
    ValueSource,
    VariableCatalog,
)
from smart_home_sim.domain.environment import (
    ConnectionKind,
    HomeModel,
    HomeRegion,
    InteractionPoint,
    Point2D,
    Polygon2D,
    RegionKind,
    SimulationBundle,
)
from smart_home_sim.domain.execution import ExecutionTrace
from smart_home_sim.domain.materialization import (
    EnvironmentMaterializationManifest,
    HomeGenerationPolicy,
    HomeGenerationReport,
    SensorDeploymentPolicy,
    SensorDeploymentReport,
    SyntheticWorkspaceManifest,
    WorkspaceArtifact,
)
from smart_home_sim.domain.models import Location, LocationKind, Resource, Scenario
from smart_home_sim.domain.sensors import (
    ContactSensor,
    ObservableSensorLog,
    OracleMapping,
    PirSensor,
    SensorModel,
    TemperatureSensor,
)
from smart_home_sim.environment import service as environment_service
from smart_home_sim.environment import validate_home_model
from smart_home_sim.environment.navigation import plan_path
from smart_home_sim.materialization import (
    bind_sensor_model,
    deploy_sensors,
    floorplan,
    generate_home,
    materialize_environment,
    materialize_workspace,
)
from smart_home_sim.materialization.service import (
    _functional_zones,
    _stair_pose,
    load_home_policy,
    load_sensor_policy,
    load_source_models,
)
from smart_home_sim.sensors import project_sensors
from smart_home_sim.simulation import simulate_bundle

ROOT = Path(__file__).parents[1]
SOURCE = ROOT / "generated/mario_rossi_2026_10_30_ingested"
GOLDEN = ROOT / "examples/materialization/mario_rossi_2026_10_30"


def source_models() -> tuple[Scenario, PersonalProcessPackage]:
    return load_source_models(SOURCE / "scenario.json", SOURCE / "personal-process-package.json")


def golden_model[ModelT](name: str, model: type[ModelT]) -> ModelT:
    return model.model_validate_json((GOLDEN / name).read_text(encoding="utf-8"))  # type: ignore[attr-defined]


def test_home_generation_is_valid_deterministic_and_matches_golden() -> None:
    scenario, package = source_models()
    first = generate_home(scenario, package)
    second = generate_home(scenario, package, HomeGenerationPolicy())
    golden = golden_model("home-model.json", HomeModel)

    assert first == second
    assert first.home == golden
    assert first.report.success
    assert first.report.home_sha256 == canonical_sha256(golden)
    assert first.report.summary.region_count == 9
    assert first.report.summary.entity_count == 27
    assert first.report.summary.resource_binding_count == 17
    assert any(entity.entity_id == "entrance_door" for entity in golden.entities)
    points_by_id = {item.interaction_point_id: item for item in golden.interaction_points}
    resource_points = [
        points_by_id[entity.interaction_point_id].position
        for entity in golden.entities
        if entity.entity_id in {binding.entity_id for binding in golden.resource_bindings}
    ]
    assert len({(point.x, point.y) for point in resource_points}) > len(golden.regions)
    assert validate_home_model(golden).valid


def test_home_generation_rejects_incompatible_or_empty_sources() -> None:
    scenario, package = source_models()
    mismatch = package.model_copy(update={"source_scenario_id": "different"})
    mismatch_result = generate_home(scenario, mismatch)
    assert mismatch_result.home is None
    assert mismatch_result.report.issues[0].code == "BEHAVIOR_SCENARIO_MISMATCH"

    composite_only = scenario.model_copy(
        update={
            "locations": [
                Location(
                    location_id="composite",
                    kind=LocationKind.composite,
                    member_location_ids=["missing"],
                )
            ]
        }
    )
    empty_result = generate_home(composite_only, package)
    assert empty_result.home is None
    assert empty_result.report.issues[0].code == "NO_PRIMITIVE_LOCATION"


# Contact counts follow the furniture, not the script: every container is instrumented whether or
# not the authored behaviour ever opens it, so this golden home yields five rather than the three
# its process models happen to touch.
@pytest.mark.parametrize(
    ("preset", "expected_pir", "expected_contact", "expected_temperature"),
    [("minimal", 1, 1, 1), ("room_coverage", 6, 5, 6), ("dense", 12, 5, 6)],
)
def test_sensor_deployment_presets_are_valid_and_projectable(
    preset: str, expected_pir: int, expected_contact: int, expected_temperature: int
) -> None:
    bundle = golden_model("simulation-bundle.json", SimulationBundle)
    policy = SensorDeploymentPolicy(preset=preset)
    first = deploy_sensors(bundle, policy)
    second = deploy_sensors(bundle, policy)

    assert first == second
    assert first.sensor_model is not None
    assert first.report.summary.pir_count == expected_pir
    assert first.report.summary.contact_count == expected_contact
    assert first.report.summary.temperature_count == expected_temperature
    assert set(first.sensor_model.region_ids) == {
        item.region_id for item in bundle.home_model.regions
    }
    assert set(first.sensor_model.entity_ids) == {
        item.entity_id for item in bundle.home_model.entities
    }
    if preset == "room_coverage":
        assert first.sensor_model == golden_model("sensor-model.json", SensorModel)
        trace = simulate_bundle(bundle).trace
        assert trace is not None
        projection = project_sensors(trace, bundle, first.sensor_model)
        assert projection.report.success
        assert projection.report.projection_policy_version == "event-driven-sensors-1.1.0"
        assert projection.observable_log is not None
        assert projection.oracle_mapping is not None
        records_by_type = Counter(item.sensor_type for item in projection.observable_log.records)
        assert records_by_type["pir"] > 1_000
        assert records_by_type["temperature"] > 1_000
        assert records_by_type["contact"] > 0
        assert all(
            float(item.value) * 2 == round(float(item.value) * 2)
            for item in projection.observable_log.records
            if item.sensor_type == "temperature"
        )
        pir_observation_ids = {
            record.observation_id
            for record in projection.observable_log.records
            if record.sensor_type == "pir"
        }
        pir_causes = {
            item.cause_type
            for item in projection.oracle_mapping.links
            if item.observation_id in pir_observation_ids
        }
        assert {"movement", "action_execution"} <= pir_causes


def test_realistic_sensor_profile_is_deterministic_and_state_coherent() -> None:
    bundle = golden_model("simulation-bundle.json", SimulationBundle)
    policy = SensorDeploymentPolicy.realistic()
    first = deploy_sensors(bundle, policy)
    second = deploy_sensors(bundle, policy)

    assert first == second
    assert first.sensor_model is not None
    assert first.sensor_model.sensor_model_version == "1.2.0"
    pir = [item for item in first.sensor_model.sensors if isinstance(item, PirSensor)]
    contacts = [item for item in first.sensor_model.sensors if isinstance(item, ContactSensor)]
    temperatures = [
        item for item in first.sensor_model.sensors if isinstance(item, TemperatureSensor)
    ]
    assert all(item.hold_log_sigma > 0 for item in pir)
    assert all(item.pulse_log_sigma > 0 for item in contacts)
    assert all(item.climate_profile == "city_seasonal" for item in temperatures)
    assert len({item.sample_phase_seconds for item in temperatures}) == len(temperatures)

    trace = simulate_bundle(bundle).trace
    assert trace is not None
    projection = project_sensors(trace, bundle, first.sensor_model)
    assert projection.report.success
    assert projection.report.projection_policy_version == "event-driven-sensors-1.2.0"
    assert projection.observable_log is not None
    binary_states: dict[tuple[str, object], set[object]] = {}
    for record in projection.observable_log.records:
        if record.sensor_type in {"pir", "contact"}:
            binary_states.setdefault((record.sensor_id, record.observed_at), set()).add(
                record.value
            )
    assert all(len(values) == 1 for values in binary_states.values())
    assert projection.report.summary.noisy_observation_count > 0


def test_generated_bindings_use_physical_interaction_targets() -> None:
    bundle = golden_model("simulation-bundle.json", SimulationBundle)
    providers_by_action = {
        action_type: {
            capability.provider_id
            for binding in bundle.action_bindings
            if binding.action_type == action_type
            for capability in binding.capability_bindings
        }
        for action_type in {"open", "close", "enter_home", "leave_home"}
    }

    assert providers_by_action["open"] == {
        "refrigerator",
        "medication_cleaning_cabinet",
    }
    assert providers_by_action["close"] == providers_by_action["open"]
    assert providers_by_action["enter_home"] == {"entrance_door"}
    assert providers_by_action["leave_home"] == {"entrance_door"}


def test_a_hygiene_activity_washes_in_the_bathroom_rather_than_the_kitchen() -> None:
    """A washbasin answers for a tap, so a bathroom activity never resolves into the kitchen.

    `sink_faucet` and `sink` used to be declared by the kitchen sink alone. Nothing was formally
    wrong with that — the role existed and resolved, so the compilation report had nothing to say —
    but it made the kitchen sink the only object in the flat that could answer "turn the tap on",
    and every hygiene process that asks for one walked the resident out of the bathroom to do it.
    On a generated year that was 150 of 1069 movements inside hygiene activities, and the trace
    then left her standing at the kitchen sink for the rest of the night.

    The check is on the resolved bundle rather than on the table, because the table is only half
    the mechanism: `_entity_candidates` prefers the activity's own regions, and it is the two
    together that keep the wash in the bathroom while `clean_kitchen` still gets the kitchen sink.
    """
    bundle = golden_model("simulation-bundle.json", SimulationBundle)
    regions = {entity.entity_id: entity.region_id for entity in bundle.home_model.entities}
    activities = {
        activity.activity_id: activity
        for day in bundle.scenario.days
        for activity in day.activities
    }
    hygiene = {
        "morning_toilet_and_wash",
        "morning_toilet_and_shower",
        "evening_hygiene",
        "use_toilet",
    }

    elsewhere = [
        (activities[binding.source_activity_id].intent, binding.node_id, capability.provider_id)
        for binding in bundle.action_bindings
        if binding.source_activity_id in activities
        and activities[binding.source_activity_id].intent in hygiene
        and activities[binding.source_activity_id].location_ids == ["bathroom"]
        for capability in binding.capability_bindings
        if regions.get(capability.provider_id) not in {None, "bathroom"}
    ]
    assert not elsewhere

    washbasin = next(item for item in bundle.home_model.entities if item.entity_type == "washbasin")
    roles = {role for capability in washbasin.capabilities for role in capability.roles}
    assert {"sink", "sink_faucet", "washing_area"} <= roles
    # What a washbasin is not: the kitchen keeps the roles that belong to a kitchen.
    assert not {"food_preparation_area", "drinking_water_source"} & roles


def test_an_action_happens_at_the_fixture_the_process_walked_to() -> None:
    """An action performed on nothing in particular happens where the process last put the body.

    `personal_care` names a procedure, not an object, so the binder had only the capability
    `personal_care_support` to choose by and took the first candidate by entity id. In a bathroom
    holding a toilet, a washbasin and a shower that is the shower every time — and because binding a
    provider also means walking to it, the resident who had just crossed to the toilet was walked
    back out to the shower to use it. Every hygiene action in the home was attributed to the shower:
    32 of 32 on a generated horizon.
    """
    bundle = golden_model("simulation-bundle.json", SimulationBundle)
    models = {item.process_model_id: item for item in bundle.behavior_package.process_models}
    order = {
        model_id: {node.node_id: index for index, node in enumerate(model.nodes)}
        for model_id, model in models.items()
    }
    by_activity: dict[str, list[Any]] = defaultdict(list)
    for binding in bundle.action_bindings:
        by_activity[binding.source_activity_id].append(binding)

    checked = 0
    for bindings in by_activity.values():
        positions = order[bindings[0].process_model_id]
        approached: str | None = None
        for binding in sorted(bindings, key=lambda item: positions[item.node_id]):
            providers = [
                item.provider_id
                for item in binding.capability_bindings
                if item.provider_type == "entity"
            ]
            if binding.action_type == "move_to_capability":
                approached = providers[0] if providers else None
            elif binding.action_type == "move_to":
                approached = None
            elif binding.action_type == "personal_care" and approached is not None:
                assert providers == [approached], (
                    f"{binding.source_activity_id}/{binding.node_id} walked to {approached} "
                    f"and then performed on {providers}"
                )
                checked += 1
    assert checked


def test_eating_happens_at_the_table_rather_than_at_the_refrigerator() -> None:
    """Binding the thing an action is performed *with* must not move the resident to it.

    `consume` binds whatever holds the food, and binding a provider is also an instruction to walk
    there, so a resident who had just sat down at the table was walked back to the refrigerator to
    eat: 3.2 metres, seated, three times a day. The provider is still the refrigerator — that is
    where the meal came from — but an `item` no longer carries the body with it.
    """
    bundle = golden_model("simulation-bundle.json", SimulationBundle)
    eating = [item for item in bundle.action_bindings if item.action_type == "consume"]

    assert eating
    assert all(item.destination_interaction_point_id is None for item in eating)
    assert all(item.capability_bindings for item in eating)


def test_a_posture_change_is_written_to_the_trace_once() -> None:
    """`change_posture` had two writers, and the trace carried both.

    The engine set the runtime field and recorded a transition; the catalog also declares
    `resident.posture := {posture}`, and the generic effect loop recorded a second one. Two ids, one
    moment, one cause — ten of ten posture changes on a generated day, so anything counting how
    often the resident sat down got double. The pair also disagreed about where she had come from,
    the fact store never having been told her opening posture: the first read `null -> lying` for a
    resident who had been in bed since midnight.
    """
    trace = golden_model("execution-trace.json", ExecutionTrace)
    postures = [
        item
        for item in trace.state_transitions
        if item.subject_type == "resident" and item.fact == "posture"
    ]

    assert postures
    moments = Counter((item.at, item.subject_id) for item in postures)
    assert not [key for key, count in moments.items() if count > 1]
    # And the first one knows what it came from, rather than reporting an empty history.
    assert postures[0].previous_value is not None


def test_workspace_is_transactional_replayable_and_self_verifying(tmp_path: Path) -> None:
    first_path = tmp_path / "first"
    second_path = tmp_path / "second"
    first = materialize_workspace(
        SOURCE / "scenario.json",
        SOURCE / "personal-process-package.json",
        first_path,
    )
    second = materialize_workspace(
        SOURCE / "scenario.json",
        SOURCE / "personal-process-package.json",
        second_path,
    )

    assert first == second
    assert first == SyntheticWorkspaceManifest.model_validate_json(
        (first_path / "workspace-manifest.json").read_text(encoding="utf-8")
    )
    assert len(first.artifacts) == 18
    # A run says on the record whether it executed a generated plan or one a researcher approved.
    assert json.loads((first_path / "plan-approval.json").read_text(encoding="utf-8")) == {
        "schemaVersion": "1.0.0",
        "documentType": "plan_approval",
        "homeModel": "generated",
        "sensorModel": "generated",
        "homeSha256": canonical_sha256(
            json.loads((first_path / "home-model.json").read_text(encoding="utf-8"))
        ),
        "sensorModelSha256": canonical_sha256(
            json.loads((first_path / "sensor-model.json").read_text(encoding="utf-8"))
        ),
    }
    for artifact in first.artifacts:
        payload = json.loads((first_path / artifact.relative_path).read_text(encoding="utf-8"))
        assert artifact.sha256 == canonical_sha256(payload)
        assert (first_path / artifact.relative_path).read_bytes() == (
            second_path / artifact.relative_path
        ).read_bytes()
    with pytest.raises(FileExistsError):
        materialize_workspace(
            SOURCE / "scenario.json",
            SOURCE / "personal-process-package.json",
            first_path,
        )


def test_workspace_removes_staging_directory_after_failure(tmp_path: Path) -> None:
    package = json.loads((SOURCE / "personal-process-package.json").read_text(encoding="utf-8"))
    package["sourceScenarioId"] = "wrong"
    invalid_package = tmp_path / "invalid-package.json"
    invalid_package.write_text(json.dumps(package), encoding="utf-8")
    output = tmp_path / "failed"

    with pytest.raises(RuntimeError, match="home generation failed"):
        materialize_workspace(SOURCE / "scenario.json", invalid_package, output)
    assert not output.exists()
    assert not list(tmp_path.glob(".failed.*"))


def test_policy_loading_and_contract_invariants(tmp_path: Path) -> None:
    home_path = tmp_path / "home-policy.json"
    sensor_path = tmp_path / "sensor-policy.json"
    home_path.write_text(HomeGenerationPolicy().model_dump_json(by_alias=True), encoding="utf-8")
    sensor_path.write_text(
        SensorDeploymentPolicy(preset="dense").model_dump_json(by_alias=True),
        encoding="utf-8",
    )
    assert load_home_policy(None) == HomeGenerationPolicy()
    assert load_home_policy(home_path) == HomeGenerationPolicy()
    assert load_sensor_policy(None) == SensorDeploymentPolicy.realistic()
    assert load_sensor_policy(sensor_path).preset == "dense"
    with pytest.raises(ValidationError):
        HomeGenerationPolicy(room_width_meters=1)
    with pytest.raises(ValidationError):
        SensorDeploymentPolicy(dropout_probability=2)
    with pytest.raises(ValidationError):
        HomeGenerationReport.model_validate(
            {
                **golden_model("home-generation-report.json", HomeGenerationReport).model_dump(),
                "success": False,
            }
        )
    with pytest.raises(ValidationError):
        SensorDeploymentReport.model_validate(
            {
                **golden_model(
                    "sensor-deployment-report.json", SensorDeploymentReport
                ).model_dump(),
                "sensor_model_sha256": None,
            }
        )


def test_materialization_cli_commands(tmp_path: Path) -> None:
    runner = CliRunner()
    home = tmp_path / "home.json"
    home_report = tmp_path / "home-report.json"
    generated = runner.invoke(
        app,
        [
            "generate-home",
            str(SOURCE / "scenario.json"),
            str(SOURCE / "personal-process-package.json"),
            "--output",
            str(home),
            "--report-output",
            str(home_report),
        ],
    )
    assert generated.exit_code == 0, generated.output
    assert HomeGenerationReport.model_validate_json(home_report.read_text()).success

    sensor = tmp_path / "sensor.json"
    sensor_report = tmp_path / "sensor-report.json"
    deployed = runner.invoke(
        app,
        [
            "deploy-sensors",
            str(GOLDEN / "simulation-bundle.json"),
            "--output",
            str(sensor),
            "--report-output",
            str(sensor_report),
        ],
    )
    assert deployed.exit_code == 0, deployed.output
    assert SensorDeploymentReport.model_validate_json(sensor_report.read_text()).success

    workspace = tmp_path / "workspace"
    run = runner.invoke(
        app,
        [
            "run-synthetic",
            str(SOURCE / "scenario.json"),
            str(SOURCE / "personal-process-package.json"),
            "--output-dir",
            str(workspace),
        ],
    )
    assert run.exit_code == 0, run.output
    assert "18 verified artifacts" in run.output
    repeated = runner.invoke(
        app,
        [
            "run-synthetic",
            str(SOURCE / "scenario.json"),
            str(SOURCE / "personal-process-package.json"),
            "--output-dir",
            str(workspace),
        ],
    )
    assert repeated.exit_code == 2


def test_the_way_out_of_the_flat_starts_where_the_front_door_is() -> None:
    """Door and exit route are anchored to the same room, and that point is walkable.

    They used to coincide only because both defaulted to the first room in the scenario. Once the
    door moved to a circulation space the transit links stayed behind, so the resident left the
    flat through the bedroom while the entrance sat in the hall, on no route at all.
    """
    from shapely.geometry import Point as ShapelyPoint
    from shapely.geometry import Polygon as ShapelyPolygon

    scenario, package = source_models()
    home = generate_home(scenario, package, HomeGenerationPolicy()).home
    assert home is not None

    door = next(item for item in home.entities if item.entity_id == "entrance_door")
    points = {item.interaction_point_id: item for item in home.interaction_points}
    door_point = points[door.interaction_point_id]
    assert door_point.region_id == door.region_id

    exits = [item for item in home.connections if item.kind is not ConnectionKind.doorway]
    assert exits, "the flat has no way out at all"
    for connection in exits:
        assert connection.region_a_id == door.region_id, (
            f"exit to {connection.region_b_id} leaves from {connection.region_a_id}, "
            f"but the front door is in {door.region_id}"
        )

    # The portal has to be reachable: a point inside the sofa is not a way out.
    region = next(item for item in home.regions if item.region_id == door.region_id)
    shell = ShapelyPolygon([(point.x, point.y) for point in region.boundary.vertices])
    blocking = [
        ShapelyPolygon([(point.x, point.y) for point in obstacle.boundary.vertices])
        for obstacle in home.obstacles
        if obstacle.region_id == door.region_id
    ]
    for probe in (door_point.position, exits[0].portal_a):
        point = ShapelyPoint(probe.x, probe.y)
        assert shell.buffer(-door_point.approach_radius_meters).covers(point)
        assert not any(
            item.buffer(door_point.approach_radius_meters).covers(point) for item in blocking
        )


def test_the_ideal_profile_deploys_no_failures_and_the_realistic_one_does() -> None:
    """A generated deployment used to be immortal: 244 healthy days out of 244.

    The projector has always silenced a sensor inside a declared failure window; nothing ever
    declared one. `ideal` keeps that behaviour, because the frozen examples are compared byte for
    byte and a study that wants clean data should be able to ask for it.
    """
    bundle = golden_model("simulation-bundle.json", SimulationBundle)

    ideal = deploy_sensors(bundle, SensorDeploymentPolicy(preset="room_coverage"))
    assert ideal.sensor_model is not None
    assert all(not sensor.failure_windows for sensor in ideal.sensor_model.sensors)

    realistic = deploy_sensors(bundle, SensorDeploymentPolicy.realistic())
    repeated = deploy_sensors(bundle, SensorDeploymentPolicy.realistic())
    assert realistic.sensor_model is not None
    assert realistic == repeated

    window = bundle.scenario.simulation_window
    for sensor in realistic.sensor_model.sensors:
        for outage in sensor.failure_windows:
            assert window.start <= outage.starts_at < outage.ends_at <= window.end
        # The contract refuses overlaps, so the merge has to hold on every draw.
        starts = [item.starts_at for item in sensor.failure_windows]
        assert starts == sorted(starts)


def test_outage_counts_and_durations_are_drawn_rather_than_rounded() -> None:
    """Replacing perfect health with perfectly uniform faults would be its own tell.

    Rounding the rate gave every sensor of an eight-month horizon exactly four outages of exactly
    five hours. Counts are Poisson and durations spread, so some nodes stay lucky and some lose a
    weekend.
    """
    from datetime import UTC, datetime, timedelta

    from smart_home_sim.materialization.service import _failure_windows

    policy = SensorDeploymentPolicy.realistic()
    start = datetime(2026, 8, 4, tzinfo=UTC)
    end = start + timedelta(days=243)
    identifiers = [f"pir_room_{index}" for index in range(12)]

    per_sensor = [
        _failure_windows(name, seed=1, policy=policy, start=start, end=end) for name in identifiers
    ]
    counts = {len(windows) for windows in per_sensor}
    durations = {
        round((item.ends_at - item.starts_at).total_seconds() / 3600, 1)
        for windows in per_sensor
        for item in windows
        if item.ends_at != end
    }

    assert len(counts) > 1, f"every sensor drew the same number of outages: {counts}"
    assert len(durations) > 1, "every outage lasted exactly as long as every other"


def test_functional_zones_split_a_room_where_room_coverage_cannot() -> None:
    """One sensor per room reports every activity of that room as the same event.

    The room where the resident spends her day then swallows the log: on one eight-month horizon
    the single kitchen sensor produced 67.3% of all observations while the balcony managed 0.3 a
    day. Adding sensors alone does not help — `dense` gives each of them the whole room as
    coverage, so they report the same thing twice. Restricted coverage is what makes two sensors
    in one room say different things.
    """
    bundle = golden_model("simulation-bundle.json", SimulationBundle)

    rooms = deploy_sensors(bundle, SensorDeploymentPolicy(preset="room_coverage"))
    dense = deploy_sensors(bundle, SensorDeploymentPolicy(preset="dense"))
    zones = deploy_sensors(bundle, SensorDeploymentPolicy(preset="functional_zones"))
    assert zones.sensor_model is not None
    assert rooms.sensor_model is not None
    assert dense.sensor_model is not None

    def coverage_area(result: Any) -> float:
        areas = []
        for sensor in result.sensor_model.sensors:
            if sensor.sensor_type != "pir":
                continue
            xs = [vertex.x for vertex in sensor.coverage.vertices]
            ys = [vertex.y for vertex in sensor.coverage.vertices]
            areas.append((max(xs) - min(xs)) * (max(ys) - min(ys)))
        return sum(areas) / len(areas)

    # `dense` doubles the sensors without narrowing what any of them sees.
    assert coverage_area(dense) == pytest.approx(coverage_area(rooms))
    assert coverage_area(zones) < coverage_area(rooms)

    # Every interaction point still belongs to exactly one sensor: a zone nobody covers is an
    # activity that stopped being observed.
    by_region: dict[str, list[Any]] = defaultdict(list)
    for sensor in zones.sensor_model.sensors:
        if sensor.sensor_type == "pir":
            by_region[sensor.region_ids[0]].append(sensor)
    for point in bundle.home_model.interaction_points:
        covering = [
            sensor
            for sensor in by_region.get(point.region_id, [])
            if _covers(sensor.coverage, point.position)
        ]
        if by_region.get(point.region_id):
            assert covering, f"{point.interaction_point_id} is covered by no sensor"


def _covers(coverage: Any, position: Any) -> bool:
    xs = [vertex.x for vertex in coverage.vertices]
    ys = [vertex.y for vertex in coverage.vertices]
    return min(xs) <= position.x <= max(xs) and min(ys) <= position.y <= max(ys)


def test_a_run_executes_the_plan_the_researcher_approved(tmp_path: Path) -> None:
    """An approved home and field replace the policy step instead of being regenerated over.

    Without this the plan editor is decoration: the researcher moves the bed, presses run, and the
    deterministic generator quietly rebuilds the room it was in. The approved models are still
    judged by the same M4 and M6 gates — they are inputs, not exemptions.
    """
    scenario, package = source_models()
    recommended = generate_home(scenario, package).home
    assert recommended is not None
    # Five centimetres, not twenty. The generator no longer leaves half a metre of slack beside
    # every object — a bathroom is now arranged as a bathroom, with the shower, the toilet and the
    # basin in one run — so a twenty-centimetre shove lands the first obstacle inside its neighbour
    # and the M4 gate rejects it, which is the gate working. What is under test here is that an
    # approved edit is carried through instead of being regenerated over, and a nudge is a nudge.
    approved = recommended.model_copy(
        update={
            "obstacles": [
                recommended.obstacles[0].model_copy(
                    update={
                        "boundary": Polygon2D(
                            vertices=[
                                Point2D(x=point.x + 0.05, y=point.y)
                                for point in recommended.obstacles[0].boundary.vertices
                            ]
                        )
                    }
                ),
                *recommended.obstacles[1:],
            ]
        }
    )

    manifest = materialize_workspace(
        SOURCE / "scenario.json",
        SOURCE / "personal-process-package.json",
        tmp_path / "approved",
        approved_home=approved,
    )

    executed = HomeModel.model_validate_json(
        (tmp_path / "approved/home-model.json").read_text(encoding="utf-8")
    )
    assert executed == approved
    assert executed != recommended
    approval = json.loads((tmp_path / "approved/plan-approval.json").read_text(encoding="utf-8"))
    assert approval["homeModel"] == "researcher_approved"
    assert approval["sensorModel"] == "generated"
    assert approval["homeSha256"] == canonical_sha256(approved)
    # Nothing generated this plan, so the run publishes no generation report claiming it did.
    assert {item.role for item in manifest.artifacts} & {"home_report"} == set()
    assert not (tmp_path / "approved/home-generation-report.json").exists()


def test_an_approved_sensor_field_is_installed_rather_than_redeployed(tmp_path: Path) -> None:
    bundle = golden_model("simulation-bundle.json", SimulationBundle)
    field = deploy_sensors(bundle, SensorDeploymentPolicy(preset="room_coverage")).sensor_model
    assert field is not None
    # The researcher keeps one PIR and widens nothing else: a deployment no preset would produce.
    approved = field.model_copy(
        update={"sensors": [item for item in field.sensors if item.sensor_type != "pir"][:2]}
    )

    bound = bind_sensor_model(approved, bundle)

    assert [item.sensor_id for item in bound.sensors] == [
        item.sensor_id for item in approved.sensors
    ]
    assert bound.source_bundle_id == bundle.bundle_id
    assert bound.source_bundle_sha256 == canonical_sha256(bundle)
    assert bound.seed == bundle.seed


def test_the_environment_alone_is_what_a_full_run_would_have_built(tmp_path: Path) -> None:
    """Stopping before execution must not change what the plan and the sensor field are.

    The whole value of building the environment first is that the researcher reviews the models a
    run will execute. If the two paths could diverge, approving a plan here would mean approving
    something else than what runs — so the same bytes are the contract between them.
    """
    environment_path = tmp_path / "environment"
    complete_path = tmp_path / "complete"
    manifest = materialize_environment(
        SOURCE / "scenario.json",
        SOURCE / "personal-process-package.json",
        environment_path,
    )
    complete = materialize_workspace(
        SOURCE / "scenario.json",
        SOURCE / "personal-process-package.json",
        complete_path,
    )

    assert manifest.executed is False
    assert manifest == EnvironmentMaterializationManifest.model_validate_json(
        (environment_path / "environment-manifest.json").read_text(encoding="utf-8")
    )
    shared = {item.relative_path for item in manifest.artifacts}
    assert shared == {item.relative_path for item in complete.artifacts} - {
        "simulation-report.json",
        "execution-trace.json",
        "sensor-projection-report.json",
        "observable-sensor-log.json",
        "oracle-mapping.json",
    }
    for relative_path in shared:
        assert (environment_path / relative_path).read_bytes() == (
            complete_path / relative_path
        ).read_bytes()
    # Nothing was executed, so nothing that describes an execution exists.
    for absent in ("execution-trace.json", "observable-sensor-log.json", "oracle-mapping.json"):
        assert not (environment_path / absent).exists()
    with pytest.raises(FileExistsError):
        materialize_environment(
            SOURCE / "scenario.json",
            SOURCE / "personal-process-package.json",
            environment_path,
        )


def test_an_environment_manifest_cannot_claim_execution_evidence() -> None:
    with pytest.raises(ValidationError, match="must not publish execution evidence"):
        EnvironmentMaterializationManifest(
            scenario_id="scenario",
            bundle_id="bundle",
            home_id="home",
            sensor_model_id="sensors",
            artifacts=[
                WorkspaceArtifact(
                    role="execution_trace",
                    relative_path="execution-trace.json",
                    sha256="a" * 64,
                )
            ],
        )


def test_building_the_environment_reports_progress_and_removes_staging_on_failure(
    tmp_path: Path,
) -> None:
    seen: list[tuple[str, float]] = []
    materialize_environment(
        SOURCE / "scenario.json",
        SOURCE / "personal-process-package.json",
        tmp_path / "watched",
        progress=lambda phase, percent, message, counters: seen.append((phase, percent)),
    )
    # The environment is the whole job, so its bar reaches the end instead of stopping at half.
    assert [phase for phase, _ in seen] == [
        "input",
        "compilation",
        "home",
        "binding",
        "sensors",
        "completed",
    ]
    assert seen[-1][1] == 100
    assert all(previous[1] <= current[1] for previous, current in zip(seen, seen[1:], strict=False))

    package = json.loads((SOURCE / "personal-process-package.json").read_text(encoding="utf-8"))
    package["sourceScenarioId"] = "wrong"
    invalid_package = tmp_path / "invalid-package.json"
    invalid_package.write_text(json.dumps(package), encoding="utf-8")
    with pytest.raises(RuntimeError, match="home generation failed"):
        materialize_environment(SOURCE / "scenario.json", invalid_package, tmp_path / "failed")
    assert not (tmp_path / "failed").exists()
    assert not list(tmp_path.glob(".failed.*"))


def test_a_cancelled_environment_build_publishes_nothing(tmp_path: Path) -> None:
    with pytest.raises(InterruptedError):
        materialize_environment(
            SOURCE / "scenario.json",
            SOURCE / "personal-process-package.json",
            tmp_path / "cancelled",
            progress=lambda *_: None,
            cancelled=lambda: True,
        )
    assert not (tmp_path / "cancelled").exists()


def test_the_projection_reproduces_the_golden_log_and_oracle_exactly() -> None:
    """Pin what the projection produces, not merely that it produces it twice the same.

    Every other check here is internal: same inputs give the same output, the counts are plausible,
    the schema holds. All of those survive a change that shifts every observation by a second, or
    consumes one random draw more per dwell — the log would still be self-consistent, and every
    dataset measured against it would be quietly different. The golden pair is the only assertion
    that fails when the sensor field stops seeing what it used to see.
    """
    bundle = golden_model("simulation-bundle.json", SimulationBundle)
    trace = golden_model("execution-trace.json", ExecutionTrace)
    model = golden_model("sensor-model.json", SensorModel)

    projection = project_sensors(trace, bundle, model)

    assert projection.observable_log == golden_model(
        "observable-sensor-log.json", ObservableSensorLog
    )
    assert projection.oracle_mapping == golden_model("oracle-mapping.json", OracleMapping)


def test_building_an_environment_compiles_the_scenario_exactly_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One materialization, one solve.

    The plan is compiled here and then handed to the binder, whose M2 gate used to obtain the plan
    it should have been given the only way it could: by compiling the same scenario over again. On
    Marco's five-month horizon that duplicate was measured at roughly twenty minutes — the larger
    half of everything spent before execution — to re-derive `canonical-plan.json` byte for byte.
    """
    calls: list[str] = []

    def counted(scenario: Scenario, on_progress: Any = None) -> CompilationResult:
        calls.append(scenario.scenario_id)
        return compile_scenario(scenario, on_progress)

    monkeypatch.setattr("smart_home_sim.materialization.service.compile_scenario", counted)
    monkeypatch.setattr("smart_home_sim.environment.service.compile_scenario", counted)
    # The gate memoizes its digest per scenario, so a cache warmed by an earlier test would hide a
    # duplicate that a fresh process still pays for.
    environment_service._compiled_plan_digest.cache_clear()

    materialize_environment(
        SOURCE / "scenario.json",
        SOURCE / "personal-process-package.json",
        tmp_path / "once",
    )

    assert calls == [
        Scenario.model_validate_json((SOURCE / "scenario.json").read_bytes()).scenario_id
    ]


def test_a_reused_compilation_builds_the_same_environment_as_compiling_twice(
    tmp_path: Path,
) -> None:
    """Handing back an already-computed solve must change the cost, not the result.

    Validating an authoring bundle compiles the scenario, and materializing it compiled the same
    scenario again: on a five-month horizon that second solve is half an hour spent to reproduce
    bytes the caller already had. Reuse is only worth having if what comes out is indistinguishable
    from what the duplicate solve produced, so that is what this asserts — every artifact, byte for
    byte, including the compilation report.
    """
    scenario, _ = source_models()
    compiled = compile_scenario(scenario)

    fresh_path = tmp_path / "fresh"
    reused_path = tmp_path / "reused"
    fresh = materialize_environment(
        SOURCE / "scenario.json", SOURCE / "personal-process-package.json", fresh_path
    )
    reused = materialize_environment(
        SOURCE / "scenario.json",
        SOURCE / "personal-process-package.json",
        reused_path,
        precompiled=compiled,
    )

    assert {item.relative_path for item in reused.artifacts} == {
        item.relative_path for item in fresh.artifacts
    }
    for item in fresh.artifacts:
        assert (reused_path / item.relative_path).read_bytes() == (
            fresh_path / item.relative_path
        ).read_bytes(), item.relative_path
    assert reused.artifacts == fresh.artifacts


def test_a_plan_compiled_from_another_scenario_is_refused(tmp_path: Path) -> None:
    """The guard is an identity check, not a resemblance check.

    A canonical plan records the digest of the document it was compiled from. Accepting a plan
    without comparing it would let a caller materialize a home for a scenario nobody supplied —
    silently, because every later artifact would be internally consistent with the wrong plan.
    """
    scenario, _ = source_models()
    other = scenario.model_copy(update={"scenario_id": f"{scenario.scenario_id}_altered"})
    foreign = compile_scenario(other)
    assert foreign.plan is not None

    with pytest.raises(RuntimeError, match="compiled from a different scenario"):
        materialize_environment(
            SOURCE / "scenario.json",
            SOURCE / "personal-process-package.json",
            tmp_path / "foreign",
            precompiled=foreign,
        )
    assert not (tmp_path / "foreign").exists()

    # Same identifier, edited content: the digest still separates them.
    renamed = foreign.plan.model_copy(update={"source_scenario_id": scenario.scenario_id})
    with pytest.raises(RuntimeError, match="compiled from a different scenario"):
        materialize_environment(
            SOURCE / "scenario.json",
            SOURCE / "personal-process-package.json",
            tmp_path / "renamed",
            precompiled=CompilationResult(plan=renamed, report=foreign.report),
        )
    assert not (tmp_path / "renamed").exists()


def test_a_compilation_without_a_plan_is_refused(tmp_path: Path) -> None:
    failed = CompilationResult(plan=None, report=compile_scenario(source_models()[0]).report)
    with pytest.raises(RuntimeError, match="carries no canonical plan"):
        materialize_environment(
            SOURCE / "scenario.json",
            SOURCE / "personal-process-package.json",
            tmp_path / "planless",
            precompiled=failed,
        )
    assert not (tmp_path / "planless").exists()


UPSTAIRS = ("bedroom", "bathroom", "landing", "study")


def _two_storey_scenario() -> tuple[Scenario, PersonalProcessPackage]:
    """The fixture flat, rewritten as a house: half its rooms upstairs, plus a landing and a study.

    A storey is declared in the location's own `attributes`, which is why this needs no new fixture
    on disk and why every scenario written before houses had storeys still means the ground floor.
    """
    scenario, package = source_models()
    rooms = [item for item in scenario.locations if item.kind is LocationKind.room]
    rooms = [
        item.model_copy(update={"attributes": {"level": 1}})
        if item.location_id in UPSTAIRS
        else item
        for item in rooms
    ] + [
        Location(location_id="landing", kind=LocationKind.room, attributes={"level": 1}),
        Location(location_id="study", kind=LocationKind.room, attributes={"level": 1}),
    ]
    others = [item for item in scenario.locations if item.kind is not LocationKind.room]
    locations = rooms + [item for item in others if item.kind is not LocationKind.composite]
    locations.extend(
        item.model_copy(update={"member_location_ids": [room.location_id for room in rooms]})
        for item in others
        if item.kind is LocationKind.composite
    )
    resources = list(scenario.resources) + [
        Resource(resource_id="desk_study_01", resource_type="desk", location_id="study"),
        Resource(resource_id="chair_study_01", resource_type="chair", location_id="study"),
        Resource(
            resource_id="bookshelf_landing_01", resource_type="bookshelf", location_id="landing"
        ),
    ]
    facts = dict(scenario.initial_state.resource_facts)
    for resource in resources:
        facts.setdefault(resource.resource_id, {"available": True})
    return (
        scenario.model_copy(
            update={
                "locations": locations,
                "resources": resources,
                "initial_state": scenario.initial_state.model_copy(
                    update={
                        "resource_facts": facts,
                        "environment_facts": {
                            **scenario.initial_state.environment_facts,
                            "dwelling_scale": 1.3,
                        },
                    }
                ),
            }
        ),
        package,
    )


def _zone_points(positions: list[tuple[float, float]]) -> list[InteractionPoint]:
    return [
        InteractionPoint(
            interaction_point_id=f"point_{index}",
            region_id="living_room",
            position=Point2D(x=x, y=y),
            approach_radius_meters=0.35,
        )
        for index, (x, y) in enumerate(positions)
    ]


def test_zones_follow_the_furniture_and_still_cover_the_whole_room() -> None:
    """A room split the way its objects are spread, not the way its bounding box divides.

    The grid this replaces cut a room into columns or quarters and dropped the empty cells. A
    living room 5.3 m wide and 6.4 m deep with the television at one end and the sofa at the other
    was cut into *columns*: both pieces landed in the same one, the other stood empty, and 33.8 m²
    ended up watched by a single detector covering 21.6 m² of it.

    Coverage is asserted as well, because the first attempt at the fix gave each zone a box around
    its own furniture and left 60% of that living room unwatched — worse than the one sensor it
    replaced, since a body crossing an unwatched floor emits nothing at all.
    """
    region = HomeRegion(
        region_id="living_room",
        kind=RegionKind.room,
        boundary=Polygon2D(
            vertices=[
                Point2D(x=0.0, y=0.0),
                Point2D(x=5.28, y=0.0),
                Point2D(x=5.28, y=6.4),
                Point2D(x=0.0, y=6.4),
            ]
        ),
    )
    television, sofa, middle = (1.36, 0.72), (1.4, 5.18), (2.64, 2.95)

    zones = _functional_zones(region, _zone_points([television, sofa, middle]), 193)

    assert len(zones) == 3, "the television and the sofa are 4.5 m apart and are not one place"
    for place in (television, sofa, middle):
        nearest = min(
            zones, key=lambda item: (item[0].x - place[0]) ** 2 + (item[0].y - place[1]) ** 2
        )
        assert (nearest[0].x, nearest[0].y) == pytest.approx(place, abs=0.01)

    room = ShapelyPolygon([(v.x, v.y) for v in region.boundary.vertices])
    covered = unary_union(
        [ShapelyPolygon([(v.x, v.y) for v in coverage.vertices]) for _, coverage in zones]
    ).intersection(room)
    assert covered.area == pytest.approx(room.area, rel=1e-6)
    # And they overlap, rather than partitioning the room between them: a real detection cone is
    # not a tile, and a field where exactly one sensor ever fires is most of the gap against Aruba.
    assert (
        sum(
            ShapelyPolygon([(v.x, v.y) for v in coverage.vertices]).intersection(room).area
            for _, coverage in zones
        )
        > room.area
    )


def test_a_quiet_room_is_told_apart_less_finely_than_a_busy_one() -> None:
    """The same two objects, the same room: how much happens there decides whether they differ."""
    region = HomeRegion(
        region_id="living_room",
        kind=RegionKind.room,
        boundary=Polygon2D(
            vertices=[
                Point2D(x=0.0, y=0.0),
                Point2D(x=5.0, y=0.0),
                Point2D(x=5.0, y=6.0),
                Point2D(x=0.0, y=6.0),
            ]
        ),
    )
    # 1.7 m apart, which is about the two sides of a bed: inside a quiet room's zone, outside a
    # busy one's. CASAS Aruba puts a detector on each side of its own bed.
    points = _zone_points([(2.0, 2.0), (2.0, 3.7)])

    assert len(_functional_zones(region, points, 4)) == 1
    assert len(_functional_zones(region, points, 300)) == 2


def test_a_landing_too_small_for_a_clear_flight_still_keeps_its_doorways_open() -> None:
    """When no pose clears the doors, give up length rather than a doorway.

    A 3.5 x 2.6 landing with three rooms off it — balcony, bathroom, bedroom — has no pose that
    keeps a full flight clear of all three. The fallback used to stop searching and stamp a fixed
    flight across the middle of the room, which on a generated house landed exactly on the bathroom
    door: its landing-side portal fell inside the staircase, and twenty-two routes became
    unexecutable in a home that had materialised without a single complaint.
    """
    policy = load_home_policy(None)
    landing = floorplan.Rect(19.5, 3.17, 3.49, 2.61)
    doors = [
        Point2D(x=21.24, y=5.38),  # balcony, along the top wall
        Point2D(x=21.24, y=3.57),  # bathroom, where the old fallback put the flight
        Point2D(x=19.9, y=4.15),  # bedroom, on the left
    ]

    rect, foot, _ = _stair_pose(landing, doors, policy)

    for door in doors:
        inside = rect.x <= door.x <= rect.max_x and rect.y <= door.y <= rect.max_y
        assert not inside, f"the flight covers the doorway at ({door.x}, {door.y})"
    # And the foot is floor a body can stand on, inside the room rather than against its wall.
    assert landing.x < foot.x < landing.max_x
    assert landing.y < foot.y < landing.max_y


def test_walking_to_an_object_that_cannot_answer_leaves_the_furniture_that_can() -> None:
    """Standing at the bookshelf must not send the reading to the anchor in the middle of the room.

    An action naming no role binds on capability, and the binder prefers whatever the resident was
    last walked to — sensible for a toilet, wrong here. The per-region service anchor answers to
    every role there is, and the one part `assigned_semantic_roles` leaves it is the *ids* of the
    real furniture, so a process that inspected `bookshelf` by id and then asked for somewhere to
    sit matched the anchor. Measured on an authored one-month horizon: forty-five reading blocks
    performed standing in the middle of a living room that contains a sofa.

    The argument-hint path a few lines above already refuses an anchor-only match for exactly this
    reason. This is the same refusal on the other path.
    """
    scenario, package = source_models()
    resources = [
        *scenario.resources,
        Resource(resource_id="bookshelf", resource_type="bookshelf", location_id="living_room"),
    ]
    facts = dict(scenario.initial_state.resource_facts)
    facts.setdefault("bookshelf", {"available": True})
    scenario = scenario.model_copy(
        update={
            "resources": resources,
            "initial_state": scenario.initial_state.model_copy(update={"resource_facts": facts}),
        }
    )

    # Walk her to the bookshelf, by id, immediately before she settles down to read.
    model = next(
        item for item in package.process_models if item.process_model_id.endswith("rest_and_read")
    )
    leisure_node = next(item for item in model.nodes if item.action_type == "leisure")
    inspect_node = leisure_node.model_copy(
        update={
            "node_id": "inspect_the_shelf",
            "action_type": "inspect",
            "arguments": {
                "targetRole": ValueExpression(source=ValueSource.literal, value="bookshelf")
            },
        }
    )
    incoming = next(item for item in model.edges if item.target_node_id == leisure_node.node_id)
    edges = [item for item in model.edges if item is not incoming] + [
        incoming.model_copy(update={"target_node_id": inspect_node.node_id}),
        ProcessEdge(source_node_id=inspect_node.node_id, target_node_id=leisure_node.node_id),
    ]
    patched = model.model_copy(update={"nodes": [*model.nodes, inspect_node], "edges": edges})
    package = package.model_copy(
        update={
            "process_models": [
                patched if item.process_model_id == model.process_model_id else item
                for item in package.process_models
            ]
        }
    )

    home = generate_home(scenario, package).home
    assert home is not None
    actions = ActionCatalog.model_validate_json(
        default_action_catalog_path(package.catalogs.action_catalog.version).read_text()
    )
    variables = VariableCatalog.model_validate_json(default_variable_catalog_path().read_text())
    bindings, _ = environment_service._build_action_bindings(
        home, scenario, package, actions, variables
    )

    chosen = {
        item.provider_id
        for binding in bindings
        if binding.node_id == leisure_node.node_id
        and binding.process_model_id == model.process_model_id
        for item in binding.capability_bindings
        if item.capability == "leisure_support"
    }
    assert chosen, "the reading never bound to anything at all"
    assert chosen == {"sofa"}, chosen


def test_a_house_with_two_storeys_is_one_valid_plan_joined_by_a_staircase() -> None:
    """Two floors are two blocks of one coordinate plane, and a stairway is what crosses between.

    Keeping the model flat is the whole point: nothing about regions not overlapping, obstacles
    living inside one region, or routing inside a room had to change to draw a house.
    """
    scenario, package = _two_storey_scenario()
    result = generate_home(scenario, package)
    assert result.report.success, [issue.message for issue in result.report.issues]
    home = result.home
    assert home is not None

    upstairs = {region.region_id for region in home.regions if region.level == 1}
    assert upstairs == set(UPSTAIRS)
    rooms = [region for region in home.regions if region.kind.value == "room"]
    # Side by side, not on top of one another: the geometry rules stay the ones for a flat.
    assert max(
        point.x for region in rooms if region.level == 0 for point in region.boundary.vertices
    ) < min(point.x for region in rooms if region.level == 1 for point in region.boundary.vertices)

    stairways = [item for item in home.connections if item.kind is ConnectionKind.stairway]
    assert len(stairways) == 1
    flight = stairways[0]
    # The climb is declared, because the gap between the blocks on the page is not a distance.
    assert flight.distance_meters == load_home_policy(None).stair_run_meters
    assert {flight.region_a_id, flight.region_b_id} & upstairs

    # A flight is a real object at both ends, standing on floor the furniture has to work round.
    treads = [item for item in home.obstacles if item.obstacle_id.startswith("obstacle_stairs_")]
    assert {item.region_id for item in treads} == {flight.region_a_id, flight.region_b_id}
    assert all(item.orientation_degrees in {0.0, 90.0, 180.0, 270.0} for item in treads)
    # A tread is named after the flight it belongs to. It is the only obstacle with no entity to
    # own it, so the id is the one thing that says which staircase it is the foot of — and the
    # editor deletes a whole staircase by reading exactly this, on generated homes as on its own.
    assert all(item.obstacle_id.startswith(f"obstacle_{flight.connection_id}_") for item in treads)

    # And the resident can actually walk upstairs.
    kitchen = next(
        item for item in home.interaction_points if item.interaction_point_id == "anchor_kitchen"
    )
    bedroom = next(
        item for item in home.interaction_points if item.interaction_point_id == "anchor_bedroom"
    )
    route = plan_path(
        home,
        start_region_id="kitchen",
        start=kitchen.position,
        end_region_id="bedroom",
        end=bedroom.position,
        walking_speed_meters_per_second=1.2,
        body_radius_meters=home.kinematic_defaults.body_radius_meters,
        mobility_profile="default",
    )
    crossed = list(dict.fromkeys(point.region_id for point in route.waypoints))
    assert crossed[0] == "kitchen" and crossed[-1] == "bedroom"
    assert flight.region_a_id in crossed and flight.region_b_id in crossed
    # One flight, not the ten metres of blank page between the two blocks.
    assert route.distance_meters < 40.0


def test_the_dwelling_scale_is_read_from_the_scenario_and_bounded() -> None:
    """A studio and a family house come off the same room profiles, sized differently."""
    scenario, package = source_models()

    def plan_area(scale: object) -> float:
        subject = scenario.model_copy(
            update={
                "initial_state": scenario.initial_state.model_copy(
                    update={"environment_facts": {"dwelling_scale": scale}}
                )
            }
        )
        home = generate_home(subject, package).home
        assert home is not None
        return sum(
            _polygon_area(region.boundary.vertices)
            for region in home.regions
            if region.kind.value == "room"
        )

    assert plan_area(0.7) < plan_area(1.0) < plan_area(1.4)
    # Nonsense is ignored rather than obeyed: a plan is not drawn at a hundred times life size.
    assert plan_area(99.0) == plan_area("not a number") == plan_area(1.0)


def _polygon_area(vertices: list[Point2D]) -> float:
    total = 0.0
    for index, point in enumerate(vertices):
        following = vertices[(index + 1) % len(vertices)]
        total += point.x * following.y - following.x * point.y
    return abs(total) / 2
