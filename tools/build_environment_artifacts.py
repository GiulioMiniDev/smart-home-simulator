from __future__ import annotations

import json
from pathlib import Path

from smart_home_sim.domain.environment import (
    ConnectionKind,
    EntityCapability,
    HomeConnection,
    HomeEntity,
    HomeModel,
    HomeObstacle,
    HomeRegion,
    InteractionPoint,
    LocationBinding,
    Point2D,
    Polygon2D,
    RegionKind,
    ResourceBinding,
    TraversalMode,
)

ROOT = Path(__file__).parents[1]


def rectangle(x: float, y: float, width: float = 6.0, height: float = 6.0) -> Polygon2D:
    return Polygon2D(
        vertices=[
            Point2D(x=x, y=y),
            Point2D(x=x + width, y=y),
            Point2D(x=x + width, y=y + height),
            Point2D(x=x, y=y + height),
        ]
    )


def capability(name: str, roles: list[str], operations: list[str]) -> EntityCapability:
    return EntityCapability(capability=name, roles=roles, supported_operations=operations)


def build_home() -> HomeModel:
    home_region_ids = [
        "bedroom",
        "bathroom",
        "hallway",
        "entrance",
        "kitchen",
        "living_room",
        "balcony",
    ]
    external_region_ids = [
        "market",
        "mothers_home",
        "neighborhood_bar",
        "outside",
        "pharmacy",
        "supermarket",
        "workplace",
    ]
    # A compact but believable apartment: the hallway is the circulation spine,
    # the entrance opens into it, and the balcony extends from the living room.
    origins: dict[str, tuple[float, float]] = {
        "bedroom": (0.0, 6.0),
        "bathroom": (0.0, 0.0),
        "hallway": (7.0, 3.0),
        "entrance": (7.0, 0.0),
        "kitchen": (11.0, 0.0),
        "living_room": (11.0, 6.0),
        "balcony": (20.0, 7.0),
    }
    dimensions = {
        "bedroom": (7.0, 6.0),
        "bathroom": (7.0, 6.0),
        "hallway": (4.0, 7.0),
        "entrance": (4.0, 3.0),
        "kitchen": (7.0, 6.0),
        "living_room": (9.0, 6.0),
        "balcony": (3.0, 5.0),
    }
    origins.update(
        {region_id: (index * 8.0, 18.0) for index, region_id in enumerate(external_region_ids)}
    )
    dimensions.update({region_id: (6.0, 6.0) for region_id in external_region_ids})
    anchors = {
        "bedroom": (5.2, 9.0),
        "bathroom": (5.2, 3.0),
        "hallway": (9.0, 6.5),
        "entrance": (9.0, 1.2),
        "kitchen": (12.5, 1.5),
        "living_room": (13.0, 10.0),
        "balcony": (21.5, 9.5),
    }
    anchors.update(
        {
            region_id: (origin[0] + 3.0, origin[1] + 3.0)
            for region_id, origin in origins.items()
            if region_id in external_region_ids
        }
    )
    regions = [
        HomeRegion(
            region_id=region_id,
            kind=RegionKind.outdoor if region_id == "balcony" else RegionKind.room,
            boundary=rectangle(*origins[region_id], *dimensions[region_id]),
        )
        for region_id in home_region_ids
    ]
    regions.extend(
        HomeRegion(
            region_id=region_id,
            kind=RegionKind.outdoor if region_id == "outside" else RegionKind.external,
            boundary=rectangle(*origins[region_id], *dimensions[region_id]),
        )
        for region_id in external_region_ids
    )
    interaction_points = [
        InteractionPoint(
            interaction_point_id=f"ip_{region_id}_anchor",
            region_id=region_id,
            position=Point2D(x=anchors[region_id][0], y=anchors[region_id][1]),
        )
        for region_id in origins
    ]

    connections: list[HomeConnection] = []
    door_specs = [
        ("bathroom", "hallway", (6.6, 3.8), (7.4, 3.8)),
        ("bedroom", "hallway", (6.6, 8.5), (7.4, 8.5)),
        ("entrance", "hallway", (9.0, 2.6), (9.0, 3.4)),
        ("kitchen", "hallway", (11.4, 4.0), (10.6, 4.0)),
        ("living_room", "hallway", (11.4, 8.2), (10.6, 8.2)),
        ("living_room", "balcony", (19.6, 9.5), (20.4, 9.5)),
    ]
    for index, (left, right, portal_a, portal_b) in enumerate(door_specs):
        connections.append(
            HomeConnection(
                connection_id=f"door_{index + 1}_{left}_{right}",
                kind=ConnectionKind.doorway,
                region_a_id=left,
                region_b_id=right,
                portal_a=Point2D(x=portal_a[0], y=portal_a[1]),
                portal_b=Point2D(x=portal_b[0], y=portal_b[1]),
                width_meters=0.9,
            )
        )
    for index, region_id in enumerate(external_region_ids):
        connections.append(
            HomeConnection(
                connection_id=f"transit_{index + 1}_entrance_{region_id}",
                kind=ConnectionKind.transit,
                region_a_id="entrance",
                region_b_id=region_id,
                portal_a=Point2D(x=anchors["entrance"][0], y=anchors["entrance"][1]),
                portal_b=Point2D(x=anchors[region_id][0], y=anchors[region_id][1]),
                width_meters=1.0,
                traversal_mode=TraversalMode.transport,
                distance_meters=500.0 + index * 350.0,
            )
        )

    all_intents = [
        activity["intent"]
        for day in json.loads((ROOT / "examples/valid/mario_week.json").read_text())["days"]
        for activity in day["activities"]
    ]
    bedroom_roles = [
        "bag_storage",
        "clothing_storage",
        "document_storage",
        "ironing_area",
        "laundry_storage",
        "personal_belongings",
    ]
    bathroom_roles = [
        "cleaning_target",
        "personal_care_fixture",
        "shower",
        "sink",
        "toilet",
        "washing_machine",
    ]
    kitchen_roles = [
        "consumption_area",
        "drink_preparation_area",
        "food_preparation_area",
        "food_storage",
        "household_storage",
        "medication_storage",
        "reheating_area",
    ]
    living_roles = [
        "calendar",
        "communication_area",
        "document_storage",
        "dusting_area",
        "exercise_area",
        "social_area",
        "television",
        "tidying_area",
        "vacuum_cleaner",
    ]
    item_roles = [
        "cleaning_tool",
        "clothing",
        "dishware",
        "documents",
        "drink",
        "drink_ingredients",
        "dusting_tool",
        "floor",
        "household_supplies",
        "ingredients",
        "leftover_food",
        "medication",
        "personal_belongings",
        "prepared_food_portions",
        "prepared_meal",
        "prepared_salad",
        "purchases",
        "recycling",
        "recycling_bin",
        "salad_ingredients",
        "snack",
        "surfaces",
        "used_clothing",
        "vacuum_cleaner",
        "work_bag",
        "work_clothes",
    ]
    common_item_capabilities = [
        capability("graspable", item_roles, ["take_item"]),
        capability("storable", item_roles, ["put_item"]),
        capability("inspectable", ["calendar", "household_supplies"], ["inspect"]),
        capability("consumable", ["drink", "prepared_meal", "snack"], ["consume"]),
        capability("cleanable", [*item_roles, *sorted(set(all_intents))], ["clean"]),
        capability(
            "storage_support",
            [
                "documents",
                "prepared_food_portions",
                "work_bag",
                "work_clothes",
                *sorted(set(all_intents)),
            ],
            ["organize"],
        ),
    ]

    entities = [
        HomeEntity(
            entity_id="bedroom_storage",
            entity_type="storage_and_clothing",
            region_id="bedroom",
            interaction_point_id="ip_bedroom_anchor",
            capabilities=[
                capability("interaction_point", bedroom_roles, ["move_to_capability"]),
                capability("wearable", ["clothing", "work_clothes"], ["dress"]),
                *common_item_capabilities,
            ],
        ),
        HomeEntity(
            entity_id="bathroom_fixture",
            entity_type="bathroom_fixture_group",
            region_id="bathroom",
            interaction_point_id="ip_bathroom_anchor",
            initial_state={"active": False},
            capabilities=[
                capability("interaction_point", bathroom_roles, ["move_to_capability"]),
                capability("personal_care_support", [], ["personal_care"]),
                capability("laundry_support", [], ["laundry_step"]),
                capability("switchable", ["shower_water"], ["activate", "deactivate"]),
                *common_item_capabilities,
            ],
        ),
        HomeEntity(
            entity_id="entrance_access",
            entity_type="entrance_and_storage",
            region_id="entrance",
            interaction_point_id="ip_entrance_anchor",
            capabilities=[
                capability(
                    "interaction_point",
                    [
                        "home_entrance",
                        "home_exit",
                        "purchases",
                        "recycling_bin",
                        "recycling_storage",
                    ],
                    ["move_to_capability"],
                ),
                capability("home_egress", [], ["leave_home"]),
                capability("home_ingress", [], ["enter_home"]),
                *common_item_capabilities,
            ],
        ),
        HomeEntity(
            entity_id="kitchen_workstation",
            entity_type="kitchen_fixture_group",
            region_id="kitchen",
            interaction_point_id="ip_kitchen_anchor",
            initial_state={"open": False, "active": False},
            capabilities=[
                capability("interaction_point", kitchen_roles, ["move_to_capability"]),
                capability("openable", ["food_storage", "household_storage"], ["open", "close"]),
                capability(
                    "switchable",
                    [
                        "cooking_appliance",
                        "drink_appliance",
                        "reheating_appliance",
                        "sink_faucet",
                    ],
                    ["activate", "deactivate"],
                ),
                capability("food_preparation", [], ["prepare_food"]),
                capability("medication_support", [], ["manage_medication"]),
                *common_item_capabilities,
            ],
        ),
        HomeEntity(
            entity_id="living_room_media",
            entity_type="media_and_social_hub",
            region_id="living_room",
            interaction_point_id="ip_living_room_anchor",
            initial_state={"active": False},
            capabilities=[
                capability("interaction_point", living_roles, ["move_to_capability"]),
                capability(
                    "switchable",
                    ["television", "vacuum_cleaner"],
                    ["activate", "deactivate"],
                ),
                capability("communication", ["phone", "in_person"], ["communicate"]),
                capability("work_support", [], ["perform_work"]),
                capability("exercise_support", [], ["exercise"]),
                capability("leisure_support", [], ["leisure"]),
                *common_item_capabilities,
            ],
        ),
        HomeEntity(
            entity_id="balcony_utility",
            entity_type="drying_and_exercise_area",
            region_id="balcony",
            interaction_point_id="ip_balcony_anchor",
            capabilities=[
                capability("interaction_point", ["drying_area"], ["move_to_capability"]),
                capability("laundry_support", [], ["laundry_step"]),
                capability("exercise_support", [], ["exercise"]),
            ],
        ),
    ]
    external_roles = {
        "market": ["retail_area"],
        "mothers_home": ["social_area", "consumption_area"],
        "neighborhood_bar": ["social_area", "consumption_area"],
        "outside": ["walking_area", "exercise_area"],
        "pharmacy": ["pharmacy_counter", "retail_area"],
        "supermarket": ["retail_area"],
        "workplace": ["communication_area"],
    }
    for region_id, roles in external_roles.items():
        entities.append(
            HomeEntity(
                entity_id=f"{region_id}_service",
                entity_type="external_service",
                region_id=region_id,
                interaction_point_id=f"ip_{region_id}_anchor",
                capabilities=[
                    capability("interaction_point", roles, ["move_to_capability"]),
                    capability("retail_service", [], ["shop"]),
                    capability("communication", ["in_person", "phone"], ["communicate"]),
                    capability("work_support", [], ["perform_work"]),
                    capability("exercise_support", [], ["exercise"]),
                    capability("leisure_support", [], ["leisure"]),
                    capability("consumable", ["drink", "prepared_meal", "snack"], ["consume"]),
                    capability("graspable", ["medication", "purchases"], ["take_item"]),
                ],
            )
        )

    location_bindings = [
        LocationBinding(
            scenario_location_id=region_id,
            region_ids=[region_id],
            anchor_interaction_point_id=f"ip_{region_id}_anchor",
        )
        for region_id in origins
    ]
    composites = {
        "home": ["entrance", "hallway", "bedroom", "bathroom", "kitchen", "living_room", "balcony"],
        "bathroom_and_bedroom": ["bathroom", "bedroom"],
        "bedroom_and_kitchen": ["bedroom", "kitchen"],
        "bedroom_hallway_living_room": ["hallway", "bedroom", "living_room"],
        "home_and_kitchen": [
            "entrance",
            "hallway",
            "bedroom",
            "bathroom",
            "kitchen",
            "living_room",
            "balcony",
        ],
        "kitchen_and_balcony": ["kitchen", "balcony"],
        "living_room_and_hallway": ["living_room", "hallway"],
    }
    for location_id, region_ids in composites.items():
        anchor_region = region_ids[0]
        location_bindings.append(
            LocationBinding(
                scenario_location_id=location_id,
                region_ids=region_ids,
                anchor_interaction_point_id=f"ip_{anchor_region}_anchor",
            )
        )
    resource_entities = {
        "bed_01": "bedroom_storage",
        "shower_01": "bathroom_fixture",
        "toilet_01": "bathroom_fixture",
        "washing_machine_01": "bathroom_fixture",
        "kitchen_sink_01": "kitchen_workstation",
        "fridge_01": "kitchen_workstation",
        "kettle_01": "kitchen_workstation",
        "stove_01": "kitchen_workstation",
        "television_01": "living_room_media",
    }
    return HomeModel(
        home_id="home_mario_monteverde",
        home_version="mario-apartment-0.1-example",
        regions=regions,
        connections=connections,
        obstacles=[
            HomeObstacle(
                obstacle_id="bedroom_bed",
                region_id="bedroom",
                boundary=rectangle(0.8, 8.0, 3.2, 3.0),
            ),
            HomeObstacle(
                obstacle_id="bathroom_cabinet",
                region_id="bathroom",
                boundary=rectangle(0.5, 0.5, 1.2, 1.0),
            ),
            HomeObstacle(
                obstacle_id="kitchen_island",
                region_id="kitchen",
                boundary=rectangle(14.5, 2.0, 2.0, 2.0),
            ),
            HomeObstacle(
                obstacle_id="living_room_table",
                region_id="living_room",
                boundary=rectangle(16.0, 8.0, 1.5, 1.5),
            ),
        ],
        interaction_points=interaction_points,
        entities=entities,
        location_bindings=location_bindings,
        resource_bindings=[
            ResourceBinding(scenario_resource_id=resource_id, entity_id=entity_id)
            for resource_id, entity_id in resource_entities.items()
        ],
    )


def main() -> None:
    output = ROOT / "examples/environment/mario_monteverde.home.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        build_home().model_dump_json(by_alias=True, indent=2) + "\n", encoding="utf-8"
    )
    from smart_home_sim.environment import build_bundle_files

    result = build_bundle_files(
        ROOT / "examples/valid/mario_week.json",
        ROOT / "examples/compiled/mario_week.plan.json",
        ROOT / "examples/behavior/mario_rossi_week_2026_10_12.behavior.json",
        output,
    )
    if result.bundle is None:
        raise RuntimeError(result.report.model_dump_json(by_alias=True, indent=2))
    bundle_dir = ROOT / "examples/bundles"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    (bundle_dir / "mario_week.simulation-bundle.json").write_text(
        result.bundle.model_dump_json(by_alias=True, indent=2) + "\n", encoding="utf-8"
    )
    (bundle_dir / "mario_week.environment-report.json").write_text(
        result.report.model_dump_json(by_alias=True, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
