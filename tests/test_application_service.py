from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from smart_home_sim.application.service import ApplicationService, _issues
from smart_home_sim.application.workspace import WorkspaceError, WorkspaceService

PROJECT_ROOT = Path(__file__).parents[1]


def _authoring() -> dict[str, object]:
    return json.loads(
        (PROJECT_ROOT / "examples/authoring/minimal.authoring-bundle.json").read_text(
            encoding="utf-8"
        )
    )


def test_application_issues_are_deduplicated_for_display_and_persistence() -> None:
    issue = SimpleNamespace(
        code="DUPLICATE",
        severity="error",
        stage="behavior",
        path="$.personalProcessPackage.processModels[0]",
        message="Repeated issue",
        details={"model": "process_1"},
    )
    assert len(_issues([issue, issue])) == 1


def test_authoring_import_is_atomic_and_creates_resident_revisions(tmp_path: Path) -> None:
    workspace = WorkspaceService.create(tmp_path / "workspace", "Authoring")
    home = workspace.create_home("Minimal home")
    service = ApplicationService(workspace)
    payload = _authoring()
    result = service.import_authoring_bundle(home.home_id, payload)
    assert result["valid"] is True
    assert result["bundleArtifact"]["role"] == "simulation_authoring_bundle"
    assert result["scenarioArtifact"]["role"] == "scenario"
    assert result["behaviorArtifact"]["role"] == "personal_process_package"
    residents = workspace.list_residents(home.home_id)
    assert [item.source_resident_id for item in residents] == ["resident_1"]
    assert service.current_models(home.home_id) == {}

    with workspace.connection() as connection:
        provenance = json.loads(
            connection.execute(
                "SELECT provenance_json FROM revisions WHERE revision_id=?",
                (result["scenarioRevisionId"],),
            ).fetchone()["provenance_json"]
        )
    assert provenance["sourceBundle"] == {
        "artifactId": result["bundleArtifact"]["artifactId"],
        "sha256": result["bundleArtifact"]["sha256"],
    }

    artifact_count = workspace.summary().artifact_count
    invalid = copy.deepcopy(payload)
    invalid["scenario"]["residents"] = []  # type: ignore[index]
    rejected = service.import_authoring_bundle(home.home_id, invalid)
    assert rejected["valid"] is False
    assert rejected["issues"]
    assert workspace.summary().artifact_count == artifact_count

    updated = copy.deepcopy(payload)
    updated["scenario"]["residents"][0]["displayName"] = "Updated resident"  # type: ignore[index]
    advanced = service.import_authoring(
        home.home_id,
        updated["scenario"],  # type: ignore[arg-type]
        updated["personalProcessPackage"],  # type: ignore[arg-type]
    )
    assert advanced["valid"] is True
    refreshed = workspace.list_residents(home.home_id)
    assert [item.display_name for item in refreshed] == ["Updated resident"]
    assert refreshed[0].scenario_artifact_id == advanced["scenarioArtifact"]["artifactId"]


def test_home_and_sensor_publication_uses_authoritative_validation(tmp_path: Path) -> None:
    workspace = WorkspaceService.create(tmp_path / "workspace", "Editors")
    home_summary = workspace.create_home("Golden home")
    service = ApplicationService(workspace)
    home = json.loads(
        (PROJECT_ROOT / "examples/environment/mario_monteverde.home.json").read_text(
            encoding="utf-8"
        )
    )
    published = service.publish_home(home_summary.home_id, home)
    assert published["valid"] is True
    assert service.current_models(home_summary.home_id)["homeModel"]["homeId"] == home["homeId"]

    invalid_home = copy.deepcopy(home)
    invalid_home["regions"][0]["boundary"]["vertices"] = []
    rejected = service.publish_home(home_summary.home_id, invalid_home)
    assert rejected["valid"] is False
    assert rejected["issues"][0]["graphicalReference"]["surface"] == "home"

    sensor = json.loads(
        (PROJECT_ROOT / "examples/sensors/mario_monteverde.sensor-model.json").read_text(
            encoding="utf-8"
        )
    )
    published_sensor = service.publish_sensor(home_summary.home_id, sensor)
    assert published_sensor["valid"] is True
    assert service.current_models(home_summary.home_id)["sensorModel"]["sensors"]

    unknown = copy.deepcopy(sensor)
    unknown["regionIds"].append("unknown_region")
    unknown["entityIds"].append("unknown_entity")
    rejected_sensor = service.publish_sensor(home_summary.home_id, unknown)
    assert rejected_sensor["valid"] is False
    assert {item["code"] for item in rejected_sensor["issues"]} == {
        "SENSOR_ENTITY_UNKNOWN",
        "SENSOR_REGION_UNKNOWN",
    }


def test_sensor_publication_rejects_structure_and_requires_home(tmp_path: Path) -> None:
    workspace = WorkspaceService.create(tmp_path / "workspace", "Sensor guards")
    home = workspace.create_home("Draft home")
    service = ApplicationService(workspace)

    invalid = service.publish_sensor(home.home_id, {})
    assert invalid["valid"] is False
    assert {item["code"] for item in invalid["issues"]} == {"SENSOR_STRUCTURE_INVALID"}
    assert all(item["graphicalReference"]["surface"] == "form" for item in invalid["issues"])

    sensor = json.loads(
        (PROJECT_ROOT / "examples/sensors/mario_monteverde.sensor-model.json").read_text(
            encoding="utf-8"
        )
    )
    with pytest.raises(WorkspaceError, match="publish a valid home"):
        service.publish_sensor(home.home_id, sensor)
