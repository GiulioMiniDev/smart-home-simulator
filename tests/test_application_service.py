from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from smart_home_sim.application.plan_approval import (
    RECOMMENDED,
    approved_home_model,
    approved_sensor_model,
    plan_approval,
)
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


def test_the_ui_asks_the_backend_for_artifacts_that_exist() -> None:
    """The front end names generation artifacts as literal paths, so a rename can strand it.

    That is not hypothetical: renaming `planned-habit-trace.json` to `planned-activity-trace.json`
    left the Generate review page requesting a file the backend no longer serves, and the front-end
    tests did not notice because they mock the API and return whatever shape they were told to.
    Mocks cannot check a contract with the other side; this can.
    """
    import re

    from smart_home_sim.application.generation_paths import GENERATION_ARTIFACTS

    source = (PROJECT_ROOT / "frontend/src/App.tsx").read_text(encoding="utf-8")
    # The page builds one `${base}` ending in /artifact and appends each filename to it.
    assert "/artifact`" in source, "the review page no longer builds an artifact base path"
    requested = set(re.findall(r"\$\{base\}/([A-Za-z0-9._-]+\.json)", source))

    assert requested, "expected the review page to fetch at least one generation artifact"
    assert requested <= set(GENERATION_ARTIFACTS), sorted(requested - set(GENERATION_ARTIFACTS))


def test_the_ui_reads_the_field_the_behavioural_profile_publishes() -> None:
    """Same drift, one level down: the file existed but its list had been renamed underneath."""
    from smart_home_sim.hybrid_planning.recurring_activities import BehavioralProfile

    source = (PROJECT_ROOT / "frontend/src/App.tsx").read_text(encoding="utf-8")
    alias = BehavioralProfile.model_fields["recurring_activities"].alias or "recurring_activities"

    assert "behavioral-profile.json" in source
    assert f"{alias}: unknown[]" in source
    assert f"profile.{alias}.length" in source


def _outline_bundle() -> dict[str, object]:
    """The reference outline, paired with a package that covers everything the days will contain.

    The published example carries no process package of its own — it illustrates the outline — so
    the minimal bundle's package is padded to bind every catalog intent plus the ones the rhythm
    adds by itself. Without that padding the expander refuses the pair, which is the behaviour a
    sibling test asserts.
    """
    from smart_home_sim.hybrid_planning.day_generation import RHYTHM_EMITTED_INTENTS
    from smart_home_sim.hybrid_planning.intents import INTENT_CATALOG

    package = _authoring()["personalProcessPackage"]
    assert isinstance(package, dict)
    template = package["bindings"][0]
    bound = {binding["intent"] for binding in package["bindings"]}
    needed = {spec.intent_id for spec in INTENT_CATALOG} | RHYTHM_EMITTED_INTENTS | {"work_shift"}
    for intent in sorted(needed - bound):
        package["bindings"].append(
            {**template, "bindingId": f"{template['residentId']}__{intent}", "intent": intent}
        )
    outline = json.loads(
        (PROJECT_ROOT / "examples/authoring/meredith.horizon-outline.json").read_text(
            encoding="utf-8"
        )
    )
    return {
        "schemaVersion": "1.0.0",
        "documentType": "horizon_authoring_bundle",
        "outline": outline,
        "personalProcessPackage": package,
    }


def test_a_horizon_outline_is_expanded_and_then_imported_like_any_bundle(tmp_path: Path) -> None:
    """The application can take a long horizon without the researcher leaving it for a terminal.

    What arrives is a structure, not days; the expander produces them and the result rejoins the
    ordinary import immediately, which is why the response carries the same report as an authored
    bundle plus a summary of what expanding it produced.
    """
    workspace = WorkspaceService.create(tmp_path / "workspace", "Outline")
    home = workspace.create_home("Outline home")
    service = ApplicationService(workspace)

    result = service.import_horizon_outline(home.home_id, _outline_bundle(), seed=1)

    expansion = result["expansion"]
    assert expansion["seed"] == 1
    assert expansion["dayCount"] > 200, "eight months of days should have been produced"
    assert expansion["habitBandCount"] >= 3
    assert "report" in result or result.get("valid") is True


def test_a_document_that_is_not_an_outline_is_refused_before_anything_is_written(
    tmp_path: Path,
) -> None:
    workspace = WorkspaceService.create(tmp_path / "workspace", "Outline")
    home = workspace.create_home("Outline home")
    service = ApplicationService(workspace)

    result = service.import_horizon_outline(home.home_id, _authoring(), seed=1)

    assert result["valid"] is False
    assert result["stage"] == "outline"
    assert workspace.list_residents(home.home_id) == []


def test_a_reviewed_plan_stops_being_a_recommendation(tmp_path: Path) -> None:
    """Confirming or editing the recommended planimetry makes it the home's own model.

    Everything downstream reads this one distinction: a recommended plan is regenerated from the
    policy on every run, an approved one is executed as it stands. The researcher who accepts the
    proposal untouched has decided just as much as the one who moves a wall, so both paths must
    leave the home approved.
    """
    workspace = WorkspaceService.create(tmp_path / "workspace", "Approval")
    summary = workspace.create_home("Reviewed home")
    service = ApplicationService(workspace)
    home = json.loads(
        (PROJECT_ROOT / "examples/environment/mario_monteverde.home.json").read_text(
            encoding="utf-8"
        )
    )
    sensor = json.loads(
        (PROJECT_ROOT / "examples/sensors/mario_monteverde.sensor-model.json").read_text(
            encoding="utf-8"
        )
    )

    assert service.publish_home(summary.home_id, home, approval=RECOMMENDED)["valid"] is True
    assert service.publish_sensor(summary.home_id, sensor, approval=RECOMMENDED)["valid"] is True
    assert plan_approval(workspace, summary.home_id) == {
        "home": RECOMMENDED,
        "sensor": RECOMMENDED,
        "approved": False,
    }
    assert approved_home_model(workspace, summary.home_id) is None
    assert approved_sensor_model(workspace, summary.home_id) is None

    approved = service.approve_plan(summary.home_id)

    assert approved["planApproval"]["approved"] is True
    model = approved_home_model(workspace, summary.home_id)
    assert model is not None and model.home_id == home["homeId"]
    field = approved_sensor_model(workspace, summary.home_id)
    assert field is not None and field.sensors
    # Approval decides, it does not duplicate: the artifact the run executes is the reviewed one.
    assert (
        workspace.get_home(summary.home_id).current_home_artifact_id
        == workspace.latest_revision(summary.home_id, "home")["artifactId"]
    )


def test_editing_the_plan_approves_it_and_a_home_without_one_cannot_be_approved(
    tmp_path: Path,
) -> None:
    workspace = WorkspaceService.create(tmp_path / "workspace", "Approval")
    summary = workspace.create_home("Edited home")
    service = ApplicationService(workspace)

    with pytest.raises(WorkspaceError, match="no plan to approve"):
        service.approve_plan(summary.home_id)

    home = json.loads(
        (PROJECT_ROOT / "examples/environment/mario_monteverde.home.json").read_text(
            encoding="utf-8"
        )
    )
    # The researcher drags the bed 20 cm across the bedroom, which is a decision about the home.
    edited = copy.deepcopy(home)
    for vertex in edited["obstacles"][0]["boundary"]["vertices"]:
        vertex["x"] += 0.2

    assert service.publish_home(summary.home_id, edited)["valid"] is True

    assert plan_approval(workspace, summary.home_id)["approved"] is True
    model = approved_home_model(workspace, summary.home_id)
    assert model is not None
    assert [point.x for point in model.obstacles[0].boundary.vertices] == [
        vertex["x"] for vertex in edited["obstacles"][0]["boundary"]["vertices"]
    ]
