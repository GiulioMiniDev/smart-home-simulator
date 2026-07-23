from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from smart_home_sim.application.workspace import WorkspaceError, WorkspaceService
from smart_home_sim.authoring.service import validate_authoring_payload
from smart_home_sim.domain.application import ApplicationIssue, GraphicalReference
from smart_home_sim.domain.environment import HomeModel
from smart_home_sim.domain.longitudinal import LongitudinalSimulationManifest
from smart_home_sim.domain.models import Scenario
from smart_home_sim.domain.sensors import SensorModel
from smart_home_sim.environment import validate_home_model
from smart_home_sim.simulation.longitudinal_validation import (
    load_and_validate_longitudinal_manifest,
)


def _reference(path: str) -> GraphicalReference | None:
    mappings = (
        ("regions", "home"),
        ("connections", "home"),
        ("obstacles", "home"),
        ("interactionPoints", "home"),
        ("entities", "home"),
        ("sensors", "sensor"),
    )
    for collection, surface in mappings:
        bracket_marker = f".{collection}["
        dotted_marker = f".{collection}."
        if bracket_marker in path:
            suffix = path.split(bracket_marker, 1)[1]
            return GraphicalReference(
                surface=surface, element_id=f"index:{suffix.split(']', 1)[0]}"
            )
        if dotted_marker in path:
            suffix = path.split(dotted_marker, 1)[1]
            return GraphicalReference(
                surface=surface, element_id=f"index:{suffix.split('.', 1)[0]}"
            )
    return GraphicalReference(surface="form", element_id=path)


def _issues(items: list[Any]) -> list[ApplicationIssue]:
    results: list[ApplicationIssue] = []
    seen: set[tuple[str, str, str, str, str]] = set()
    for item in items:
        key = (
            item.code,
            item.severity,
            item.path,
            item.message,
            json.dumps(item.details, sort_keys=True, default=str),
        )
        if key in seen:
            continue
        seen.add(key)
        results.append(
            ApplicationIssue(
                code=item.code,
                severity=item.severity,
                stage=item.stage,
                path=item.path,
                message=item.message,
                details=item.details,
                graphical_reference=_reference(item.path),
            )
        )
    return results


class ApplicationService:
    def __init__(self, workspace: WorkspaceService) -> None:
        self.workspace = workspace

    def import_authoring(
        self,
        home_id: str,
        scenario_payload: dict[str, Any],
        behavior_payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Backward-compatible Advanced import for two canonical documents."""
        return self.import_authoring_bundle(
            home_id,
            {
                "schemaVersion": "1.0.0",
                "documentType": "simulation_authoring_bundle",
                "scenario": scenario_payload,
                "personalProcessPackage": behavior_payload,
            },
        )

    def import_authoring_bundle(
        self,
        home_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Validate and publish one researcher-facing authoring bundle."""
        self.workspace.ensure_writable()
        self.workspace.get_home(home_id)
        result = validate_authoring_payload(payload)
        issues = _issues(result.report.issues)
        self.workspace.replace_validation_issues(home_id, issues)
        if not result.report.valid:
            return {
                "valid": False,
                "report": result.report.model_dump(mode="json", by_alias=True),
                "issues": [item.model_dump(mode="json", by_alias=True) for item in issues],
            }
        assert result.scenario_json is not None
        assert result.behavior_json is not None
        canonical_bundle_json = (
            json.dumps(
                {
                    "schemaVersion": "1.0.0",
                    "documentType": "simulation_authoring_bundle",
                    "scenario": json.loads(result.scenario_json),
                    "personalProcessPackage": json.loads(result.behavior_json),
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )
        bundle_artifact = self.workspace.put_object(
            canonical_bundle_json.encode("utf-8"),
            role="simulation_authoring_bundle",
            schema_version="1.0.0",
            home_id=home_id,
        )
        scenario_artifact = self.workspace.put_object(
            result.scenario_json.encode("utf-8"),
            role="scenario",
            schema_version="1.0.0",
            home_id=home_id,
        )
        behavior_artifact = self.workspace.put_object(
            result.behavior_json.encode("utf-8"),
            role="personal_process_package",
            schema_version="1.0.0",
            home_id=home_id,
        )
        scenario = Scenario.model_validate_json(result.scenario_json)
        resident_results = self.workspace.replace_authoring_residents(
            home_id,
            [
                (resident.resident_id, resident.display_name or resident.resident_id)
                for resident in scenario.residents
            ],
            scenario_artifact_id=scenario_artifact.artifact_id,
            behavior_artifact_id=behavior_artifact.artifact_id,
        )
        source_bundle = {
            "artifactId": bundle_artifact.artifact_id,
            "sha256": bundle_artifact.sha256,
        }
        report = result.report.model_dump(mode="json", by_alias=True)
        bundle_revision = self.workspace.create_revision(
            home_id,
            "authoring_bundle",
            bundle_artifact.artifact_id,
            status="valid",
            provenance={"ingestionReport": report},
        )
        scenario_revision = self.workspace.create_revision(
            home_id,
            "scenario",
            scenario_artifact.artifact_id,
            status="valid",
            provenance={"ingestionReport": report, "sourceBundle": source_bundle},
        )
        behavior_revision = self.workspace.create_revision(
            home_id,
            "behavior",
            behavior_artifact.artifact_id,
            status="valid",
            provenance={"ingestionReport": report, "sourceBundle": source_bundle},
        )
        return {
            "valid": True,
            "report": report,
            "issues": [item.model_dump(mode="json", by_alias=True) for item in issues],
            "bundleArtifact": bundle_artifact.model_dump(mode="json", by_alias=True),
            "scenarioArtifact": scenario_artifact.model_dump(mode="json", by_alias=True),
            "behaviorArtifact": behavior_artifact.model_dump(mode="json", by_alias=True),
            "bundleRevisionId": bundle_revision,
            "scenarioRevisionId": scenario_revision,
            "behaviorRevisionId": behavior_revision,
            "residents": [item.model_dump(mode="json", by_alias=True) for item in resident_results],
        }

    def import_longitudinal_manifest(
        self,
        home_id: str,
        manifest_payload: dict[str, Any],
        scenarios_payload: dict[str, dict[str, Any]] | None = None,
        behavior_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Validate and publish a longitudinal multi-scenario simulation manifest package."""
        self.workspace.ensure_writable()
        self.workspace.get_home(home_id)
        scenarios_payload = scenarios_payload or {}

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)

            for rel_path, sc_dict in scenarios_payload.items():
                target_file = tmp_path / rel_path
                target_file.parent.mkdir(parents=True, exist_ok=True)
                target_file.write_text(json.dumps(sc_dict), encoding="utf-8")

            if behavior_payload:
                pkg_path_str = manifest_payload.get("personalProcessPackagePath", "personal-process-package.json")
                pkg_file = tmp_path / pkg_path_str
                pkg_file.parent.mkdir(parents=True, exist_ok=True)
                pkg_file.write_text(json.dumps(behavior_payload), encoding="utf-8")

            manifest_file = tmp_path / "manifest.json"
            manifest_file.write_text(json.dumps(manifest_payload), encoding="utf-8")

            try:
                resolved = load_and_validate_longitudinal_manifest(manifest_file)
            except Exception as error:
                issue = ApplicationIssue(
                    code="LONGITUDINAL_MANIFEST_INVALID",
                    severity="error",
                    stage="compatibility",
                    path="$",
                    message=str(error),
                )
                return {
                    "valid": False,
                    "issues": [issue.model_dump(mode="json", by_alias=True)],
                }

            manifest_bytes = json.dumps(manifest_payload, indent=2).encode("utf-8")
            manifest_artifact = self.workspace.put_object(
                manifest_bytes,
                role="longitudinal_simulation_manifest",
                schema_version="1.0.0",
                home_id=home_id,
            )

            return {
                "valid": True,
                "manifestArtifactId": manifest_artifact.artifact_id,
                "chunkCount": len(resolved.scenarios),
                "runId": resolved.manifest.run_id,
                "seed": resolved.manifest.seed,
            }

    def publish_home(self, home_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.workspace.ensure_writable()
        self.workspace.get_home(home_id)
        try:
            # Strict domain models accept timestamps and enum values through
            # their JSON wire representation, as the CLI validators do.
            home = HomeModel.model_validate_json(json.dumps(payload))
        except ValidationError as error:
            issues = [
                ApplicationIssue(
                    code="HOME_STRUCTURE_INVALID",
                    severity="error",
                    stage="structure",
                    path="$." + ".".join(str(part) for part in item["loc"]),
                    message=item["msg"],
                    graphical_reference=_reference(
                        "$." + ".".join(str(part) for part in item["loc"])
                    ),
                )
                for item in error.errors(
                    include_url=False, include_context=False, include_input=False
                )
            ]
            self.workspace.replace_validation_issues(home_id, issues)
            return {
                "valid": False,
                "issues": [item.model_dump(mode="json", by_alias=True) for item in issues],
            }
        report = validate_home_model(home)
        issues = _issues(report.issues)
        self.workspace.replace_validation_issues(home_id, issues)
        if not report.valid:
            return {
                "valid": False,
                "report": report.model_dump(mode="json", by_alias=True),
                "issues": [item.model_dump(mode="json", by_alias=True) for item in issues],
            }
        content = home.model_dump_json(by_alias=True, indent=2).encode("utf-8") + b"\n"
        artifact = self.workspace.put_object(
            content,
            role="home_model",
            schema_version="1.0.0",
            home_id=home_id,
        )
        revision = self.workspace.create_revision(
            home_id,
            "home",
            artifact.artifact_id,
            status="valid",
            provenance={"validationReport": report.model_dump(mode="json", by_alias=True)},
        )
        return {
            "valid": True,
            "report": report.model_dump(mode="json", by_alias=True),
            "issues": [item.model_dump(mode="json", by_alias=True) for item in issues],
            "artifact": artifact.model_dump(mode="json", by_alias=True),
            "revisionId": revision,
        }

    def publish_sensor(self, home_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.workspace.ensure_writable()
        self.workspace.get_home(home_id)
        try:
            sensor = SensorModel.model_validate_json(json.dumps(payload))
        except ValidationError as error:
            issues = [
                ApplicationIssue(
                    code="SENSOR_STRUCTURE_INVALID",
                    severity="error",
                    stage="structure",
                    path="$." + ".".join(str(part) for part in item["loc"]),
                    message=item["msg"],
                    graphical_reference=_reference(
                        "$." + ".".join(str(part) for part in item["loc"])
                    ),
                )
                for item in error.errors(
                    include_url=False, include_context=False, include_input=False
                )
            ]
            self.workspace.replace_validation_issues(home_id, issues)
            return {
                "valid": False,
                "issues": [item.model_dump(mode="json", by_alias=True) for item in issues],
            }
        home_summary = self.workspace.get_home(home_id)
        if home_summary.current_home_artifact_id is None:
            raise WorkspaceError("publish a valid home before publishing sensors")
        home = HomeModel.model_validate_json(
            self.workspace.read_artifact(home_summary.current_home_artifact_id)
        )
        region_ids = {item.region_id for item in home.regions}
        entity_ids = {item.entity_id for item in home.entities}
        unknown_regions = sorted(set(sensor.region_ids) - region_ids)
        unknown_entities = sorted(set(sensor.entity_ids) - entity_ids)
        issues: list[ApplicationIssue] = []
        if unknown_regions:
            issues.append(
                ApplicationIssue(
                    code="SENSOR_REGION_UNKNOWN",
                    severity="error",
                    stage="compatibility",
                    path="$.regionIds",
                    message=f"Unknown home regions: {', '.join(unknown_regions)}",
                    details={"regionIds": unknown_regions},
                    graphical_reference=GraphicalReference(
                        surface="sensor", element_id="regionIds"
                    ),
                )
            )
        if unknown_entities:
            issues.append(
                ApplicationIssue(
                    code="SENSOR_ENTITY_UNKNOWN",
                    severity="error",
                    stage="compatibility",
                    path="$.entityIds",
                    message=f"Unknown home entities: {', '.join(unknown_entities)}",
                    details={"entityIds": unknown_entities},
                    graphical_reference=GraphicalReference(
                        surface="sensor", element_id="entityIds"
                    ),
                )
            )
        if issues:
            self.workspace.replace_validation_issues(home_id, issues)
            return {
                "valid": False,
                "issues": [item.model_dump(mode="json", by_alias=True) for item in issues],
            }
        self.workspace.replace_validation_issues(home_id, [])
        content = sensor.model_dump_json(by_alias=True, indent=2).encode("utf-8") + b"\n"
        artifact = self.workspace.put_object(
            content,
            role="sensor_model",
            schema_version="1.0.0",
            home_id=home_id,
        )
        revision = self.workspace.create_revision(
            home_id,
            "sensor",
            artifact.artifact_id,
            status="valid",
            provenance={"validatedAgainstHomeArtifact": home_summary.current_home_artifact_id},
        )
        return {
            "valid": True,
            "issues": [],
            "artifact": artifact.model_dump(mode="json", by_alias=True),
            "revisionId": revision,
        }

    def current_models(self, home_id: str) -> dict[str, Any]:
        home = self.workspace.get_home(home_id)
        result: dict[str, Any] = {}
        if home.current_home_artifact_id:
            result["homeModel"] = json.loads(
                self.workspace.read_artifact(home.current_home_artifact_id)
            )
        if home.current_sensor_artifact_id:
            result["sensorModel"] = json.loads(
                self.workspace.read_artifact(home.current_sensor_artifact_id)
            )
        return result
