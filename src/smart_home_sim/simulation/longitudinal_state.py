from __future__ import annotations

from shapely.geometry import Point as ShapelyPoint
from shapely.geometry import Polygon

from smart_home_sim.domain.environment import SimulationBundle
from smart_home_sim.domain.execution import FinalWorldState, SimulationIssue


def validate_handoff(
    bundle: SimulationBundle,
    state: FinalWorldState,
) -> list[SimulationIssue]:
    issues: list[SimulationIssue] = []

    # 1. Timestamp match
    if state.at != bundle.scenario.simulation_window.start:
        issues.append(
            SimulationIssue(
                code="INITIAL_WORLD_STATE_INVALID",
                stage="preflight",
                path="$.at",
                message=f"Initial world state timestamp '{state.at}' does not match simulation window start '{bundle.scenario.simulation_window.start}'.",
            )
        )

    # Build region boundaries map
    regions = {
        item.region_id: Polygon([(p.x, p.y) for p in item.boundary.vertices])
        for item in bundle.home_model.regions
    }
    scenario_resident_ids = {r.resident_id for r in bundle.scenario.residents}
    state_resident_ids = {r.resident_id for r in state.residents}

    # 2. Resident matching
    missing_residents = scenario_resident_ids - state_resident_ids
    if missing_residents:
        issues.append(
            SimulationIssue(
                code="INITIAL_WORLD_STATE_INVALID",
                stage="preflight",
                path="$.residents",
                message=f"Initial world state is missing resident(s): {sorted(missing_residents)}.",
            )
        )

    # 3. Resident region, position, and held resources
    for resident in state.residents:
        if resident.resident_id not in scenario_resident_ids:
            issues.append(
                SimulationIssue(
                    code="INITIAL_WORLD_STATE_INVALID",
                    stage="preflight",
                    path="$.residents",
                    message=f"Unknown resident '{resident.resident_id}' in initial world state.",
                )
            )
            continue

        region_poly = regions.get(resident.region_id)
        if region_poly is None:
            issues.append(
                SimulationIssue(
                    code="INITIAL_WORLD_STATE_INVALID",
                    stage="preflight",
                    path=f"$.residents[{resident.resident_id}].regionId",
                    message=f"Resident '{resident.resident_id}' is in unknown region '{resident.region_id}'.",
                )
            )
        else:
            point = ShapelyPoint(resident.position.x, resident.position.y)
            if not region_poly.covers(point):
                issues.append(
                    SimulationIssue(
                        code="INITIAL_WORLD_STATE_INVALID",
                        stage="preflight",
                        path=f"$.residents[{resident.resident_id}].position",
                        message=f"Resident '{resident.resident_id}' position ({resident.position.x}, {resident.position.y}) is outside region '{resident.region_id}'.",
                    )
                )

        if resident.held_resource_ids:
            issues.append(
                SimulationIssue(
                    code="INITIAL_WORLD_STATE_INVALID",
                    stage="preflight",
                    path=f"$.residents[{resident.resident_id}].heldResourceIds",
                    message=f"Resident '{resident.resident_id}' holds resources at boundary, which is invalid.",
                )
            )

    # 4. Entity states validation
    known_entity_ids = {e.entity_id for e in bundle.home_model.entities}
    for entity_id in state.entity_states:
        if entity_id not in known_entity_ids:
            issues.append(
                SimulationIssue(
                    code="INITIAL_WORLD_STATE_INVALID",
                    stage="preflight",
                    path=f"$.entityStates.{entity_id}",
                    message=f"Unknown entity '{entity_id}' in initial world state.",
                )
            )

    # 5. Resource capacity validation
    resource_capacities = {res.resource_id: res.capacity for res in bundle.scenario.resources}
    for res_id, cap in resource_capacities.items():
        avail = state.resource_available_units.get(res_id)
        if avail != cap:
            issues.append(
                SimulationIssue(
                    code="INITIAL_WORLD_STATE_INVALID",
                    stage="preflight",
                    path=f"$.resourceAvailableUnits.{res_id}",
                    message=f"Resource '{res_id}' available units ({avail}) does not match capacity ({cap}).",
                )
            )

    return issues
