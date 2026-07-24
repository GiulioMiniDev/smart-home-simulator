"""Deterministically build a persona's planning world (stage A2a): no LLM.

A ``PlanningWorld`` is the reusable, window-agnostic environment for one persona: locations,
resources, the resident, and the initial placement — everything a scenario needs except the days.
It is the deterministic front half of the machinery. The personal process package (stage A2b) is
authored against this world, and the executable home is materialised from it afterwards, because the
home's entity capabilities are derived from the package's actions (so the home cannot precede it).
``assemble_scenario`` later combines a world with generated days and a window into a full scenario.

NOTE (future extensibility): the apartment is a fixed, comprehensive standard template, with the
persona injected as resident. Deliberate for now — distinctiveness lives in the habits, days, and
process package, not the ADL home. A later version may generate a per-persona world (tailoring
locations/resources to the habits) behind this same ``PlanningWorld`` contract; keep that swap open.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import Field, model_validator

from smart_home_sim.domain.base import ContractModel
from smart_home_sim.domain.models import (
    AuthorType,
    DayPlan,
    ExternalPerson,
    InitialState,
    Location,
    LocationKind,
    ModelReferences,
    Provenance,
    Resident,
    ResidentInitialState,
    Resource,
    Scenario,
    SimulationWindow,
    VersionedReference,
)
from smart_home_sim.hybrid_planning.persona import Persona

GENERATOR_NAME = "smart-home-sim.hybrid_planning.world"
GENERATOR_VERSION = "1.0.0"

HOME_COMPOSITE_ID = "home"
STANDARD_ROOMS: tuple[str, ...] = ("bedroom", "kitchen", "bathroom", "living_room", "balcony")
STANDARD_EXTERNAL: tuple[str, ...] = ("outdoors",)

# (resource_id, resource_type, location_id) for the fixed standard apartment.
STANDARD_RESOURCES: tuple[tuple[str, str, str], ...] = (
    ("bed_01", "bed", "bedroom"),
    ("wardrobe_01", "wardrobe", "bedroom"),
    ("stove_01", "stove", "kitchen"),
    ("moka_01", "moka_coffee_maker", "kitchen"),
    ("refrigerator_01", "refrigerator", "kitchen"),
    ("sink_01", "sink", "kitchen"),
    ("kitchen_table_01", "table", "kitchen"),
    ("kitchen_chair_01", "chair", "kitchen"),
    ("medication_cabinet_01", "storage_cabinet", "kitchen"),
    ("shower_01", "shower", "bathroom"),
    ("toilet_01", "toilet", "bathroom"),
    ("washbasin_01", "washbasin", "bathroom"),
    ("washing_machine_01", "washing_machine", "bathroom"),
    ("sofa_01", "sofa", "living_room"),
    ("television_01", "television", "living_room"),
    ("radio_01", "radio", "living_room"),
    ("planter_01", "garden_planter", "balcony"),
)


class PlanningWorld(ContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    document_type: Literal["planning_world"] = "planning_world"
    world_id: str = Field(min_length=1)
    persona_id: str = Field(min_length=1)
    scenario_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    language: str = "en"
    time_zone: str = Field(min_length=1)
    seed: int
    home_model: VersionedReference
    activity_catalog: VersionedReference
    residents: list[Resident] = Field(min_length=1)
    external_people: list[ExternalPerson] = Field(default_factory=list)
    locations: list[Location] = Field(min_length=1)
    resources: list[Resource] = Field(default_factory=list)
    resident_placements: list[ResidentInitialState] = Field(min_length=1)
    resource_facts: dict[str, dict[str, object]] = Field(default_factory=dict)
    environment_facts: dict[str, object] = Field(default_factory=dict)
    provenance: Provenance

    @model_validator(mode="after")
    def check_location_references(self) -> PlanningWorld:
        primitive = {
            loc.location_id for loc in self.locations if loc.kind is not LocationKind.composite
        }
        known = {loc.location_id for loc in self.locations}
        for location in self.locations:
            for member in location.member_location_ids:
                if member not in known:
                    raise ValueError(f"composite location references unknown member {member!r}")
        for resource in self.resources:
            if resource.location_id not in primitive:
                raise ValueError(f"resource {resource.resource_id!r} references unknown location")
        for placement in self.resident_placements:
            if placement.location_id not in primitive:
                raise ValueError("resident placement references unknown location")
        return self


def build_planning_world(
    persona: Persona,
    *,
    seed: int = 1,
    activity_catalog_version: str = "1.0.0",
    home_model_version: str = "1.0.0",
    now: datetime | None = None,
) -> PlanningWorld:
    """Build the deterministic standard-apartment world for one persona."""
    locations = [Location(location_id=room, kind=LocationKind.room) for room in STANDARD_ROOMS]
    locations.extend(
        Location(location_id=name, kind=LocationKind.external) for name in STANDARD_EXTERNAL
    )
    locations.append(
        Location(
            location_id=HOME_COMPOSITE_ID,
            kind=LocationKind.composite,
            member_location_ids=list(STANDARD_ROOMS),
        )
    )
    resources = [
        Resource(resource_id=resource_id, resource_type=resource_type, location_id=location_id)
        for resource_id, resource_type, location_id in STANDARD_RESOURCES
    ]
    resource_facts = {resource.resource_id: {"available": True} for resource in resources}

    resident = Resident(
        resident_id=persona.persona_id,
        display_name=persona.name,
        profile={
            "age": persona.age,
            "sex": persona.sex,
            "occupation": persona.occupation,
            "household": persona.household,
            "health": persona.health,
            "city": persona.city,
        },
    )
    relative = ExternalPerson(
        external_person_id="relative_01",
        display_name="Relative",
        relationship_to_residents={persona.persona_id: "family"},
    )
    placement = ResidentInitialState(
        resident_id=persona.persona_id, location_id="bedroom", facts={"awake": False}
    )
    provenance = Provenance(
        author_type=AuthorType.rule_generator,
        generator_name=GENERATOR_NAME,
        generator_version=GENERATOR_VERSION,
        generated_at=now or datetime.now(UTC),
        parameters={"seed": seed},
    )
    return PlanningWorld(
        world_id=f"{persona.persona_id}_world",
        persona_id=persona.persona_id,
        scenario_id=f"{persona.persona_id}_scenario",
        title=f"Synthetic life of {persona.name}",
        time_zone=persona.timezone,
        seed=seed,
        home_model=VersionedReference(
            reference_id=f"{persona.persona_id}_home", version=home_model_version
        ),
        activity_catalog=VersionedReference(
            reference_id="activity_catalog", version=activity_catalog_version
        ),
        residents=[resident],
        external_people=[relative],
        locations=locations,
        resources=resources,
        resident_placements=[placement],
        resource_facts=resource_facts,
        provenance=provenance,
    )


def assemble_scenario(
    world: PlanningWorld,
    *,
    days: list[DayPlan],
    window: SimulationWindow,
    seed: int | None = None,
    provenance: Provenance | None = None,
) -> Scenario:
    """Combine a world with generated days and a window into a full, structurally valid scenario."""
    return Scenario(
        schema_version="1.0.0",
        scenario_id=world.scenario_id,
        title=world.title,
        language=world.language,
        time_zone=world.time_zone,
        simulation_window=window,
        seed=world.seed if seed is None else seed,
        provenance=provenance
        or Provenance(
            author_type=AuthorType.rule_generator,
            generator_name=GENERATOR_NAME,
            generator_version=GENERATOR_VERSION,
            generated_at=window.start,
        ),
        model_references=ModelReferences(
            activity_catalog=world.activity_catalog, home_model=world.home_model
        ),
        residents=world.residents,
        external_people=world.external_people,
        locations=world.locations,
        resources=world.resources,
        initial_state=InitialState(
            at=window.start,
            residents=world.resident_placements,
            resource_facts=world.resource_facts,
            environment_facts=world.environment_facts,
        ),
        days=days,
    )
