from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from smart_home_sim.cli import app
from smart_home_sim.compiler.service import canonical_sha256
from smart_home_sim.domain.behavior import PersonalProcessPackage
from smart_home_sim.domain.environment import (
    ConnectionKind,
    HomeModel,
    Point2D,
    Polygon2D,
    SimulationBundle,
)
from smart_home_sim.domain.materialization import (
    EnvironmentMaterializationManifest,
    HomeGenerationPolicy,
    HomeGenerationReport,
    SensorDeploymentPolicy,
    SensorDeploymentReport,
    SyntheticWorkspaceManifest,
    WorkspaceArtifact,
)
from smart_home_sim.domain.models import Location, LocationKind, Scenario
from smart_home_sim.domain.sensors import (
    ContactSensor,
    PirSensor,
    SensorModel,
    TemperatureSensor,
)
from smart_home_sim.environment import validate_home_model
from smart_home_sim.materialization import (
    bind_sensor_model,
    deploy_sensors,
    generate_home,
    materialize_environment,
    materialize_workspace,
)
from smart_home_sim.materialization.service import (
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
    approved = recommended.model_copy(
        update={
            "obstacles": [
                recommended.obstacles[0].model_copy(
                    update={
                        "boundary": Polygon2D(
                            vertices=[
                                Point2D(x=point.x + 0.2, y=point.y)
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
