from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from smart_home_sim.cli import app
from smart_home_sim.compiler.service import canonical_sha256
from smart_home_sim.domain.behavior import PersonalProcessPackage
from smart_home_sim.domain.environment import HomeModel, SimulationBundle
from smart_home_sim.domain.materialization import (
    HomeGenerationPolicy,
    HomeGenerationReport,
    SensorDeploymentPolicy,
    SensorDeploymentReport,
    SyntheticWorkspaceManifest,
)
from smart_home_sim.domain.models import Location, LocationKind, Scenario
from smart_home_sim.domain.sensors import SensorModel
from smart_home_sim.environment import validate_home_model
from smart_home_sim.materialization import deploy_sensors, generate_home, materialize_workspace
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


@pytest.mark.parametrize(
    ("preset", "expected_pir", "expected_contact", "expected_temperature"),
    [("minimal", 1, 1, 1), ("room_coverage", 6, 3, 6), ("dense", 12, 3, 6)],
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
    assert len(first.artifacts) == 17
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
    assert load_sensor_policy(None) == SensorDeploymentPolicy()
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
    assert "17 verified artifacts" in run.output
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
