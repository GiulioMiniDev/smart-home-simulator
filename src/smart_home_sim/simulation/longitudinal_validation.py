from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from smart_home_sim.domain.behavior import PersonalProcessPackage
from smart_home_sim.domain.longitudinal import LongitudinalSimulationManifest
from smart_home_sim.domain.materialization import (
    HomeGenerationPolicy,
    SensorDeploymentPolicy,
)
from smart_home_sim.domain.models import Scenario
from smart_home_sim.materialization.service import (
    load_home_policy,
    load_sensor_policy,
)


@dataclass(frozen=True, slots=True)
class ResolvedLongitudinalInputs:
    manifest_path: Path
    manifest: LongitudinalSimulationManifest
    scenarios: tuple[Scenario, ...]
    scenario_paths: tuple[Path, ...]
    package: PersonalProcessPackage
    package_path: Path
    home_policy: HomeGenerationPolicy
    sensor_policy: SensorDeploymentPolicy
    manifest_sha256: str
    configuration_sha256: str


def _canonical_bytes(obj: object) -> bytes:
    if hasattr(obj, "model_dump_json"):
        return obj.model_dump_json(by_alias=True).encode("utf-8")
    return json.dumps(obj, sort_keys=True).encode("utf-8")


def load_and_validate_longitudinal_manifest(
    manifest_path: Path,
) -> ResolvedLongitudinalInputs:
    if not manifest_path.is_file():
        raise ValueError(f"longitudinal manifest file not found: {manifest_path}")

    try:
        manifest_bytes = manifest_path.read_bytes()
        manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
        manifest = LongitudinalSimulationManifest.model_validate_json(manifest_bytes)
    except (ValidationError, json.JSONDecodeError, OSError) as error:
        raise ValueError(f"invalid longitudinal manifest: {error}") from error

    base_dir = manifest_path.parent.resolve()

    package_path = (base_dir / manifest.personal_process_package_path).resolve()
    if not package_path.is_file():
        raise ValueError(
            f"personal process package file not found: {manifest.personal_process_package_path}"
        )

    try:
        package_bytes = package_path.read_bytes()
        package = PersonalProcessPackage.model_validate_json(package_bytes)
    except (ValidationError, json.JSONDecodeError, OSError) as error:
        raise ValueError(f"invalid personal process package: {error}") from error

    home_policy_path = (
        (base_dir / manifest.home_policy_path).resolve()
        if manifest.home_policy_path is not None
        else None
    )
    sensor_policy_path = (
        (base_dir / manifest.sensor_policy_path).resolve()
        if manifest.sensor_policy_path is not None
        else None
    )

    try:
        home_policy = load_home_policy(home_policy_path)
        sensor_policy = load_sensor_policy(sensor_policy_path)
    except Exception as error:
        raise ValueError(f"failed to load materialization policies: {error}") from error

    # Compute configuration fingerprint
    config_components = [
        str(manifest.seed).encode("utf-8"),
        hashlib.sha256(package_bytes).hexdigest().encode("utf-8"),
        hashlib.sha256(_canonical_bytes(home_policy)).hexdigest().encode("utf-8"),
        hashlib.sha256(_canonical_bytes(sensor_policy)).hexdigest().encode("utf-8"),
    ]
    configuration_sha256 = hashlib.sha256(b":".join(config_components)).hexdigest()

    # Load and validate scenarios
    scenario_paths: list[Path] = []
    scenarios: list[Scenario] = []

    for rel_path in manifest.scenario_paths:
        resolved_path = (base_dir / rel_path).resolve()
        if not resolved_path.is_file():
            raise ValueError(f"scenario file not found: {rel_path}")
        try:
            scenario_bytes = resolved_path.read_bytes()
            scenario = Scenario.model_validate_json(scenario_bytes)
        except (ValidationError, json.JSONDecodeError, OSError) as error:
            raise ValueError(f"invalid scenario file '{rel_path}': {error}") from error

        scenario_paths.append(resolved_path)
        scenarios.append(scenario)

    if not scenarios:
        raise ValueError("manifest must contain at least one scenario path")

    # Sequence validation gates
    first_scenario = scenarios[0]

    # Package sourceScenarioId check
    if package.source_scenario_id != first_scenario.scenario_id:
        raise ValueError(
            f"personal process package sourceScenarioId '{package.source_scenario_id}' "
            f"does not match scenario scenarioId '{first_scenario.scenario_id}'"
        )

    # Activity ID uniqueness check within each chunk
    for chunk_idx, scenario in enumerate(scenarios):
        seen_chunk_activity_ids: set[str] = set()
        for day in scenario.days:
            for activity in day.activities:
                if activity.activity_id in seen_chunk_activity_ids:
                    raise ValueError(
                        f"duplicate activityId '{activity.activity_id}' found in scenario chunk {chunk_idx + 1}"
                    )
                seen_chunk_activity_ids.add(activity.activity_id)

    # First scenario seed check against manifest
    if first_scenario.seed != manifest.seed:
        raise ValueError(
            f"scenario seed {first_scenario.seed} does not match manifest seed {manifest.seed}"
        )

    for i, scenario in enumerate(scenarios):
        if scenario.scenario_id != first_scenario.scenario_id:
            raise ValueError(
                f"scenario chunk {i + 1} has mismatched scenarioId '{scenario.scenario_id}' "
                f"(expected '{first_scenario.scenario_id}')"
            )

        if scenario.residents != first_scenario.residents:
            raise ValueError(f"scenario chunk {i + 1} has mismatched residents")

        if scenario.time_zone != first_scenario.time_zone:
            raise ValueError(f"scenario chunk {i + 1} has mismatched timezone")

        if scenario.seed != first_scenario.seed:
            raise ValueError(f"scenario chunk {i + 1} has mismatched seed")

        if scenario.model_references != first_scenario.model_references:
            raise ValueError(f"scenario chunk {i + 1} has mismatched modelReferences")

        # Topology comparison: locations & resources
        loc_topo_current = [(loc.location_id, loc.kind) for loc in scenario.locations]
        loc_topo_first = [(loc.location_id, loc.kind) for loc in first_scenario.locations]
        if loc_topo_current != loc_topo_first:
            raise ValueError(f"scenario chunk {i + 1} has mismatched location topology")

        res_topo_current = [
            (res.resource_id, res.resource_type, res.location_id, res.capacity)
            for res in scenario.resources
        ]
        res_topo_first = [
            (res.resource_id, res.resource_type, res.location_id, res.capacity)
            for res in first_scenario.resources
        ]
        if res_topo_current != res_topo_first:
            raise ValueError(f"scenario chunk {i + 1} has mismatched resource topology")

        # Window validation
        if scenario.simulation_window.start >= scenario.simulation_window.end:
            raise ValueError(
                f"scenario chunk {i + 1} has invalid window: start >= end"
            )

        if i > 0:
            prev_scenario = scenarios[i - 1]
            if scenario.simulation_window.start != prev_scenario.simulation_window.end:
                raise ValueError(
                    f"scenario chunk {i + 1} window start ({scenario.simulation_window.start}) "
                    f"is not contiguous with chunk {i} window end ({prev_scenario.simulation_window.end})"
                )

            # Later initialState.at check
            if scenario.initial_state.at != scenario.simulation_window.start:
                raise ValueError(
                    f"scenario chunk {i + 1} initialState.at ({scenario.initial_state.at}) "
                    f"must equal its window start ({scenario.simulation_window.start})"
                )

    return ResolvedLongitudinalInputs(
        manifest_path=manifest_path.resolve(),
        manifest=manifest,
        scenarios=tuple(scenarios),
        scenario_paths=tuple(scenario_paths),
        package=package,
        package_path=package_path,
        home_policy=home_policy,
        sensor_policy=sensor_policy,
        manifest_sha256=manifest_sha256,
        configuration_sha256=configuration_sha256,
    )
